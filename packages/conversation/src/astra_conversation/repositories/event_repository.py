"""``SqlAgentEventRepository``（实现领域 ``AgentEventRepository``）。

🔴 落在 Conversation 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。

**§5 #13（全量落库 + 批量写入）**：由 :meth:`add_many` 一次性批量写入，
``seq`` 按 ``run_id`` 单调递增；:meth:`list_after_seq` 支持 ``Last-Event-ID`` 续传。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.conversation import AgentEvent as OrmAgentEvent
from astra_domain import AgentEvent
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import event_to_domain, event_to_orm

__all__ = ["SqlAgentEventRepository"]


class SqlAgentEventRepository:
    """基于 SQLAlchemy 的事件仓储（``agent_event`` 表，批量写入 + 回放）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentEvent | None:
        """按主键获取事件，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentEvent, entity_id)
            return event_to_domain(row) if row is not None else None

    def add(self, entity: AgentEvent) -> AgentEvent:
        """新增单条事件（``seq`` 缺省时自增）。"""
        return self.add_many([entity])[0]

    def list(self, **filters: Any) -> builtins.list[AgentEvent]:
        """按等值条件列出事件（按 ``seq`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentEvent)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentEvent, field) == value)
            statement = statement.order_by(OrmAgentEvent.seq.asc())
            rows = session.execute(statement).scalars().all()
            return [event_to_domain(row) for row in rows]

    def update(self, entity: AgentEvent) -> AgentEvent:
        """更新事件并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentEvent, entity.id)
            if row is None:
                return event_to_domain(event_to_orm(entity))
            row.seq = entity.seq
            row.type = entity.type
            row.payload = dict(entity.payload or {}) or None
            row.trace_id = entity.trace_id
            row.span_id = entity.span_id
            session.flush()
            return event_to_domain(row)

    def delete(self, entity: AgentEvent) -> None:
        """删除事件。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentEvent, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_run(self, run_id: str) -> builtins.list[AgentEvent]:
        """按 ``seq`` 升序列出某 Run 的全部事件（供回放）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentEvent)
                .where(OrmAgentEvent.run_id == run_id)
                .order_by(OrmAgentEvent.seq.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [event_to_domain(row) for row in rows]

    def add_many(self, events: builtins.list[AgentEvent]) -> builtins.list[AgentEvent]:
        """**批量**写入事件（§5 #13）。

        ``seq`` 按 ``run_id`` 单调递增：未提供（``<=0``）或非递增时自动补齐。
        """
        if not events:
            return []
        with session_scope(self._session_factory) as session:
            next_seq: dict[str, int] = {}
            rows: list[OrmAgentEvent] = []
            for entity in events:
                run_id = entity.run_id
                if run_id not in next_seq:
                    current_max = session.execute(
                        select(func.max(OrmAgentEvent.seq)).where(OrmAgentEvent.run_id == run_id)
                    ).scalar()
                    next_seq[run_id] = int(current_max or 0)
                seq = (
                    entity.seq
                    if entity.seq and entity.seq > next_seq[run_id]
                    else next_seq[run_id] + 1
                )
                next_seq[run_id] = seq
                row = event_to_orm(entity, seq=seq)
                session.add(row)
                rows.append(row)
            session.flush()
            return [event_to_domain(row) for row in rows]

    def list_after_seq(
        self, run_id: str, last_event_id: int | None = None
    ) -> builtins.list[AgentEvent]:
        """按 ``seq`` 升序列出 ``seq > last_event_id`` 的事件（``Last-Event-ID`` 续传）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentEvent).where(OrmAgentEvent.run_id == run_id)
            if last_event_id is not None:
                statement = statement.where(OrmAgentEvent.seq > last_event_id)
            statement = statement.order_by(OrmAgentEvent.seq.asc())
            rows = session.execute(statement).scalars().all()
            return [event_to_domain(row) for row in rows]
