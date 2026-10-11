"""``SqlMCPServerRepository`` 等（实现 ``astra_mcp`` 的领域仓储 Protocol；W2 / T2-10）。

- :class:`SqlMCPServerRepository`（``mcp_server`` 表，``(tenant_id, name)`` 唯一）；
- :class:`SqlMCPToolRepository`（``mcp_tool`` 表，``(mcp_server_id, name)`` 唯一）；
- :class:`SqlMCPPermissionRepository`（``mcp_permission`` 表）。

🔴 落在能力包 ``repositories/``（W2 裁定 R9；能力包仅禁 Web，ORM 允许）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import apply_scope, session_scope
from astra_database.models.mcp import McpPermission as OrmMcpPermission
from astra_database.models.mcp import McpServer as OrmMcpServer
from astra_database.models.mcp import McpTool as OrmMcpTool
from astra_domain import ScopeFilter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..domain import MCPPermission, MCPServer, MCPTool
from .mappers import (
    mcp_permission_to_domain,
    mcp_permission_to_orm,
    mcp_server_to_domain,
    mcp_server_to_orm,
    mcp_tool_to_domain,
    mcp_tool_to_orm,
)

__all__ = [
    "SqlMCPServerRepository",
    "SqlMCPToolRepository",
    "SqlMCPPermissionRepository",
]


class SqlMCPServerRepository:
    """基于 SQLAlchemy 的 MCPServer 仓储（``mcp_server`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> MCPServer | None:
        """按主键获取 Server，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpServer, entity_id)
            return mcp_server_to_domain(row) if row is not None else None

    def get_by_name(self, tenant_id: str, name: str) -> MCPServer | None:
        """按 ``(tenant_id, name)`` 获取 Server，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMcpServer).where(
                OrmMcpServer.tenant_id == tenant_id, OrmMcpServer.name == name
            )
            row = session.execute(statement).scalars().first()
            return mcp_server_to_domain(row) if row is not None else None

    def add(self, entity: MCPServer) -> MCPServer:
        """新增 Server 并返回。"""
        with session_scope(self._session_factory) as session:
            row = mcp_server_to_orm(entity)
            session.add(row)
            session.flush()
            return mcp_server_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[MCPServer]:
        """按等值条件列出 Server（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMcpServer)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMcpServer, field) == value)
            statement = apply_scope(statement, OrmMcpServer, scope)
            rows = session.execute(statement).scalars().all()
            return [mcp_server_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[MCPServer]:
        """列出某租户下的全部 Server。"""
        return self.list(tenant_id=tenant_id)

    def update(self, entity: MCPServer) -> MCPServer:
        """更新 Server 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpServer, entity.id)
            if row is None:
                return mcp_server_to_domain(mcp_server_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.name = entity.name
            row.transport = entity.transport
            row.endpoint = entity.endpoint
            row.command = entity.command
            row.args = list(entity.args or []) or None
            row.env_ref = dict(entity.env_ref or {}) or None
            row.credential_id = entity.credential_id
            row.status = entity.status
            row.capabilities = dict(entity.capabilities or {}) or None
            session.flush()
            return mcp_server_to_domain(row)

    def delete(self, entity: MCPServer) -> None:
        """删除 Server。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpServer, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlMCPToolRepository:
    """基于 SQLAlchemy 的 MCPTool 仓储（``mcp_tool`` 表；发现目录）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> MCPTool | None:
        """按主键获取 Tool，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpTool, entity_id)
            return mcp_tool_to_domain(row) if row is not None else None

    def get_by_name(self, mcp_server_id: str, name: str) -> MCPTool | None:
        """按 ``(mcp_server_id, name)`` 获取 Tool，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMcpTool).where(
                OrmMcpTool.mcp_server_id == mcp_server_id, OrmMcpTool.name == name
            )
            row = session.execute(statement).scalars().first()
            return mcp_tool_to_domain(row) if row is not None else None

    def add(self, entity: MCPTool) -> MCPTool:
        """新增 Tool 并返回。"""
        with session_scope(self._session_factory) as session:
            row = mcp_tool_to_orm(entity)
            session.add(row)
            session.flush()
            return mcp_tool_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[MCPTool]:
        """按等值条件列出 Tool（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMcpTool)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMcpTool, field) == value)
            statement = apply_scope(statement, OrmMcpTool, scope)
            rows = session.execute(statement).scalars().all()
            return [mcp_tool_to_domain(row) for row in rows]

    def list_by_server(self, mcp_server_id: str) -> builtins.list[MCPTool]:
        """列出某 Server 的全部已发现 Tool（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmMcpTool)
                .where(OrmMcpTool.mcp_server_id == mcp_server_id)
                .order_by(OrmMcpTool.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [mcp_tool_to_domain(row) for row in rows]

    def update(self, entity: MCPTool) -> MCPTool:
        """更新 Tool 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpTool, entity.id)
            if row is None:
                return mcp_tool_to_domain(mcp_tool_to_orm(entity))
            row.mcp_server_id = entity.mcp_server_id
            row.name = entity.name
            row.description = entity.description
            row.input_schema = dict(entity.input_schema or {}) or None
            row.output_schema = dict(entity.output_schema or {}) or None
            row.status = entity.status
            session.flush()
            return mcp_tool_to_domain(row)

    def delete(self, entity: MCPTool) -> None:
        """删除 Tool。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpTool, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlMCPPermissionRepository:
    """基于 SQLAlchemy 的 MCPPermission 仓储（``mcp_permission`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> MCPPermission | None:
        """按主键获取策略条目，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpPermission, entity_id)
            return mcp_permission_to_domain(row) if row is not None else None

    def add(self, entity: MCPPermission) -> MCPPermission:
        """新增策略条目并返回。"""
        with session_scope(self._session_factory) as session:
            row = mcp_permission_to_orm(entity)
            session.add(row)
            session.flush()
            return mcp_permission_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[MCPPermission]:
        """按等值条件列出策略条目（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMcpPermission)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMcpPermission, field) == value)
            statement = apply_scope(statement, OrmMcpPermission, scope)
            rows = session.execute(statement).scalars().all()
            return [mcp_permission_to_domain(row) for row in rows]

    def list_by_tool(self, mcp_tool_id: str) -> builtins.list[MCPPermission]:
        """列出某 MCPTool 的全部默认策略条目（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmMcpPermission)
                .where(OrmMcpPermission.mcp_tool_id == mcp_tool_id)
                .order_by(OrmMcpPermission.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [mcp_permission_to_domain(row) for row in rows]

    def update(self, entity: MCPPermission) -> MCPPermission:
        """更新策略条目并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpPermission, entity.id)
            if row is None:
                return mcp_permission_to_domain(mcp_permission_to_orm(entity))
            row.agent_id = entity.agent_id
            row.agent_version_id = entity.agent_version_id
            row.mcp_tool_id = entity.mcp_tool_id
            row.action = entity.action
            row.effect = entity.effect
            row.scope = dict(entity.scope or {}) or None
            session.flush()
            return mcp_permission_to_domain(row)

    def delete(self, entity: MCPPermission) -> None:
        """删除策略条目。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMcpPermission, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
