"""市场包导入：schema + 依赖 + 敏感静态校验（W8 裁定 R12 / R13 / §3.1）。

- :func:`scan_sensitive`：对 YAML **值**做明文凭据启发式扫描（高熵串 / 常见 token
  前缀 / ``password|secret|token|key`` 键名 + 明文值），命中 → ``DomainError``
  （``VALIDATION_ERROR``），**不落库**（R12；发布与导入**两侧均扫**）；
- :func:`validate_dependencies`：依赖清单格式校验；
- :func:`validate`：清单 schema + ``core_compat`` 兼容区间校验；
- :class:`PackageInspection` / :func:`inspect`：安装前元数据（作者 / 版本 / 兼容 /
  依赖 / 摘要 / 签名有无，R11）；
- :class:`ImportedPackage` / :func:`import_package`：目录导入（**同名同版本异摘要拒绝**，R13）。

🔴 零 Web / ORM：仅依赖标准库 + ``astra_core`` + 同子包 ``package`` / ``schema`` / ``serialize``。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

from astra_plugin.marketplace.package import (
    DEFAULT_CORE_VERSION,
    AstraPackageManifest,
    load_manifest,
    manifest_to_dict,
    satisfies_core_compat,
)
from astra_plugin.marketplace.schema import normalize_resource
from astra_plugin.marketplace.serialize import canonical_dump, load, read_text

__all__ = [
    "SENSITIVE_KEY_PATTERN",
    "TOKEN_VALUE_PATTERNS",
    "PackageInspection",
    "ImportedPackage",
    "scan_sensitive",
    "validate_dependencies",
    "validate",
    "inspect",
    "inspect_manifest",
    "load_resource",
    "content_digest",
    "import_package",
    "load_package",
]

#: 敏感键名模式（命中且给**明文标量** → 拒绝；R12）。
SENSITIVE_KEY_PATTERN = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)",
    re.IGNORECASE,
)

#: 常见凭证明文前缀特征（保守；命中即拒）。
TOKEN_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

#: 高熵 token 判定参数（无空白 + base64 字符集 + 长度/熵阈值，避免误伤自然语言）。
_TOKEN_CHARSET = re.compile(r"^[A-Za-z0-9+/=_\-]+$")
_HIGH_ENTROPY_MIN_LEN = 20
_HIGH_ENTROPY_THRESHOLD = 4.2

#: 敏感扫描递归深度上限（超深嵌套 → ``VALIDATION_ERROR``，避免裸 ``RecursionError``）。
_MAX_SCAN_DEPTH = 200

#: 占位符标记（命中则视为**非真实凭据**，不报错）。
_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "change-me",
    "changeme",
    "replace",
    "example",
    "placeholder",
    "your-",
    "dummy",
    "todo",
    "<",
    ">",
    "xxx",
    "****",
)

#: 引用形值（``{$ref: ...}`` / ``credential:`` / ``secret:``）——不视为明文。
_REF_PREFIXES: tuple[str, ...] = ("credential:", "secret:", "$ref:")


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def _conflict_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``CONFLICT``。"""
    return DomainError(message, code=ErrorCode.CONFLICT, data=dict(data))


