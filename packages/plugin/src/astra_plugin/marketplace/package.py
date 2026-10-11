"""``astra-package.yaml`` 包清单与 ``AstraPackageManifest``（W8 裁定 §3.1 / R1）。

冻结字段（设计 §2.13.1 L694）：``kind`` / ``name`` / ``version``(SemVer) /
``core_compat`` / ``manifest_path`` / ``author`` / ``license`` / 依赖清单 /
``artifact_sha256``（另支持可选 ``signature``，R11）。

- :class:`AstraPackageManifest`：``astra-package.yaml`` 的 ``frozen`` schema；
- :func:`manifest_from_dict` / :func:`manifest_to_dict`：字典 ↔ 清单（**无损往返**）；
- :func:`parse_manifest` / :func:`load_manifest`：文件 / 目录 → 清单；
- :func:`satisfies_core_compat`：``core_compat`` 兼容区间校验（发布/导入用）；
- :func:`compute_sha256`：字节摘要（归档字节 → ``artifact_sha256``，R8）。

🔴 本模块**零 Web / ORM**：仅依赖标准库 + ``astra_core`` +（间接）:mod:`.serialize`。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

from astra_plugin.marketplace.serialize import load, read_text

__all__ = [
    "PACKAGE_MANIFEST_FILE",
    "KIND_AGENT",
    "KIND_SKILL",
    "KIND_WORKFLOW",
    "VALID_KINDS",
    "NAME_PATTERN",
    "VERSION_PATTERN",
    "DEFAULT_CORE_VERSION",
    "AstraPackageManifest",
    "version_key",
    "parse_core_compat",
    "satisfies_core_compat",
    "manifest_from_dict",
    "manifest_to_dict",
    "parse_manifest",
    "load_manifest",
    "compute_sha256",
]

#: 包清单文件名（冻结）。
PACKAGE_MANIFEST_FILE = "astra-package.yaml"

#: 资源种类枚举。
KIND_AGENT = "agent"
KIND_SKILL = "skill"
KIND_WORKFLOW = "workflow"
VALID_KINDS: frozenset[str] = frozenset({KIND_AGENT, KIND_SKILL, KIND_WORKFLOW})

#: 包名合法模式（复用 ``astra_skill.SKILL_NAME_PATTERN`` 口径；本处**自含定义**，R1）。
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: 语义化版本模式（``MAJOR.MINOR.PATCH``）。
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: 当前 core 版本默认值（可被调用方覆盖；W8 施工口径 v0.4）。
DEFAULT_CORE_VERSION = "0.4.0"

#: ``core_compat`` 单子句模式（``>=0.4.0`` / ``~=0.4.0`` …）。
_COMPAT_CLAUSE_PATTERN = re.compile(r"^(>=|<=|==|!=|>|<|~=)(\d+\.\d+\.\d+)$")

#: 十六进制 SHA-256 模式。
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_OPERATORS: frozenset[str] = frozenset({">=", "<=", "==", "!=", ">", "<", "~="})


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``（复用既有错误码，不新增）。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def version_key(version: str) -> tuple[int, int, int]:
    """把语义化版本解析为可比较元组（非法版本回退 ``(0, 0, 0)``）。"""
    match = VERSION_PATTERN.match(str(version))
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _next_minor(key: tuple[int, int, int]) -> tuple[int, int, int]:
    """``~=X.Y.Z`` 的上界（``< X.(Y+1).0``）。"""
    return (key[0], key[1] + 1, 0)


def parse_core_compat(spec: str) -> tuple[tuple[str, tuple[int, int, int]], ...]:
    """解析 ``core_compat`` 兼容区间为 ``((op, version_key), ...)``。

    Args:
        spec: 形如 ``">=0.4.0,<0.5.0"`` 的区间串（逗号分隔）。

    Returns:
        子句序列；空串 → 空元组（表示**无约束**）。

    Raises:
        DomainError: 子句语法非法（``VALIDATION_ERROR``）。
    """
    if spec is None or str(spec).strip() == "":
        return ()
    clauses: list[tuple[str, tuple[int, int, int]]] = []
    for raw in str(spec).split(","):
        clause = raw.strip()
        if not clause:
            continue
        match = _COMPAT_CLAUSE_PATTERN.match(clause)
        if not match or match.group(1) not in _OPERATORS:
            raise _validation_error("core_compat 子句非法", clause=clause)
        clauses.append((match.group(1), version_key(match.group(2))))
    return tuple(clauses)


def satisfies_core_compat(spec: str, core_version: str) -> bool:
    """判断 ``core_version`` 是否满足 ``core_compat`` 区间。

    无区间（空串）→ ``True``。``~=X.Y.Z`` 语义 = ``>=X.Y.Z`` 且 ``<X.(Y+1).0``。
    """
    clauses = parse_core_compat(spec)
    if not clauses:
        return True
    current = version_key(core_version)
    for op, bound in clauses:
        if op == ">=" and not current >= bound:
            return False
        if op == "<=" and not current <= bound:
            return False
        if op == ">" and not current > bound:
            return False
        if op == "<" and not current < bound:
            return False
        if op == "==" and not current == bound:
            return False
        if op == "!=" and current == bound:
            return False
        if op == "~=" and not (bound <= current < _next_minor(bound)):
            return False
    return True


def compute_sha256(payload: bytes) -> str:
    """计算 ``payload`` 的 SHA-256 十六进制摘要（R8 归档摘要口径）。"""
    return hashlib.sha256(payload).hexdigest()


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把 YAML 列表字段归一化为字符串元组。"""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclass(frozen=True)
class AstraPackageManifest:
    """``astra-package.yaml`` 清单（冻结字段；§3.1）。

    Attributes:
        kind: 资源种类（``agent`` / ``skill`` / ``workflow``）。
        name: 包名（``^[a-z0-9][a-z0-9._-]{1,63}$``）。
        version: 语义化版本（``MAJOR.MINOR.PATCH``，**不可覆盖**）。
        core_compat: 兼容区间（如 ``>=0.4.0,<0.5.0``）。
        manifest_path: 资源清单相对路径（``agent.yaml`` / ``skill.yaml`` / ``workflow.yaml``）。
        author: 作者。
        license: 许可标识（SPDX 或自定义）。
        dependencies: 依赖清单（字符串引用，**不 import**）。
        artifact_sha256: 归档摘要（发布时重算并写回；R8）。
        signature: 签名（可选；提供则校验，R11）。
        description: 描述（可选）。
        extra: 未知字段（无损往返保留）。
    """

    kind: str
    name: str
    version: str
    core_compat: str = ""
    manifest_path: str = ""
    author: str = ""
    license: str = ""
    dependencies: tuple[str, ...] = ()
    artifact_sha256: str = ""
    signature: str = ""
    description: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def signature_present(self) -> bool:
        """是否携带签名（R11：缺失则以 ``signature_present=false`` 明示）。"""
        return bool(self.signature)

    @property
    def identity(self) -> tuple[str, str, str]:
        """唯一标识 ``(kind, name, version)``（版本不可覆盖判定用）。"""
        return (self.kind, self.name, self.version)

    def validate(self) -> None:
        """校验清单字段合法性。

        Raises:
            DomainError: 任一字段非法（``VALIDATION_ERROR``）。
        """
        if self.kind not in VALID_KINDS:
            raise _validation_error("astra-package.yaml: kind 非法", field="kind", value=self.kind)
        if not isinstance(self.name, str) or not NAME_PATTERN.match(self.name):
            raise _validation_error(
                "astra-package.yaml: name 缺失或非法", field="name", value=self.name
            )
        if not isinstance(self.version, str) or not VERSION_PATTERN.match(self.version):
            raise _validation_error(
                "astra-package.yaml: version 缺失或非语义化版本",
                field="version",
                value=self.version,
            )
        if not isinstance(self.manifest_path, str) or not self.manifest_path.strip():
            raise _validation_error("astra-package.yaml: manifest_path 缺失", field="manifest_path")
        # core_compat 语法校验（空 = 无约束）。
        parse_core_compat(self.core_compat)
        # 依赖项须为非空字符串。
        for index, dependency in enumerate(self.dependencies):
            if not isinstance(dependency, str) or not dependency.strip():
                raise _validation_error(
                    "astra-package.yaml: 依赖项非法", field="dependencies", index=index
                )
        # artifact_sha256：非空时须为 64 位十六进制。
        if self.artifact_sha256 and not _SHA256_PATTERN.match(self.artifact_sha256):
            raise _validation_error(
                "astra-package.yaml: artifact_sha256 非法", field="artifact_sha256"
            )

    def satisfies_core(self, core_version: str) -> bool:
        """本包 ``core_compat`` 是否兼容给定 ``core_version``。"""
        return satisfies_core_compat(self.core_compat, core_version)


