"""``SqlTaskExecutionRepository``（实现领域 ``TaskExecutionRepository``；W7 / T2-39）。

🔴 落在 ``astra_database``（ORM 允许位置，R2）；``packages/task`` 保持零 ORM。
领域实体 :class:`astra_task.TaskExecutionRecord`（零 ORM）。

对应 ORM 表：``task_execution``（随迁移 ``0015`` 落地）；唯一键 ``(task_id, attempt)``。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from astra_common.time import ensure_utc
from astra_task import TaskExecutionRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astra_database.models.task_ext import TaskExecution as OrmTaskExecution

from ..session import session_scope

__all__ = ["SqlTaskExecutionRepository"]


def _utc(value: datetime | None) -> datetime | None:
    """把（可能因 SQLite 丢 tz 而变为 naive 的）时间戳归一化为 UTC 感知对象。"""
    return ensure_utc(value) if value is not None else None


def execution_to_domain(row: OrmTaskExecution) -> TaskExecutionRecord:
    """ORM ``task_execution`` 行 → 领域 ``TaskExecutionRecord``（时间戳归一化为 UTC 感知）。"""
    return TaskExecutionRecord(
        id=row.id,
        task_id=row.task_id,
        attempt=row.attempt,
        worker_id=row.worker_id,
        status=row.status,
        started_at=_utc(row.started_at),
        finished_at=_utc(row.finished_at),
        duration_ms=row.duration_ms,
        error=row.error,
    )


def execution_to_orm(entity: TaskExecutionRecord) -> OrmTaskExecution:
    """领域 ``TaskExecutionRecord`` → ORM 行。"""
    return OrmTaskExecution(
        id=entity.id,
        task_id=entity.task_id,
        attempt=entity.attempt,
        worker_id=entity.worker_id,
        status=entity.status,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        duration_ms=entity.duration_ms,
        error=entity.error,
    )


class SqlTaskExecutionRepository:
    """基于 SQLAlchemy 的 ``task_execution`` 仓储（风格②：自持 ``sessionmaker``）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> TaskExecutionRecord | None:
        """按主键获取执行记录，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTaskExecution, entity_id)
            return execution_to_domain(row) if row is not None else None

    def add(self, entity: TaskExecutionRecord) -> TaskExecutionRecord:
        """新增执行记录并返回。"""
        with session_scope(self._session_factory) as session:
            row = execution_to_orm(entity)
            session.add(row)
            session.flush()
            return execution_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[TaskExecutionRecord]:
        """按等值条件列出执行记录。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmTaskExecution)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmTaskExecution, field) == value)
            rows = session.execute(statement).scalars().all()
            return [execution_to_domain(row) for row in rows]

    def update(self, entity: TaskExecutionRecord) -> TaskExecutionRecord:
        """更新执行记录并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTaskExecution, entity.id)
            if row is None:
                row = execution_to_orm(entity)
                session.add(row)
                session.flush()
                return execution_to_domain(row)
            row.attempt = entity.attempt
            row.worker_id = entity.worker_id
            row.status = entity.status
            row.started_at = entity.started_at
            row.finished_at = entity.finished_at
            row.duration_ms = entity.duration_ms
            row.error = entity.error
            session.flush()
            return execution_to_domain(row)

    def delete(self, entity: TaskExecutionRecord) -> None:
        """删除执行记录。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTaskExecution, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_task(self, task_id: str) -> builtins.list[TaskExecutionRecord]:
        """列出某任务的全部执行记录（按 ``attempt`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmTaskExecution)
                .where(OrmTaskExecution.task_id == task_id)
                .order_by(OrmTaskExecution.attempt.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [execution_to_domain(row) for row in rows]

    def get_by_attempt(self, task_id: str, attempt: int) -> TaskExecutionRecord | None:
        """按 ``(task_id, attempt)`` 获取执行记录，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmTaskExecution).where(
                OrmTaskExecution.task_id == task_id,
                OrmTaskExecution.attempt == attempt,
            )
            row = session.execute(statement).scalars().first()
            return execution_to_domain(row) if row is not None else None
