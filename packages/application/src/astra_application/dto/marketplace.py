"""Marketplace DTO（W8 / T2-44；设计 §2.12 / §2.13.1）。

纯 dataclass（无框架依赖）；仅承载用例出入参：

- :class:`PackageMetadataDTO`：安装前元数据（预检展示）；
- :class:`ImportResultDTO`：导入结果；
- :class:`ExportResultDTO`：导出结果（规范化 yaml 全文 + 摘要）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import DTO

__all__ = ["PackageMetadataDTO", "ImportResultDTO", "ExportResultDTO"]

#: 预检状态（未落库）。
IMPORT_STATUS_PREVIEW = "PREVIEW"

#: 已导入状态。
IMPORT_STATUS_IMPORTED = "IMPORTED"


@dataclass
class PackageMetadataDTO(DTO):
    """安装前元数据（作者 / 版本 / 兼容 / 权限 / 依赖 / 摘要；R5 / R14）。"""

    status: str = IMPORT_STATUS_PREVIEW
    kind: str = ""
    name: str = ""
    version: str = ""
    core_compat: str = ""
    author: str = ""
    license: str = ""
    dependencies: list[str] = field(default_factory=list)
    manifest_path: str = ""
    artifact_sha256: str = ""
    signature_present: bool = False


@dataclass
class ImportResultDTO(DTO):
    """导入执行结果（落库后）。"""

    status: str = IMPORT_STATUS_IMPORTED
    kind: str = ""
    name: str = ""
    version: str = ""
    digest: str = ""


@dataclass
class ExportResultDTO(DTO):
    """导出结果（规范化 yaml 全文 + 资源标识 + 内容摘要）。"""

    yaml: str = ""
    kind: str = ""
    id: str = ""
    digest: str = ""
