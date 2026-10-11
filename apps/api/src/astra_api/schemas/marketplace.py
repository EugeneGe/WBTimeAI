"""Marketplace schema（导入 / 导出视图；W8 / T2-44；设计 §2.12 / §2.13.1）。

面向 ``/agent-studio/marketplace`` 的请求 / 响应模型。**统一响应壳**
``{code, data, message, request_id}`` 由既有中间件注入——此处仅定义 ``data`` 内的模型。

- :class:`ImportPackageRequest`：导入请求（``package_yaml`` / ``expected_sha256`` / ``confirm``）；
- :class:`PackageMetadataResponse`：预检（安装前展示）元数据（``status=PREVIEW``）；
- :class:`ImportResultResponse`：导入执行结果（``status=IMPORTED``）；
- :class:`ExportResultResponse`：导出结果（规范化 yaml 全文 + 摘要）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "ImportPackageRequest",
    "PackageMetadataResponse",
    "ImportResultResponse",
    "ExportResultResponse",
]


class ImportPackageRequest(BaseModel):
    """导入市场包请求。"""

    package_yaml: str = Field(..., min_length=1, description="包文档 yaml（清单 + resource）")
    expected_sha256: str | None = Field(default=None, description="期望内容摘要（不匹配拒绝）")
    confirm: bool = Field(default=False, description="False=预检（安装前展示）；True=执行导入")


class PackageMetadataResponse(BaseModel):
    """安装前元数据（预检）。"""

    status: str = "PREVIEW"
    kind: str = ""
    name: str = ""
    version: str = ""
    core_compat: str = ""
    author: str = ""
    license: str = ""
    dependencies: list[str] = Field(default_factory=list)
    manifest_path: str = ""
    artifact_sha256: str = ""
    signature_present: bool = False


class ImportResultResponse(BaseModel):
    """导入执行结果。"""

    status: str = "IMPORTED"
    kind: str = ""
    name: str = ""
    version: str = ""
    digest: str = ""


class ExportResultResponse(BaseModel):
    """导出结果（规范化 yaml 全文）。"""

    yaml: str = ""
    kind: str = ""
    id: str = ""
    digest: str = ""
