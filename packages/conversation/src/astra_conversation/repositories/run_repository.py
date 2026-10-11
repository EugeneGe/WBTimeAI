"""``SqlAgentRunRepository``（实现领域 ``AgentRunRepository``）。

🔴 落在 Conversation 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。

**并发控制（设计 §2.7.2）**：同 Conversation 活跃 Run 超限时须拒绝新 Run。为保证
「检查活跃数 + 建 Run」的**原子性**，本仓储提供 :meth:`add_guarded`：

- PostgreSQL：对 ``conversation`` 行加 ``SELECT ... FOR UPDATE`` 行锁后再计数；
- SQLite：``session_scope(..., serialize_writes=True)`` 以 ``BEGIN IMMEDIATE`` 先取写锁，
  使「计数 + 建 Run」处于同一串行化写事务（等价串行化，W8-2 / A37）。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_database import session_scope
from astra_database.models.conversation import AgentRun as OrmAgentRun
from astra_database.models.conversation import Conversation as OrmConversation
from astra_domain import RUN_STATUS_RUNNING, AgentRun, RunStatus
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import run_to_domain, run_to_orm

__all__ = ["SqlAgentRunRepository"]

_ACTIVE_STATUSES = tuple(RunStatus.non_terminal_values())


class SqlAgentRunRepository:
    """基于 SQLAlchemy 的 Run 仓储（``agent_run`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentRun | None:
        """按主键获取 Run，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentRun, entity_id)
            return run_to_domain(row) if row is not None else None

    def add(self, entity: AgentRun) -> AgentRun:
        """新增 Run 并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = run_to_orm(entity)
            session.add(row)
            session.flush()
            return run_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[AgentRun]:
        """按等值条件列出 Run。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentRun)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentRun, field) == value)
            rows = session.execute(statement).scalars().all()
            return [run_to_domain(row) for row in rows]

    def update(self, entity: AgentRun) -> AgentRun:
        """更新 Run 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentRun, entity.id)
            if row is None:
                return run_to_domain(run_to_orm(entity))
            row.agent_id = entity.agent_id
            row.agent_version_id = entity.agent_version_id
            row.conversation_id = entity.conversation_id
            row.user_id = entity.user_id
            row.task_id = entity.task_id
            row.trigger = entity.trigger
            row.run_mode = entity.run_mode
            row.status = entity.status
            row.trace_id = entity.trace_id
            row.span_id = entity.span_id
            row.last_heartbeat_at = entity.last_heartbeat_at
            row.idempotency_key = entity.idempotency_key
            row.started_at = entity.started_at
            row.completed_at = entity.completed_at
            row.duration_ms = entity.duration_ms
            row.token_usage = dict(entity.token_usage or {}) or None
            row.success = entity.success
            row.error_type = entity.error_type
            row.tool_error_count = entity.tool_error_count
            row.cost = entity.cost
            row.cost_currency = entity.cost_currency
            row.cost_price_version = entity.cost_price_version
            row.cost_estimated = entity.cost_estimated
            row.cost_breakdown = dict(entity.cost_breakdown or {}) or None
            row.cost_status = entity.cost_status
            row.error = entity.error
            session.flush()
            return run_to_domain(row)

    def delete(self, entity: AgentRun) -> None:
        """删除 Run。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentRun, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_conversation(self, conversation_id: str) -> builtins.list[AgentRun]:
        """列出某会话下的全部 Run（按创建时间升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentRun)
                .where(OrmAgentRun.conversation_id == conversation_id)
                .order_by(OrmAgentRun.started_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [run_to_domain(row) for row in rows]

    def list_active_by_conversation(self, conversation_id: str) -> builtins.list[AgentRun]:
        """列出某会话下的**活跃**（非终态）Run。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentRun).where(
                OrmAgentRun.conversation_id == conversation_id,
                OrmAgentRun.status.in_(_ACTIVE_STATUSES),
            )
            rows = session.execute(statement).scalars().all()
            return [run_to_domain(row) for row in rows]

    def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> AgentRun | None:
        """按 ``(tenant_id, idempotency_key)`` 唯一键获取 Run（幂等去重）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentRun).where(
                OrmAgentRun.tenant_id == tenant_id,
                OrmAgentRun.idempotency_key == idempotency_key,
            )
            row = session.execute(statement).scalars().first()
            return run_to_domain(row) if row is not None else None

    def add_guarded(self, entity: AgentRun, *, max_active: int) -> AgentRun | None:
        """**原子**地「检查活跃 Run 数 + 建 Run」（设计 §2.7.2）。

        - PostgreSQL：对 ``conversation`` 行加 ``SELECT ... FOR UPDATE`` 行锁；
        - SQLite：``serialize_writes=True`` 使事务以 ``BEGIN IMMEDIATE`` **先取写锁**
          （等价串行化，§2.7.2），计数与建 Run 处于**同一串行化写事务**。

        若创建后将超出 ``max_active`` 则返回 ``None``（``serialize_writes`` 对 PG **no-op**，
        PG 路径语义逐位不变）。
        """
        with session_scope(self._session_factory, serialize_writes=True) as session:
            if _dialect_name(session) == "postgresql":
                session.execute(
                    select(OrmConversation.id)
                    .where(OrmConversation.id == entity.conversation_id)
                    .with_for_update()
                )
            active = session.execute(
                select(func.count())
                .select_from(OrmAgentRun)
                .where(
                    OrmAgentRun.conversation_id == entity.conversation_id,
                    OrmAgentRun.status.in_(_ACTIVE_STATUSES),
                )
            ).scalar_one()
            if int(active) + 1 > max_active:
                return None
            row = run_to_orm(entity)
            session.add(row)
            session.flush()
            return run_to_domain(row)

    def touch_heartbeat(self, run_id: str, *, at: datetime | None = None) -> None:
        """更新某 Run 的心跳时刻（``UPDATE agent_run SET last_heartbeat_at = ...``）。

        幂等：Run 不存在时静默返回。Runtime **每轮迭代**调用（W6 / T1-31）。
        """
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentRun, run_id)
            if row is None:
                return
            row.last_heartbeat_at = at if at is not None else utcnow()
            session.flush()

    def list_stale_running(self, threshold: datetime) -> builtins.list[AgentRun]:
        """列出 ``status=RUNNING`` 且心跳超期的 Run（重启兜底扫描，W6 / T1-31）。

        超期判定：``last_heartbeat_at < threshold``，或 ``last_heartbeat_at`` 为空且
        ``started_at < threshold``。
        """
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentRun).where(
                OrmAgentRun.status == RUN_STATUS_RUNNING,
                or_(
                    OrmAgentRun.last_heartbeat_at < threshold,
                    and_(
                        OrmAgentRun.last_heartbeat_at.is_(None),
                        OrmAgentRun.started_at < threshold,
                    ),
                ),
            )
            rows = session.execute(statement).scalars().all()
            return [run_to_domain(row) for row in rows]


def _dialect_name(session: Session) -> str:
    """返回当前会话绑定引擎的方言名（``postgresql`` / ``sqlite`` …）。"""
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""
