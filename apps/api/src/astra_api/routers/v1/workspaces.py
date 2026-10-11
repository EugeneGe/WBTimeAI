"""``/api/v1/workspaces`` 路由（T0-18：创建 / 列表 / 详情 / 更新设置）。

路由经 **应用层用例**（Command / Query）落业务，**不直调 DB / ORM**。
"""

from __future__ import annotations

from typing import Annotated

from astra_application import (
    CreateWorkspaceCommand,
    CreateWorkspaceHandler,
    GetWorkspaceHandler,
    GetWorkspaceQuery,
    ListWorkspacesHandler,
    ListWorkspacesQuery,
    UpdateWorkspaceSettingsCommand,
    UpdateWorkspaceSettingsHandler,
    WorkspaceDTO,
)
from astra_application.dto import UserDTO
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser, require_permission
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    CreateWorkspaceRequest,
    UpdateWorkspaceSettingsRequest,
    WorkspaceResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _to_response(workspace: WorkspaceDTO) -> WorkspaceResponse:
    """由工作区 DTO 构造响应。"""
    return WorkspaceResponse(
        id=workspace.id,
        tenant_id=workspace.tenant_id,
        owner_id=workspace.owner_id,
        name=workspace.name,
        workspace_type=workspace.workspace_type,
        settings=workspace.settings,
        config=workspace.config,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识（Phase 0 必有默认租户）。"""
    return user.tenant_id or ""


@router.post("", response_model=WorkspaceResponse, status_code=201, summary="创建工作区")
def create_workspace(
    payload: CreateWorkspaceRequest,
    user: Annotated[UserDTO, Depends(require_permission("workspace:create"))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkspaceResponse:
    """创建工作区（需 ``workspace:create`` 权限）。"""
    handler = CreateWorkspaceHandler(services.workspace.workspaces)
    dto = handler.handle(
        CreateWorkspaceCommand(
            tenant_id=_tenant_id(user),
            owner_id=user.id,
            name=payload.name,
            workspace_type=payload.workspace_type,
            settings=payload.settings,
            config=payload.config,
        )
    )
    return _to_response(dto)


@router.get("", response_model=list[WorkspaceResponse], summary="工作区列表")
def list_workspaces(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[WorkspaceResponse]:
    """列出当前租户下的全部工作区（多租户隔离）。"""
    handler = ListWorkspacesHandler(services.workspace.workspaces)
    return [_to_response(dto) for dto in handler.handle(ListWorkspacesQuery(_tenant_id(user)))]


@router.get("/{workspace_id}", response_model=WorkspaceResponse, summary="工作区详情")
def get_workspace(
    workspace_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkspaceResponse:
    """按 id 获取工作区（跨租户 → 404）。"""
    handler = GetWorkspaceHandler(services.workspace.workspaces)
    dto = handler.handle(GetWorkspaceQuery(workspace_id=workspace_id, tenant_id=_tenant_id(user)))
    return _to_response(dto)


@router.put("/{workspace_id}/settings", response_model=WorkspaceResponse, summary="更新设置")
def update_workspace_settings(
    workspace_id: str,
    payload: UpdateWorkspaceSettingsRequest,
    user: Annotated[UserDTO, Depends(require_permission("workspace:update"))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkspaceResponse:
    """更新工作区设置（需 ``workspace:update`` 权限）。"""
    handler = UpdateWorkspaceSettingsHandler(services.workspace.workspaces)
    dto = handler.handle(
        UpdateWorkspaceSettingsCommand(
            workspace_id=workspace_id,
            tenant_id=_tenant_id(user),
            settings=payload.settings,
        )
    )
    return _to_response(dto)