def _shannon_entropy(text: str) -> float:
    """计算字符串的 Shannon 熵（比特/字符）。"""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_placeholder(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_high_entropy_token(text: str) -> bool:
    """判定字符串是否为高熵 token（保守；避免误伤普通描述文本）。"""
    if len(text) < _HIGH_ENTROPY_MIN_LEN:
        return False
    if not _TOKEN_CHARSET.match(text):
        return False
    has_letter = any(char.isalpha() for char in text)
    has_other = any(char.isdigit() or char in "+/=_-" for char in text)
    if not (has_letter and has_other):
        return False
    return _shannon_entropy(text) >= _HIGH_ENTROPY_THRESHOLD


def _is_reference(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(_REF_PREFIXES)


def _value_finding(key: str, value: str) -> str | None:
    """返回单值的命中原因（``None`` 表示无命中）。"""
    if not value or _is_reference(value):
        return None
    if _looks_like_placeholder(value):
        return None
    for pattern in TOKEN_VALUE_PATTERNS:
        if pattern.search(value):
            return "token-prefix"
    if _is_high_entropy_token(value):
        return "high-entropy"
    if SENSITIVE_KEY_PATTERN.search(key) and len(value) >= 8:
        return "sensitive-key"
    return None


def scan_sensitive(data: Any, *, path: str = "") -> None:
    """对 YAML **值**做明文凭据启发式扫描（递归；R12）。

    Args:
        data: 任意 JSON-ish 结构（映射 / 序列 / 标量）。
        path: 当前路径前缀（递归内部使用）。

    Raises:
        DomainError: 命中明文凭据（``VALIDATION_ERROR``）；**不包含原文明文**，
            仅含命中路径与原因（避免二次泄漏）。
    """
    findings: list[dict[str, str]] = []

    def _walk(node: Any, prefix: str, depth: int) -> None:
        if depth > _MAX_SCAN_DEPTH:
            raise _validation_error(
                "包内容嵌套过深（超出扫描上限）",
                reason="too_deep",
                limit=_MAX_SCAN_DEPTH,
            )
        if isinstance(node, Mapping):
            for key, value in node.items():
                name = str(key)
                child = f"{prefix}.{name}" if prefix else name
                if isinstance(value, Mapping):
                    _walk(value, child, depth + 1)
                elif isinstance(value, (list, tuple)):
                    for index, item in enumerate(value):
                        _walk(item, f"{child}[{index}]", depth + 1)
                else:
                    reason = _value_finding(name, str(value))
                    if reason is not None:
                        findings.append({"path": child, "reason": reason})
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                _walk(item, f"{prefix}[{index}]", depth + 1)

    _walk(data, path, 0)
    if findings:
        raise _validation_error(
            "包内容含疑似明文凭据（禁止明文，需改用引用）",
            findings=findings[:20],
            count=len(findings),
        )


def validate_dependencies(dependencies: tuple[str, ...]) -> None:
    """校验依赖清单（每项为非空字符串）。

    Raises:
        DomainError: 依赖项非法（``VALIDATION_ERROR``）。
    """
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, str) or not dependency.strip():
            raise _validation_error("依赖项非法", field="dependencies", index=index)


def validate(manifest: AstraPackageManifest, *, core_version: str = DEFAULT_CORE_VERSION) -> None:
    """校验清单 schema + ``core_compat`` 兼容区间（发布/导入共用）。

    Raises:
        DomainError: 清单非法或 ``core_compat`` 与 ``core_version`` 不兼容
            （``VALIDATION_ERROR``）。
    """
    manifest.validate()
    if not satisfies_core_compat(manifest.core_compat, core_version):
        raise _validation_error(
            "core_compat 与当前 core 版本不兼容",
            field="core_compat",
            core_compat=manifest.core_compat,
            core_version=core_version,
        )


@dataclass(frozen=True)
class PackageInspection:
    """安装前元数据（Studio 展示用；R5 / R14）。

    Attributes:
        kind / name / version / core_compat / author / license / manifest_path: 清单字段。
        dependencies: 依赖清单。
        artifact_sha256: 归档摘要（可能为空）。
        signature_present: 是否携带签名（R11）。
        core_compatible: 是否与当前 core 兼容。
        valid: 校验是否通过。
        errors: 校验错误信息（人类可读）。
    """

    kind: str
    name: str
    version: str
    core_compat: str
    author: str
    license: str
    dependencies: tuple[str, ...]
    artifact_sha256: str
    signature_present: bool
    manifest_path: str
    core_compatible: bool
    valid: bool
    errors: tuple[str, ...] = ()


def inspect_manifest(
    manifest: AstraPackageManifest, *, core_version: str = DEFAULT_CORE_VERSION
) -> PackageInspection:
    """由清单构造 :class:`PackageInspection`（不抛错，错误收敛进 ``errors``）。"""
    errors: list[str] = []
    try:
        manifest.validate()
    except DomainError as exc:
        errors.append(exc.message)
    core_compatible = satisfies_core_compat(manifest.core_compat, core_version)
    if not core_compatible:
        errors.append("core_compat 与当前 core 版本不兼容")
    validate_dependencies(manifest.dependencies)
    return PackageInspection(
        kind=manifest.kind,
        name=manifest.name,
        version=manifest.version,
        core_compat=manifest.core_compat,
        author=manifest.author,
        license=manifest.license,
        dependencies=manifest.dependencies,
        artifact_sha256=manifest.artifact_sha256,
        signature_present=manifest.signature_present,
        manifest_path=manifest.manifest_path,
        core_compatible=core_compatible,
        valid=not errors,
        errors=tuple(errors),
    )


def inspect(text: str, *, core_version: str = DEFAULT_CORE_VERSION) -> PackageInspection:
    """解析 ``astra-package.yaml`` 文本并生成安装前元数据。

    Raises:
        DomainError: YAML 非法或清单字段非法（``VALIDATION_ERROR``）。
    """
    from astra_plugin.marketplace.package import manifest_from_dict

    return inspect_manifest(manifest_from_dict(load(text) or {}), core_version=core_version)


def load_resource(text: str, *, kind: str) -> dict[str, Any]:
    """解析并**规范化**资源清单文本（schema 校验；幂等往返）。

    Raises:
        DomainError: YAML 非法或资源字段非法（``VALIDATION_ERROR``）。
    """
    data = load(text)
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise _validation_error("资源清单顶层须为映射", kind=kind)
    return normalize_resource(kind, data)


def content_digest(resource: Mapping[str, Any]) -> str:
    """资源内容的规范化摘要（``sha256(canonical_dump)``；同名同版本异摘要判定用）。"""
    from astra_plugin.marketplace.package import compute_sha256

    return compute_sha256(canonical_dump(resource).encode("utf-8"))


@dataclass(frozen=True)
class ImportedPackage:
    """目录导入结果。

    Attributes:
        manifest: 包清单。
        resource: 规范化资源字典。
        content_digest: 资源内容摘要。
        inspection: 安装前元数据。
    """

    manifest: AstraPackageManifest
    resource: Mapping[str, Any]
    content_digest: str
    inspection: PackageInspection


def import_package(
    directory: Path,
    *,
    core_version: str = DEFAULT_CORE_VERSION,
    known_digests: Mapping[tuple[str, str, str], str] | None = None,
) -> ImportedPackage:
    """从包目录导入：schema + 依赖 + 敏感校验；同名同版本异摘要拒绝（R13）。

    Args:
        directory: 包目录（含 ``astra-package.yaml`` 与资源清单）。
        core_version: 当前 core 版本（``core_compat`` 校验）。
        known_digests: 已知 ``{(kind, name, version): content_digest}``——命中且摘要
            不同 → ``DomainError(CONFLICT)``。

    Returns:
        :class:`ImportedPackage`。

    Raises:
        DomainError: 目录/清单/资源非法或敏感命中（``VALIDATION_ERROR``）；
            ``core_compat`` 越界（``VALIDATION_ERROR``）；同名同版本异摘要（``CONFLICT``）。
    """
    root = Path(directory)
    if root.is_file():
        root = root.parent
    manifest = load_manifest(root)
    validate(manifest, core_version=core_version)
    validate_dependencies(manifest.dependencies)
    scan_sensitive(manifest_to_dict(manifest))
    resource_path = root / manifest.manifest_path
    if not resource_path.is_file():
        raise _validation_error(
            "资源清单缺失", path=str(resource_path), manifest_path=manifest.manifest_path
        )
    resource = load_resource(read_text(resource_path), kind=manifest.kind)
    scan_sensitive(resource)
    digest = content_digest(resource)
    if known_digests is not None:
        existing = known_digests.get(manifest.identity)
        if existing is not None and existing != digest:
            raise _conflict_error(
                "同名同版本内容摘要不同，拒绝导入",
                kind=manifest.kind,
                name=manifest.name,
                version=manifest.version,
            )
    return ImportedPackage(
        manifest=manifest,
        resource=resource,
        content_digest=digest,
        inspection=inspect_manifest(manifest, core_version=core_version),
    )


def load_package(
    directory: Path,
    *,
    core_version: str = DEFAULT_CORE_VERSION,
    known_digests: Mapping[tuple[str, str, str], str] | None = None,
) -> ImportedPackage:
    """:func:`import_package` 的别名（门面 / 时序图命名对齐）。"""
    return import_package(directory, core_version=core_version, known_digests=known_digests)
