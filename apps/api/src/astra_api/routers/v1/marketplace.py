"""``/agent-studio/marketplace`` 路由（W8 / T2-44；设计 §2.12 / §2.13.1 / 裁定 R4 / R5）。

端点：

- ``POST /agent-studio/marketplace/import``：**预检**（``confirm=false`` → 安装前展示元数据，
  **不落库**）或 **执行**（``confirm=true`` → 校验 + 权限 + 落库；``expected_sha256`` 不匹配拒绝）；
- ``GET /agent-studio/marketplace/export?kind=&id=``：导出已落地资源为**规范化 yaml 全文**。

Router **只**依赖 ``AppServices``（N-8）：**不** import ``astra_database`` / ``sqlalchemy`` /
``astra_agent`` / ``astra_skill`` / ``astra_workflow`` / ``astra_plugin``（``test_api_routers_have_
no_orm_dependency``）；编排全部经 ``services.marketplace``（应用层 ``MarketplaceService``）。
**统一响应壳** ``{code,data,message,request_id}`` 由中间件注入（本 Router 只返回模型）。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from astra_application.dto import UserDTO
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import require_permission
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.marketplace import (
    ExportResultResponse,
    ImportPackageRequest,
    ImportResultResponse,
    PackageMetadataResponse,
)

router = APIRouter(prefix="/agent-studio/marketplace", tags=["marketplace"])

#: 导入 / 导出权限码（与 ``MarketplaceService`` 动作码同口径）。
_PERMISSION_IMPORT = "marketplace:import"
_PERMISSION_EXPORT = "marketplace:export"


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


@router.post(
    "/import",
    response_model=None,
    summary="导入市场包（预检 / 执行）",
)
def import_package(
    payload: ImportPackageRequest,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_IMPORT))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PackageMetadataResponse | ImportResultResponse:
    """导入市场包：``confirm=false`` → 预检元数据；``confirm=true`` → 执行并落库。

    🔴 ``response_model=None``：本端点按分支返回**两种** ``data`` 形态（预检 /
    执行），故显式关闭 FastAPI 返回类型推断，直接经 ``jsonable_encoder`` 序列化
    分支模型（避免 Union 响应模型把任一分支误套成另一分支的空字段）。
    """
    if not payload.confirm:
        metadata = services.marketplace.preview(payload.package_yaml, user_id=user.id)
        return PackageMetadataResponse(**asdict(metadata))
    result = services.marketplace.import_package(
        payload.package_yaml,
        user_id=user.id,
        tenant_id=_tenant_id(user),
        expected_sha256=payload.expected_sha256,
    )
    return ImportResultResponse(**asdict(result))


@router.get(
    "/export",
    response_model=ExportResultResponse,
    summary="导出资源为规范化 yaml",
)
def export_resource(
    kind: str,
    id: str,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_EXPORT))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ExportResultResponse:
    """导出已落地资源（``kind`` ∈ ``agent|skill|workflow``）为规范化 yaml 全文。"""
    result = services.marketplace.export_resource(
        kind=kind,
        resource_id=id,
        user_id=user.id,
        tenant_id=_tenant_id(user),
    )
    return ExportResultResponse(**asdict(result))
