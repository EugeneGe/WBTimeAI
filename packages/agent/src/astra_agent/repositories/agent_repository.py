"""``SqlAgentRepository``（实现领域 ``AgentRepository``）。

🔴 落在 Agent 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import apply_scope, session_scope
from astra_database.models.agent import Agent as OrmAgent
from astra_domain import Agent, ScopeFilter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import agent_to_domain, agent_to_orm

__all__ = ["SqlAgentRepository"]


class SqlAgentRepository:
    """基于 SQLAlchemy 的 Agent 仓储（``agent`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Agent | None:
        """按主键获取 Agent，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgent, entity_id)
            return agent_to_domain(row) if row is not None else None

    def add(self, entity: Agent) -> Agent:
        """新增 Agent 并返回。"""
        with session_scope(self._session_factory) as session:
            row = agent_to_orm(entity)
            session.add(row)
            session.flush()
            return agent_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Agent]:
        """按等值条件列出 Agent（``scope`` 叠加租户 / 组织 / 工作区过滤，缺省不过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgent)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgent, field) == value)
            statement = apply_scope(statement, OrmAgent, scope)
            rows = session.execute(statement).scalars().all()
            return [agent_to_domain(row) for row in rows]

    def update(self, entity: Agent) -> Agent:
        """更新 Agent 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgent, entity.id)
            if row is None:
                return agent_to_domain(agent_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.name = entity.name
            row.description = entity.description
            row.type = entity.type
            row.status = entity.status
            row.current_version_id = entity.current_version_id
            row.created_by = entity.created_by
            session.flush()
            return agent_to_domain(row)

    def delete(self, entity: Agent) -> None:
        """删除 Agent。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgent, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_tenant(self, tenant_id: str) -> builtins.list[Agent]:
        """列出某租户下的全部 Agent。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgent)
                .where(OrmAgent.tenant_id == tenant_id)
                .order_by(OrmAgent.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [agent_to_domain(row) for row in rows]
