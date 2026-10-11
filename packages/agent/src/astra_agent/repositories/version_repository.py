"""``SqlAgentVersionRepository``（实现领域 ``AgentVersionRepository``）。

🔴 落在 Agent 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。

**不可变（设计 §2.4）**：已发布版本不提供字段级修改——``update`` 仅在行不存在时补写，
否则视为**恒等**返回（一次发布 = 一个新版本）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.agent import AgentVersion as OrmAgentVersion
from astra_domain import AgentVersion
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import version_to_domain, version_to_orm

__all__ = ["SqlAgentVersionRepository"]


class SqlAgentVersionRepository:
    """基于 SQLAlchemy 的 AgentVersion 仓储（``agent_version`` 表，不可变快照）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentVersion | None:
        """按主键获取版本，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentVersion, entity_id)
            return version_to_domain(row) if row is not None else None

    def add(self, entity: AgentVersion) -> AgentVersion:
        """新增版本并返回（不可变快照：一次发布一个新行）。"""
        with session_scope(self._session_factory) as session:
            row = version_to_orm(entity)
            session.add(row)
            session.flush()
            return version_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[AgentVersion]:
        """按等值条件列出版本。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentVersion)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentVersion, field) == value)
            rows = session.execute(statement).scalars().all()
            return [version_to_domain(row) for row in rows]

    def update(self, entity: AgentVersion) -> AgentVersion:
        """更新版本（不可变语义：行存在时**不改字段**，恒等返回）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentVersion, entity.id)
            if row is None:
                row = version_to_orm(entity)
                session.add(row)
                session.flush()
            return version_to_domain(row)

    def delete(self, entity: AgentVersion) -> None:
        """删除版本。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentVersion, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_agent(self, agent_id: str) -> builtins.list[AgentVersion]:
        """列出某 Agent 的全部版本（按创建时间升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentVersion)
                .where(OrmAgentVersion.agent_id == agent_id)
                .order_by(OrmAgentVersion.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [version_to_domain(row) for row in rows]
