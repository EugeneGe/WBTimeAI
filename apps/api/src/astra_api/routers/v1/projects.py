"""``/projects`` + ``/workspaces/{id}/files|environment`` 路由（W10 / T2-49；设计 §2.8 / §2.12）。

端点（**无前缀 router + 显式全路径**，裁定 R-W10-01）：

- ``GET  /projects``：列表（``workspace_id`` 必填，``tenant_id`` 取 ``CurrentUser``，分页）；
- ``POST /projects``：创建（``name`` + ``workspace_id``）；
- ``GET  /projects/{project_id}``：详情（跨租户 / 不存在 → 404）；
- ``GET  /workspaces/{workspace_id}/files``：文件清单（列表，分页；经 ``Storage``）；
- ``GET  /workspaces/{workspace_id}/files/content``：文件内容（query ``path``；经 ``Storage``）；
- ``GET  /workspaces/{workspace_id}/environment``：环境清单（敏感项 masked）；
- ``GET  /workspaces/{workspace_id}/environment/{environment_id}``：环境详情（敏感项 masked）。

Router **只**依赖 ``AppServices`` / ``CurrentUser``（N-8）：**不** import ``astra_workspace`` /
``astra_database`` / ``sqlalchemy`` / ``astra_storage``（守
``test_api_routers_have_no_orm_dependency``）；编排全部经 ``services.workspace.projects`` /
``.files`` / ``.environment``。

🔴 **无前缀 router**：``projects.py`` 同时承载 ``/projects`` 与 ``/workspaces/{id}/...``，故以**显式
   全路径**注册，避免与既有 ``workspaces.py``（``prefix="/workspaces"``，冻结）前缀叠加
   （裁定 R-W10-01）。

🔴 **降级口径（冻结 R-W10-02）**：``services.workspace.files`` 在缺 ``Storage`` 注入时为 ``None``
   → 文件端点返回结构化 ``503``（``DomainError``，**不 500、不静默空**）。文件读取**必须经
   ``Storage``**，**禁**直读文件系统。

🔴 **环境明文禁止回显（冻结 R-W10-02）**：``env_vars`` 敏感项（``{"$ref": ...}``）仅返回引用 +
   ``masked=true``，明文恒不外泄。
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Annotated, Any

from astra_application.dto import UserDTO
from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.project import (
    CreateProjectRequest,
    EnvironmentResponse,
    EnvironmentVarResponse,
    FileContentResponse,
    FileObjectResponse,
    ProjectResponse,
)

router = APIRouter(tags=["projects"])

#: 环境变量引用对象保留键（与 ``astra_workspace.environment.REF_KEY`` 同口径）。
_ENV_REF_KEY = "$ref"


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_project_response(project: Any) -> ProjectResponse:
    """项目实体 → 响应。"""
    return ProjectResponse(
        id=str(project.id),
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        workspace_id=project.workspace_id,
        name=project.name,
        description=project.description,
        repo_url=project.repo_url,
        default_branch=project.default_branch,
        settings=dict(project.settings or {}),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _masked_env_vars(env_vars: Mapping[str, Any] | None) -> list[EnvironmentVarResponse]:
    """把 ``env_vars`` 映射为**脱敏**条目列表（敏感引用 masked，明文不回显）。"""
    entries: list[EnvironmentVarResponse] = []
    for name, value in (env_vars or {}).items():
        if isinstance(value, Mapping):
            ref = value.get(_ENV_REF_KEY)
            entries.append(
                EnvironmentVarResponse(
                    name=str(name),
                    value=None,
                    ref=str(ref) if ref is not None else None,
                    masked=True,
                )
            )
        else:
            entries.append(
                EnvironmentVarResponse(name=str(name), value=str(value), ref=None, masked=False)
            )
    return entries


def _to_environment_response(environment: Any) -> EnvironmentResponse:
    """环境实体 → 响应（``env_vars`` 经脱敏映射）。"""
    return EnvironmentResponse(
        id=str(environment.id),
        tenant_id=environment.tenant_id,
        organization_id=environment.organization_id,
        workspace_id=environment.workspace_id,
        name=environment.name,
        env_vars=_masked_env_vars(environment.env_vars),
        runtime=dict(environment.runtime or {}),
        created_at=environment.created_at,
        updated_at=environment.updated_at,
    )


def _require_files_service(services: AppServices) -> Any:
    """取工作区文件用例（缺 ``Storage`` 注入 → 结构化 ``503``，不静默空）。"""
    files = services.workspace.files
    if files is None:
        raise DomainError(
            "工作区文件能力未装配（缺 Storage 注入）",
            code=ErrorCode.DEPENDENCY_MISSING,
            status_code=503,
            data={"capability": "workspace.files"},
        )
    return files


# -- /projects --------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectResponse], summary="项目列表")
def list_projects(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace_id: Annotated[str, Query(description="归属 Workspace 标识（必填）")],
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[ProjectResponse]:
    """列出某工作区下的项目（仅同租户；分页）。"""
    projects = services.workspace.projects.list_by_workspace(
        workspace_id, tenant_id=_tenant_id(user)
    )
    page = projects[offset : offset + limit]
    return [_to_project_response(project) for project in page]


@router.post("/projects", response_model=ProjectResponse, status_code=201, summary="创建项目")
def create_project(
    payload: CreateProjectRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ProjectResponse:
    """创建一个项目（归属指定工作区）。"""
    project = services.workspace.projects.create(
        tenant_id=_tenant_id(user),
        workspace_id=payload.workspace_id,
        name=payload.name,
        description=payload.description,
        repo_url=payload.repo_url,
        default_branch=payload.default_branch,
        settings=payload.settings,
        created_by=user.id,
        organization_id=payload.organization_id,
    )
    return _to_project_response(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse, summary="项目详情")
def get_project(
    project_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ProjectResponse:
    """按 id 获取项目（跨租户 / 不存在 → 404）。"""
    project = services.workspace.projects.get(project_id, tenant_id=_tenant_id(user))
    return _to_project_response(project)


# -- /workspaces/{id}/files -------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/files",
    response_model=list[FileObjectResponse],
    summary="工作区文件清单",
)
def list_workspace_files(
    workspace_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    prefix: Annotated[str | None, Query(description="工作区内前缀过滤（可空）")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[FileObjectResponse]:
    """列出工作区下的文件（**经 ``Storage``**；分页。缺装配 → 503）。"""
    files = _require_files_service(services)
    objects = files.list(workspace_id=workspace_id, prefix=prefix)
    page = objects[offset : offset + limit]
    return [
        FileObjectResponse(
            key=obj.key,
            size=obj.size,
            content_type=obj.content_type,
            etag=obj.etag,
            created_at=obj.created_at,
        )
        for obj in page
    ]


@router.get(
    "/workspaces/{workspace_id}/files/content",
    response_model=FileContentResponse,
    summary="工作区文件内容",
)
def read_workspace_file(
    workspace_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    path: Annotated[str, Query(description="工作区内相对路径（必填）")],
) -> FileContentResponse:
    """读取工作区文件内容（**经 ``Storage``**；内容 base64 承载，二进制安全。缺装配 → 503）。"""
    files = _require_files_service(services)
    data = files.get(workspace_id=workspace_id, path=path)
    return FileContentResponse(
        path=path,
        size=len(data),
        encoding="base64",
        content_base64=base64.b64encode(data).decode("ascii"),
    )


# -- /workspaces/{id}/environment -------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/environment",
    response_model=list[EnvironmentResponse],
    summary="工作区环境清单",
)
def list_workspace_environments(
    workspace_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[EnvironmentResponse]:
    """列出工作区下的全部环境（仅同租户；敏感项 masked）。"""
    environments = services.workspace.environment.list_for_workspace(
        workspace_id, tenant_id=_tenant_id(user)
    )
    return [_to_environment_response(environment) for environment in environments]


@router.get(
    "/workspaces/{workspace_id}/environment/{environment_id}",
    response_model=EnvironmentResponse,
    summary="工作区环境详情",
)
def get_workspace_environment(
    workspace_id: str,
    environment_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> EnvironmentResponse:
    """按 id 获取环境详情（跨租户 / 跨工作区 / 不存在 → 404；敏感项 masked，**明文不回显**）。

    🔴 **路径一致性（R-W10-09 口径）**：``environment`` 归属的 ``workspace_id`` **必须**与路径
    ``workspace_id`` 一致；不一致 → 404（**不泄漏**资源存在于其它工作区）。服务层 ``get`` 仅校验
    租户归属（同租户跨工作区仍命中），故此处补路径一致性校验。
    """
    environment = services.workspace.environment.get(environment_id, tenant_id=_tenant_id(user))
    if environment.workspace_id != workspace_id:
        raise DomainError(
            "运行环境不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
            data={"environment_id": environment_id},
        )
    return _to_environment_response(environment)
