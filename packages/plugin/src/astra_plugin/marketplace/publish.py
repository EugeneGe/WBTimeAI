"""Marketplace 发布流程（W8 / T2-43；裁定 R8 / R9 / §2.13.1 L695 / §4.2）。

``astra marketplace publish <package-path> --registry <path>`` 的落地实现：

1. 加载并校验清单：schema + ``core_compat`` 兼容区间 + 依赖 + **敏感扫描**；
2. 规范化资源 → **确定性归档**（成员路径排序 + ``mtime=0`` + 固定 ``uid/gid=0`` /
   权限；gzip 时固定 ``mtime=0``；R8）；
3. ``artifact_sha256 = sha256(归档字节)``（归档内 ``astra-package.yaml`` 摘要置空以
   **避免自指**；最终摘要写回**旁挂** ``astra-package.yaml`` 与 ``index.json``）；
4. 幂等写入静态注册表：同版本异摘要**拒绝**、同摘要**跳过**、**原子替换**（R9/§4.2）；
5. 返回**变更摘要**（新增 / 跳过 / 拒绝）。

🔴 **不上传**任何托管服务：``--registry`` 仅接受**本地 Git 工作树 / 静态目录**，
HTTP(S) / Git URL 一律拒绝（对齐 §2.13.1 L695「不含市场账户或交易环节」）。
🔴 零 Web / ORM：仅依赖标准库 + ``astra_core`` + 同子包。
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from astra_core import DomainError, ErrorCode

from astra_plugin.marketplace.export import export_manifest_text
from astra_plugin.marketplace.import_ import scan_sensitive, validate, validate_dependencies
from astra_plugin.marketplace.index import IndexEntry, RegistryIndex
from astra_plugin.marketplace.package import (
    DEFAULT_CORE_VERSION,
    PACKAGE_MANIFEST_FILE,
    compute_sha256,
    load_manifest,
    manifest_to_dict,
)
from astra_plugin.marketplace.schema import normalize_resource
from astra_plugin.marketplace.serialize import (
    atomic_write_bytes,
    canonical_dump,
    load,
    read_text,
)

__all__ = ["PACKS_DIR", "PublishSummary", "build_archive", "publish_package"]

#: 注册表内版本包目录（冻结布局：``packs/<kind>/<name>/<version>/``）。
PACKS_DIR = "packs"

#: 托管 / 远程地址特征（**拒绝**；本命令仅写本地静态目录）。
_REMOTE_PATTERN = re.compile(r"^(?:https?://|git@|ssh://|git://|ftp://)", re.IGNORECASE)


def _validation_error(message: str, **data: object) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def _conflict_error(message: str, **data: object) -> DomainError:
    """构造统一 ``CONFLICT``。"""
    return DomainError(message, code=ErrorCode.CONFLICT, data=dict(data))


@dataclass(frozen=True)
class PublishSummary:
    """发布变更摘要（§4.2 步骤 4）。

    Attributes:
        kind / name / version: 包标识。
        artifact_sha256: 归档摘要。
        download: 归档相对路径（注册表内）。
        registry: 注册表目录。
        index_path: ``index.json`` 路径。
        outcome: ``added``（新增）/ ``skipped``（同摘要跳过）。
        message: 人类可读说明。
    """

    kind: str
    name: str
    version: str
    artifact_sha256: str
    download: str
    registry: str
    index_path: str
    outcome: str
    message: str

    @property
    def changed(self) -> bool:
        """本次是否**新增**（写入了版本包与索引）。"""
        return self.outcome == "added"

    @property
    def skipped(self) -> bool:
        """本次是否**幂等跳过**（同版本同摘要）。"""
        return self.outcome == "skipped"


def _resolve_package_dir(package_path: Path) -> Path:
    """解析包目录（文件路径 → 其父目录；校验存在）。"""
    root = Path(package_path)
    if root.is_file():
        root = root.parent
    if not root.is_dir():
        raise _validation_error("包目录不存在", path=str(root))
    return root


def _tar_bytes(files: Mapping[str, bytes]) -> bytes:
    """把 ``{相对路径: 字节}`` 打成**确定性**未压缩 tar（R8）。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_archive(files: Mapping[str, bytes], *, compress: bool = True) -> bytes:
    """构造**字节确定性**归档（R8）。

    Args:
        files: ``{相对路径: 字节}``（成员路径排序）。
        compress: ``True`` → 确定性 ``gzip``（``mtime=0``）``.tgz``；``False`` → 未压缩
            ``.tar``（跨平台兜底，R8 W8-A02）。

    Returns:
        归档字节（同输入 → 同输出）。
    """
    tar_bytes = _tar_bytes(files)
    if not compress:
        return tar_bytes
    return gzip.compress(tar_bytes, mtime=0)


