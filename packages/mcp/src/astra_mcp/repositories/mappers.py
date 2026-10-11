"""ORM 行 ↔ 领域实体映射（MCPServer / MCPTool / MCPPermission；W2 / T2-10）。

将 ``astra_database.models.mcp`` 的 SQLAlchemy 行与领域实体互转。

🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from astra_database.models.mcp import McpPermission as OrmMcpPermission
from astra_database.models.mcp import McpServer as OrmMcpServer
from astra_database.models.mcp import McpTool as OrmMcpTool

from ..domain import MCPPermission, MCPServer, MCPTool

__all__ = [
    "mcp_server_to_domain",
    "mcp_server_to_orm",
    "mcp_tool_to_domain",
    "mcp_tool_to_orm",
    "mcp_permission_to_domain",
    "mcp_permission_to_orm",
]


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


# -- MCPServer --------------------------------------------------------------


def mcp_server_to_domain(row: OrmMcpServer) -> MCPServer:
    """ORM McpServer 行 → 领域 ``MCPServer``。"""
    return MCPServer(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        name=row.name,
        transport=row.transport,
        endpoint=row.endpoint,
        command=row.command,
        args=list(row.args or []),
        env_ref=dict(row.env_ref or {}),
        credential_id=row.credential_id,
        status=row.status,
        capabilities=dict(row.capabilities or {}),
        workspace_id=row.workspace_id,
    )


def mcp_server_to_orm(entity: MCPServer) -> OrmMcpServer:
    """领域 ``MCPServer`` → ORM 行。"""
    return OrmMcpServer(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        name=entity.name,
        transport=entity.transport,
        endpoint=entity.endpoint,
        command=entity.command,
        args=list(entity.args or []) or None,
        env_ref=dict(entity.env_ref or {}) or None,
        credential_id=entity.credential_id,
        status=entity.status,
        capabilities=dict(entity.capabilities or {}) or None,
    )


# -- MCPTool ----------------------------------------------------------------


def mcp_tool_to_domain(row: OrmMcpTool) -> MCPTool:
    """ORM McpTool 行 → 领域 ``MCPTool``。"""
    return MCPTool(
        id=row.id,
        mcp_server_id=row.mcp_server_id,
        name=row.name,
        description=row.description,
        input_schema=dict(row.input_schema or {}),
        output_schema=dict(row.output_schema or {}),
        status=row.status,
        discovered_at=_dt(getattr(row, "discovered_at", None)),
    )


def mcp_tool_to_orm(entity: MCPTool) -> OrmMcpTool:
    """领域 ``MCPTool`` → ORM 行。"""
    return OrmMcpTool(
        id=entity.id,
        mcp_server_id=entity.mcp_server_id,
        name=entity.name,
        description=entity.description,
        input_schema=dict(entity.input_schema or {}) or None,
        output_schema=dict(entity.output_schema or {}) or None,
        discovered_at=_dt(entity.discovered_at),
        status=entity.status,
    )


# -- MCPPermission ----------------------------------------------------------


def mcp_permission_to_domain(row: OrmMcpPermission) -> MCPPermission:
    """ORM McpPermission 行 → 领域 ``MCPPermission``。"""
    return MCPPermission(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        mcp_tool_id=row.mcp_tool_id,
        action=row.action,
        effect=row.effect,
        scope=dict(row.scope or {}),
    )


def mcp_permission_to_orm(entity: MCPPermission) -> OrmMcpPermission:
    """领域 ``MCPPermission`` → ORM 行。"""
    return OrmMcpPermission(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_id=entity.agent_id,
        agent_version_id=entity.agent_version_id,
        mcp_tool_id=entity.mcp_tool_id,
        action=entity.action,
        effect=entity.effect,
        scope=dict(entity.scope or {}) or None,
    )