def manifest_from_dict(data: Mapping[str, Any]) -> AstraPackageManifest:
    """由解析字典构造并校验 :class:`AstraPackageManifest`。

    Raises:
        DomainError: 顶层非映射、缺 ``kind`` / ``name`` / ``version`` 或取值非法
            （``VALIDATION_ERROR``）。
    """
    if not isinstance(data, Mapping):
        raise _validation_error("astra-package.yaml 顶层须为映射", field="astra-package")
    known = {
        "kind",
        "name",
        "version",
        "core_compat",
        "manifest_path",
        "author",
        "license",
        "dependencies",
        "artifact_sha256",
        "signature",
        "description",
    }
    extra = {str(key): value for key, value in data.items() if str(key) not in known}
    manifest = AstraPackageManifest(
        kind=str(data.get("kind") or ""),
        name=str(data.get("name") or ""),
        version=str(data.get("version") or ""),
        core_compat=str(data.get("core_compat") or ""),
        manifest_path=str(data.get("manifest_path") or ""),
        author=str(data.get("author") or ""),
        license=str(data.get("license") or ""),
        dependencies=_as_str_tuple(data.get("dependencies")),
        artifact_sha256=str(data.get("artifact_sha256") or ""),
        signature=str(data.get("signature") or ""),
        description=str(data.get("description") or ""),
        extra=extra,
    )
    manifest.validate()
    return manifest


