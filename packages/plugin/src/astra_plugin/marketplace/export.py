"""市场包导出：确定性序列化（W8 裁定 R7 / §3.2）。

:func:`export_package` 为**导出的唯一出口**：先按资源 schema 规范化，再经
:func:`~astra_plugin.marketplace.serialize.canonical_dump` 序列化，保证
``export → import → export`` 规范化后 ``diff == 空``（``I-P2-18`` / ``D13``）。

- :func:`export_package`：资源字典 → 规范化 YAML 文本；
- :func:`export_manifest_text`：清单 → 规范化 YAML 文本；
- :func:`build_manifest`：由参数构造 :class:`AstraPackageManifest`（并校验）。

🔴 零 Web / ORM：仅依赖标准库 + ``astra_core`` + 同子包 ``package`` / ``schema`` / ``serialize``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from astra_plugin.marketplace.package import (
    DEFAULT_CORE_VERSION,
    AstraPackageManifest,
    manifest_to_dict,
)
from astra_plugin.marketplace.schema import normalize_resource
from astra_plugin.marketplace.serialize import canonical_dump

__all__ = [
    "export_package",
    "export_resource_text",
    "export_manifest_text",
    "build_manifest",
]


def export_package(resource: Mapping[str, Any], *, kind: str) -> str:
    """把资源字典导出为**规范化 YAML 文本**（R7 导出唯一出口）。

    Args:
        resource: 资源字典（如 ``agent`` / ``skill`` / ``workflow`` 清单）。
        kind: 资源种类。

    Returns:
        规范化 YAML 文本（键序升序 / 2 空格缩进 / LF / 恰好一个尾换行 / 中文不转义）。

    Raises:
        DomainError: 资源字段非法（``VALIDATION_ERROR``）。
    """
    return canonical_dump(normalize_resource(kind, resource))


def export_resource_text(resource: Mapping[str, Any], *, kind: str) -> str:
    """:func:`export_package` 的别名（语义更明确）。"""
    return export_package(resource, kind=kind)


def export_manifest_text(manifest: AstraPackageManifest) -> str:
    """把清单导出为规范化 YAML 文本（``astra-package.yaml``）。"""
    return canonical_dump(manifest_to_dict(manifest))


def build_manifest(
    *,
    kind: str,
    name: str,
    version: str,
    manifest_path: str,
    core_compat: str = "",
    author: str = "",
    license: str = "",
    dependencies: Sequence[str] = (),
    artifact_sha256: str = "",
    signature: str = "",
    description: str = "",
    core_version: str = DEFAULT_CORE_VERSION,
) -> AstraPackageManifest:
    """构造并校验 :class:`AstraPackageManifest`。

    Args:
        kind / name / version / manifest_path: 必填字段。
        core_compat: 兼容区间。
        author / license / description: 元信息。
        dependencies: 依赖清单。
        artifact_sha256: 归档摘要（空 = 未归档）。
        signature: 签名（可选）。
        core_version: 当前 core 版本（构造期做兼容区间提示；不兼容仍会构造，
            兼容拒绝由 :func:`~astra_plugin.marketplace.import_.validate` 负责）。

    Returns:
        校验通过的 :class:`AstraPackageManifest`。

    Raises:
        DomainError: 字段非法（``VALIDATION_ERROR``）。
    """
    manifest = AstraPackageManifest(
        kind=kind,
        name=name,
        version=version,
        core_compat=core_compat,
        manifest_path=manifest_path,
        author=author,
        license=license,
        dependencies=tuple(str(item) for item in dependencies),
        artifact_sha256=artifact_sha256,
        signature=signature,
        description=description,
    )
    manifest.validate()
    return manifest
