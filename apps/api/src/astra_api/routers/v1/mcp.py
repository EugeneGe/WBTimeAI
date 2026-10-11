"""``/mcp`` 路由（W3 / T2-17；设计 §2.4 / §2.12）。

端点：

- ``POST /mcp/servers`` · ``GET /mcp/servers`` · ``GET /mcp/servers/{id}`` ·
  ``DELETE /mcp/servers/{id}``（Server 注册生命周期）；
- ``POST /mcp/servers/{id}/discover``（发现工具 → **落 ``mcp_tool``**）；
- ``GET /mcp/tools``（工具目录）；
- ``GET /mcp/permissions`` · ``POST /mcp/permissions``（授权）。

Router **只**依赖 ``AppServices``（N-8）；面向领域 Protocol / 领域服务取用；**不** import
ORM / MCPClient 直调。跨租户 / 不存在 → **404**（I-1）；凭据**仅引用 / 掩码**（C-07）。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Query, Response

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.mcp import (
    CreateMCPPermissionRequest,
    MCPPermissionResponse,
    MCPServerResponse,
    MCPToolResponse,
    RegisterMCPServerRequest,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _tenant_id(user: Any) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_server_response(server: object) -> MCPServerResponse:
    """MCPServer 实体 → 响应（**无明文**）。"""
    return MCPServerResponse(
        id=str(getattr(server, "id")),  # noqa: B009 - 泛化只读映射
        tenant_id=getattr(server, "tenant_id", None),
        name=str(getattr(server, "name", "")),
        transport=str(getattr(server, "transport", "stdio")),
        endpoint=getattr(server, "endpoint", None),
        command=getattr(server, "command", None),
        args=list(getattr(server, "args", []) or []),
        env_ref=dict(getattr(server, "env_ref", {}) or {}),
        credential_id=getattr(server, "credential_id", None),
        status=str(getattr(server, "status", "ACTIVE")),
        workspace_id=getattr(server, "workspace_id", None),
        created_at=getattr(server, "created_at", None),
    )


def _to_tool_response(tool: object) -> MCPToolResponse:
    """MCPTool 实体 → 响应。"""
    return MCPToolResponse(
        id=str(getattr(tool, "id")),  # noqa: B009 - 泛化只读映射
        mcp_server_id=str(getattr(tool, "mcp_server_id", "")),
        name=str(getattr(tool, "name", "")),
        description=getattr(tool, "description", None),
        input_schema=dict(getattr(tool, "input_schema", {}) or {}),
        output_schema=dict(getattr(tool, "output_schema", {}) or {}),
        status=str(getattr(tool, "status", "ACTIVE")),
        discovered_at=getattr(tool, "discovered_at", None),
    )


def _to_permission_response(permission: object) -> MCPPermissionResponse:
    """MCPPermission 实体 → 响应。"""
    return MCPPermissionResponse(
        id=str(getattr(permission, "id")),  # noqa: B009 - 泛化只读映射
        tenant_id=getattr(permission, "tenant_id", None),
        agent_id=getattr(permission, "agent_id", None),
        agent_version_id=getattr(permission, "agent_version_id", None),
        mcp_tool_id=str(getattr(permission, "mcp_tool_id", "")),
        action=str(getattr(permission, "action", "EXECUTE")),
        effect=str(getattr(permission, "effect", "DENY")),
        scope=dict(getattr(permission, "scope", {}) or {}),
        created_at=getattr(permission, "created_at", None),
    )


def _require_owned_server(services: AppServices, *, server_id: str, tenant_id: str) -> Any:
    """取当前租户下的 MCP Server，不存在 / 跨租户 → 404。"""
    server = services.mcp.get(server_id)
    if server is None or getattr(server, "tenant_id", None) != tenant_id:
        raise DomainError(
            "MCP Server 不存在", code=ErrorCode.NOT_FOUND, data={"server_id": server_id}
        )
    return server


# -- Server 注册生命周期 ----------------------------------------------------


@router.post(
    "/servers", response_model=MCPServerResponse, status_code=201, summary="注册 MCP Server"
)
def register_server(
    payload: RegisterMCPServerRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MCPServerResponse:
    """注册一个 MCP Server（凭据**仅引用**）。"""
    from astra_mcp import MCPServer

    tenant_id = _tenant_id(user)
    existing = services.mcp.get_by_name(tenant_id, payload.name)
    if existing is not None:
        raise DomainError(
            "MCP Server 名已存在",
            code=ErrorCode.CONFLICT,
            data={"name": payload.name},
        )
    server = services.mcp.add(
        MCPServer(
            tenant_id=tenant_id,
            name=payload.name,
            transport=payload.transport,
            endpoint=payload.endpoint,
            command=payload.command,
            args=list(payload.args),
            env_ref=dict(payload.env_ref),
            credential_id=payload.credential_id,
            workspace_id=payload.workspace_id,
        )
    )
    return _to_server_response(server)


@router.get("/servers", response_model=list[MCPServerResponse], summary="MCP Server 列表")
def list_servers(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[MCPServerResponse]:
    """列出当前租户的全部 MCP Server。"""
    return [_to_server_response(server) for server in services.mcp.list_by_tenant(_tenant_id(user))]


@router.get("/servers/{server_id}", response_model=MCPServerResponse, summary="MCP Server 详情")
def get_server(
    server_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MCPServerResponse:
    """按 id 获取 MCP Server（跨租户 / 不存在 → 404）。"""
    return _to_server_response(
        _require_owned_server(services, server_id=server_id, tenant_id=_tenant_id(user))
    )


@router.delete("/servers/{server_id}", status_code=204, summary="删除 MCP Server")
def delete_server(
    server_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """删除 MCP Server（连带注销内存注册表条目）。"""
    server = _require_owned_server(services, server_id=server_id, tenant_id=_tenant_id(user))
    services.mcp.delete(server)
    services.mcp_registry.unregister_server(str(getattr(server, "name", "")))
    return Response(status_code=204)


# -- 发现（落 ``mcp_tool``） ------------------------------------------------


@router.post(
    "/servers/{server_id}/discover",
    response_model=list[MCPToolResponse],
    summary="发现 MCP 工具",
)
def discover_tools(
    server_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[MCPToolResponse]:
    """发现 Server 的工具并**落 ``mcp_tool`` 发现目录**（复用 W2 ``MCPDiscovery``）。"""
    server = _require_owned_server(services, server_id=server_id, tenant_id=_tenant_id(user))
    client = services.mcp_client_factory(server)
    tools = services.mcp_discovery.discover(server, client)
    return [_to_tool_response(tool) for tool in tools]


# -- 工具目录 ---------------------------------------------------------------


@router.get("/tools", response_model=list[MCPToolResponse], summary="MCP 工具目录")
def list_tools(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    server_id: Annotated[str | None, Query(description="限定某 Server；缺省聚合本租户全部")] = None,
) -> list[MCPToolResponse]:
    """列出 MCP 工具目录（可按 ``server_id`` 过滤；缺省聚合本租户全部 Server）。"""
    tenant_id = _tenant_id(user)
    if server_id is not None:
        _require_owned_server(services, server_id=server_id, tenant_id=tenant_id)
        tools = services.mcp_tools.list_by_server(server_id)
    else:
        tools = []
        for server in services.mcp.list_by_tenant(tenant_id):
            tools.extend(services.mcp_tools.list_by_server(str(server.id)))
    return [_to_tool_response(tool) for tool in tools]


# -- 授权 -------------------------------------------------------------------


@router.get(
    "/permissions",
    response_model=list[MCPPermissionResponse],
    summary="MCP 授权列表",
)
def list_permissions(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    mcp_tool_id: Annotated[str, Query(min_length=1, description="目标 MCPTool 标识")],
) -> list[MCPPermissionResponse]:
    """列出某 MCPTool 的全部授权条目（经 ``resource_permission``，**同一映射口径**）。"""
    return [
        _to_permission_response(permission)
        for permission in services.mcp_permission_service.list_by_tool(
            mcp_tool_id, tenant_id=_tenant_id(user)
        )
    ]


@router.post(
    "/permissions",
    response_model=MCPPermissionResponse,
    status_code=201,
    summary="新增 MCP 授权",
)
def create_permission(
    payload: CreateMCPPermissionRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MCPPermissionResponse:
    """新增一条 MCP Tool 授权（agent × mcp_tool × effect × scope）。

    经 ``resource_permission`` 落库（裁定 §21.4 X1/X2）：先做 ``mcp_tool_id → tool 行 id``
    映射再写运行期**唯一**判定源；未映射（未同步进 ``tool`` 表）→ fail-closed + 告警。
    """
    permission = services.mcp_permission_service.grant(
        tenant_id=_tenant_id(user),
        mcp_tool_id=payload.mcp_tool_id,
        agent_id=payload.agent_id,
        agent_version_id=payload.agent_version_id,
        action=payload.action,
        effect=payload.effect,
        scope=dict(payload.scope),
    )
    return _to_permission_response(permission)
