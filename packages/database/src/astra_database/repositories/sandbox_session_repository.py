"""``SqlSandboxSessionRepository``（实现领域 ``SandboxSessionRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；由组合根 / 集成测试构造后，以**领域 Protocol**
   依赖（``packages/sandbox`` 零 ORM，W4 架构裁定 Q1 = 方案 B）。

供审计与「重建一次执行」：记录 provider / image / status / container_ref / workdir。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_domain import SandboxSession
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.sandbox import SandboxSession as OrmSandboxSession
from ..session import session_scope
from .sandbox_mappers import sandbox_session_to_domain, sandbox_session_to_orm

__all__ = ["SqlSandboxSessionRepository"]


class SqlSandboxSessionRepository:
    """基于 SQLAlchemy 的沙箱会话仓储（``sandbox_session`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> SandboxSession | None:
        """按主键获取会话（不存在返回 ``None``）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSandboxSession, entity_id)
            return sandbox_session_to_domain(row) if row is not None else None

    def add(self, entity: SandboxSession) -> SandboxSession:
        """新增会话并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = sandbox_session_to_orm(entity)
            session.add(row)
            session.flush()
            return sandbox_session_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[SandboxSession]:
        """按等值条件列出会话。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSandboxSession)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmSandboxSession, field) == value)
            rows = session.execute(statement).scalars().all()
            return [sandbox_session_to_domain(row) for row in rows]

    def update(self, entity: SandboxSession) -> SandboxSession:
        """更新会话并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSandboxSession, entity.id)
            if row is None:
                return sandbox_session_to_domain(sandbox_session_to_orm(entity))
            row.run_id = entity.run_id
            row.workspace_id = entity.workspace_id
            row.provider = entity.provider
            row.image = entity.image
            row.status = entity.status
            row.container_ref = entity.container_ref
            row.workdir = entity.workdir
            row.ended_at = entity.ended_at
            session.flush()
            return sandbox_session_to_domain(row)

    def delete(self, entity: SandboxSession) -> None:
        """删除会话。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSandboxSession, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_run(self, run_id: str) -> builtins.list[SandboxSession]:
        """列出某 Run 关联的全部沙箱会话。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmSandboxSession)
                .where(OrmSandboxSession.run_id == run_id)
                .order_by(OrmSandboxSession.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [sandbox_session_to_domain(row) for row in rows]
