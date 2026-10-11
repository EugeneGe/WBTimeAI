"""``/tools`` 路由（W6 / T1-29；设计 §2.5 / §2.13）。

端点：

- ``GET /tools``：内置工具浏览器（注册表内工具）；
- ``GET /tools/permissions?agent_id=``：某 Agent 的 Tool 授权列表；
- ``POST /tools/permissions``：授予 / 更新一条 Tool 权限（agent × tool × effect × scope）；
- ``DELETE /tools/permissions/{permission_id}``：撤销一条权限。

Router **只**依赖 ``AppServices``（N-8）；**不** import ``astra_model`` /
``astra_database`` / ``sqlalchemy``（A33 收紧）。
"""

from __future__ import annotations

from typing import Annotated

from astra_application.dto import UserDTO
from fastapi import APIRouter, Depends, Query, Response

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import ToolPermissionRequest, ToolPermissionResponse, ToolResponse

router = APIRouter(prefix="/tools", tags=["tools"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_tool_response(tool: object) -> ToolResponse:
    """Tool（注册表项）→ 响应。"""
    spec = getattr(tool, "spec", None)
    meta = getattr(spec, "metadata", None)
    return ToolResponse(
        id=getattr(tool, "tool_id", None),
        name=str(getattr(meta, "name", "") or getattr(spec, "name", "")),
        display_name=str(getattr(meta, "display_name", "")),
        description=str(getattr(meta, "description", "")),
        category=str(getattr(meta, "category", "")),
        type=str(getattr(spec, "tool_type", "builtin")),
        requires_sandbox=bool(getattr(spec, "requires_sandbox", False)),
        input_schema=dict(getattr(spec, "input_schema", {}) or {}),
    )


def _to_permission_response(permission: object) -> ToolPermissionResponse:
    """ToolPermission 实体 → 响应。"""
    return ToolPermissionResponse(
        id=str(getattr(permission, "id")),  # noqa: B009 - 泛化只读映射（对象可能为任意实体）
        tenant_id=getattr(permission, "tenant_id", None),
        agent_id=getattr(permission, "agent_id", None),
        agent_version_id=getattr(permission, "agent_version_id", None),
        tool_id=str(getattr(permission, "tool_id", "")),
        action=str(getattr(permission, "action", "EXECUTE")),
        effect=str(getattr(permission, "effect", "ALLOW")),
        scope=dict(getattr(permission, "scope", {}) or {}),
        created_at=getattr(permission, "created_at", None),
    )


@router.get("", response_model=list[ToolResponse], summary="内置工具浏览器")
def list_tools(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ToolResponse]:
    """列出注册表中的全部工具（首批 5 个内置 Tool + 扩展）。"""
    return [_to_tool_response(tool) for tool in services.tool.list()]


@router.get(
    "/permissions",
    response_model=list[ToolPermissionResponse],
    summary="Tool 权限列表",
)
def list_permissions(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    agent_id: Annotated[str, Query(min_length=1)],
) -> list[ToolPermissionResponse]:
    """列出某 Agent 的全部 Tool 权限（agent × tool × effect × scope）。"""
    return [
        _to_permission_response(permission)
        for permission in services.tool_permissions.list_permissions(
            agent_id, tenant_id=_tenant_id(user)
        )
    ]


@router.post(
    "/permissions",
    response_model=ToolPermissionResponse,
    status_code=201,
    summary="授予 Tool 权限",
)
def grant_permission(
    payload: ToolPermissionRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ToolPermissionResponse:
    """授予 / 更新一条 Tool 权限（``effect ∈ {ALLOW, DENY}``）。"""
    permission = services.tool_permissions.grant(
        tenant_id=_tenant_id(user),
        tool_id=payload.tool_id,
        action=payload.action,
        effect=payload.effect,
        scope=payload.scope,
        agent_id=payload.agent_id,
        agent_version_id=payload.agent_version_id,
    )
    return _to_permission_response(permission)


@router.delete(
    "/permissions/{permission_id}",
    status_code=204,
    summary="撤销 Tool 权限",
)
def revoke_permission(
    permission_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """撤销一条 Tool 权限（先校验租户归属）。"""
    services.tool_permissions.revoke(permission_id, tenant_id=_tenant_id(user))
    return Response(status_code=204)
