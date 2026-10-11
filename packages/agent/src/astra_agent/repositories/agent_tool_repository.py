"""``SqlAgentToolRepository``（实现领域 ``AgentToolRepository``）。

🔴 落在 Agent 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。
唯一键 ``(agent_version_id, tool_id)``。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.agent import AgentTool as OrmAgentTool
from astra_domain import AgentTool
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import agent_tool_to_domain, agent_tool_to_orm

__all__ = ["SqlAgentToolRepository"]


class SqlAgentToolRepository:
    """基于 SQLAlchemy 的 AgentTool 绑定仓储（``agent_tool`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentTool | None:
        """按主键获取绑定，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentTool, entity_id)
            return agent_tool_to_domain(row) if row is not None else None

    def add(self, entity: AgentTool) -> AgentTool:
        """新增绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = agent_tool_to_orm(entity)
            session.add(row)
            session.flush()
            return agent_tool_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[AgentTool]:
        """按等值条件列出绑定。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentTool)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentTool, field) == value)
            rows = session.execute(statement).scalars().all()
            return [agent_tool_to_domain(row) for row in rows]

    def update(self, entity: AgentTool) -> AgentTool:
        """更新绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentTool, entity.id)
            if row is None:
                return agent_tool_to_domain(agent_tool_to_orm(entity))
            row.agent_version_id = entity.agent_version_id
            row.tool_id = entity.tool_id
            row.enabled = entity.enabled
            row.permission_scope = dict(entity.permission_scope or {}) or None
            session.flush()
            return agent_tool_to_domain(row)

    def delete(self, entity: AgentTool) -> None:
        """删除绑定。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentTool, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_agent_version(self, agent_version_id: str) -> builtins.list[AgentTool]:
        """列出某 AgentVersion 绑定的全部 Tool（按创建顺序：``id`` 为时间有序 ULID）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentTool)
                .where(OrmAgentTool.agent_version_id == agent_version_id)
                .order_by(OrmAgentTool.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [agent_tool_to_domain(row) for row in rows]