def manifest_to_dict(manifest: AstraPackageManifest) -> dict[str, Any]:
    """把清单序列化为字典（**无损往返**；未知字段原样保留）。"""
    data: dict[str, Any] = {str(key): value for key, value in manifest.extra.items()}
    data.update(
        {
            "kind": manifest.kind,
            "name": manifest.name,
            "version": manifest.version,
            "core_compat": manifest.core_compat,
            "manifest_path": manifest.manifest_path,
            "author": manifest.author,
            "license": manifest.license,
            "dependencies": list(manifest.dependencies),
            "artifact_sha256": manifest.artifact_sha256,
        }
    )
    if manifest.signature:
        data["signature"] = manifest.signature
    if manifest.description:
        data["description"] = manifest.description
    return data


def parse_manifest(path: Path) -> AstraPackageManifest:
    """解析 ``astra-package.yaml``（``path`` 指向该文件）。

    Raises:
        DomainError: 文件不存在 / YAML 非法 / 字段校验失败（``VALIDATION_ERROR``）。
    """
    target = Path(path)
    if not target.is_file():
        raise _validation_error("astra-package.yaml 不存在", path=str(target))
    return manifest_from_dict(load(read_text(target)) or {})


def load_manifest(directory: Path) -> AstraPackageManifest:
    """从包目录装载 ``astra-package.yaml``。

    Raises:
        DomainError: 目录不存在 / 清单缺失或非法（``VALIDATION_ERROR``）。
    """
    root = Path(directory)
    if root.is_file():
        root = root.parent
    if not root.is_dir():
        raise _validation_error("包目录不存在", path=str(root))
    return parse_manifest(root / PACKAGE_MANIFEST_FILE)