def _collect_files(
    pkg_dir: Path,
    *,
    manifest_path: str,
    manifest_text: bytes,
    resource_text: bytes,
) -> dict[str, bytes]:
    """收集包内文件为归档成员（清单 / 资源清单用规范化内容覆盖）。"""
    files: dict[str, bytes] = {}
    for path in sorted(pkg_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(pkg_dir).as_posix()
        if relative in (PACKAGE_MANIFEST_FILE, manifest_path):
            continue  # 由规范化内容覆盖（清单摘要置空，避免自指）
        files[relative] = path.read_bytes()
    files[manifest_path] = resource_text
    files[PACKAGE_MANIFEST_FILE] = manifest_text
    return files


def publish_package(
    package_path: Path | str,
    registry: Path | str,
    *,
    core_version: str = DEFAULT_CORE_VERSION,
    compress: bool = True,
) -> PublishSummary:
    """发布本地包到**静态注册表**（幂等；不产生半成品）。

    Args:
        package_path: 包目录（含 ``astra-package.yaml``）或其清单路径。
        registry: 本地注册表根目录（Git 工作树 / 静态目录）。**拒绝**远程 URL。
        core_version: 当前 core 版本（``core_compat`` 校验）。
        compress: 是否 ``gzip``（默认 ``True``；``False`` → 未压缩 tar 兜底）。

    Returns:
        :class:`PublishSummary`（新增 / 跳过）。

    Raises:
        DomainError: 远程 registry（``CONFIGURATION_ERROR``）；清单 / 资源非法、
            ``core_compat`` 越界或敏感命中（``VALIDATION_ERROR``）；同名同版本异摘要
            （``CONFLICT``）。
    """
    registry_str = str(registry)
    if _REMOTE_PATTERN.match(registry_str):
        raise DomainError(
            "不支持上传托管服务；请提供本地 Git 工作树或静态目录路径",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"registry": registry_str},
        )

    pkg_dir = _resolve_package_dir(Path(package_path))
    registry_dir = Path(registry)

    manifest = load_manifest(pkg_dir)
    validate(manifest, core_version=core_version)
    validate_dependencies(manifest.dependencies)
    scan_sensitive(manifest_to_dict(manifest))

    resource_path = pkg_dir / manifest.manifest_path
    if not resource_path.is_file():
        raise _validation_error(
            "资源清单缺失", path=str(resource_path), manifest_path=manifest.manifest_path
        )
    resource = normalize_resource(manifest.kind, load(read_text(resource_path)) or {})
    scan_sensitive(resource)

    # 归档内容：清单摘要置空（避免自指）；资源规范化序列化。
    blank_manifest = manifest_to_dict(manifest)
    blank_manifest["artifact_sha256"] = ""
    files = _collect_files(
        pkg_dir,
        manifest_path=manifest.manifest_path,
        manifest_text=canonical_dump(blank_manifest).encode("utf-8"),
        resource_text=canonical_dump(resource).encode("utf-8"),
    )
    archive_bytes = build_archive(files, compress=compress)
    artifact_sha256 = compute_sha256(archive_bytes)

    extension = ".tgz" if compress else ".tar"
    filename = f"{manifest.name}-{manifest.version}{extension}"
    download = "/".join((PACKS_DIR, manifest.kind, manifest.name, manifest.version, filename))
    entry = IndexEntry(
        kind=manifest.kind,
        name=manifest.name,
        version=manifest.version,
        artifact_sha256=artifact_sha256,
        download=download,
        core_compat=manifest.core_compat,
        author=manifest.author,
        license=manifest.license,
    )

    index = RegistryIndex(registry_dir)
    existing = index.find(manifest.kind, manifest.name, manifest.version)
    if existing is not None:
        if index.is_idempotent(entry, existing):
            return PublishSummary(
                kind=manifest.kind,
                name=manifest.name,
                version=manifest.version,
                artifact_sha256=artifact_sha256,
                download=download,
                registry=registry_str,
                index_path=str(index.path),
                outcome="skipped",
                message="同版本同摘要，跳过（幂等）",
            )
        raise _conflict_error(
            "同名同版本异摘要，拒绝发布",
            kind=manifest.kind,
            name=manifest.name,
            version=manifest.version,
        )

    # 写入版本包（归档 + 旁挂清单，原子）+ 幂等 merge 索引（原子）。
    dest_dir = registry_dir.joinpath(PACKS_DIR, manifest.kind, manifest.name, manifest.version)
    dest_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(dest_dir / filename, archive_bytes)
    final_manifest = replace(manifest, artifact_sha256=artifact_sha256)
    atomic_write_bytes(
        dest_dir / PACKAGE_MANIFEST_FILE, export_manifest_text(final_manifest).encode("utf-8")
    )
    index.merge(entry)

    return PublishSummary(
        kind=manifest.kind,
        name=manifest.name,
        version=manifest.version,
        artifact_sha256=artifact_sha256,
        download=download,
        registry=registry_str,
        index_path=str(index.path),
        outcome="added",
        message=f"已发布 {manifest.kind}/{manifest.name}@{manifest.version}",
    )
