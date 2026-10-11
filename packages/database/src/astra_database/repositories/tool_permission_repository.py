"""``SqlToolPermissionRepository``（实现领域 ``ToolPermissionRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；由组合根 / 集成测试构造后，以**领域 Protocol**
   注入 ``astra_tool.services.PermissionService``（``packages/tool`` 零 ORM）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_domain import ToolPermission
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.tool import ToolPermission as OrmToolPermission
from ..session import session_scope
from .tool_mappers import tool_permission_to_domain, tool_permission_to_orm

__all__ = ["SqlToolPermissionRepository"]


class SqlToolPermissionRepository:
    """基于 SQLAlchemy 的 Tool 权限仓储（``tool_permission`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> ToolPermission | None:
        """按主键获取权限（不存在返回 ``None``）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolPermission, entity_id)
            return tool_permission_to_domain(row) if row is not None else None

    def add(self, entity: ToolPermission) -> ToolPermission:
        """新增权限并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = tool_permission_to_orm(entity)
            session.add(row)
            session.flush()
            return tool_permission_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[ToolPermission]:
        """按等值条件列出权限。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmToolPermission)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmToolPermission, field) == value)
            rows = session.execute(statement).scalars().all()
            return [tool_permission_to_domain(row) for row in rows]

    def update(self, entity: ToolPermission) -> ToolPermission:
        """更新权限并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolPermission, entity.id)
            if row is None:
                return tool_permission_to_domain(tool_permission_to_orm(entity))
            row.agent_id = entity.agent_id
            row.agent_version_id = entity.agent_version_id
            row.tool_id = entity.tool_id
            row.action = entity.action
            row.effect = entity.effect
            row.scope = dict(entity.scope) if entity.scope else {}
            session.flush()
            return tool_permission_to_domain(row)

    def delete(self, entity: ToolPermission) -> None:
        """删除权限。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolPermission, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_agent(self, agent_id: str) -> builtins.list[ToolPermission]:
        """列出某 Agent 的全部 Tool 权限（唯一键 ``(agent_id, tool_id, action)``）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmToolPermission)
                .where(OrmToolPermission.agent_id == agent_id)
                .order_by(OrmToolPermission.tool_id.asc(), OrmToolPermission.action.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [tool_permission_to_domain(row) for row in rows]
