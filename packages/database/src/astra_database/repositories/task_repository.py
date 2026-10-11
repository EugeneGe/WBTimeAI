"""``SqlTaskRepository``（实现领域 ``TaskRepository``；W5 / T1-26）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03 / A19 先例）；``packages/task`` 保持零 ORM。

领域实体为 :class:`astra_task.models.Task`（状态机驱动，含 ``execution_mode``）。

⚠️ 现状缺口：``task`` ORM 表无 ``error`` 列，故 ``Task.error`` **不持久化**（读取恒 ``None``）。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_task import Task, TaskStatus
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astra_database.models.task import Task as OrmTask

from ..session import session_scope

__all__ = ["SqlTaskRepository"]


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


def task_to_domain(row: OrmTask) -> Task:
    """ORM 任务行 → 领域 ``astra_task.Task``。"""
    return Task(
        task_id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        type=row.type,
        status=TaskStatus(row.status),
        priority=row.priority,
        execution_mode=row.execution_mode,
        payload=dict(row.payload or {}),
        result=dict(row.result) if row.result is not None else None,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        error=None,
    )


def task_to_orm(entity: Task) -> OrmTask:
    """领域 ``astra_task.Task`` → ORM 行。"""
    return OrmTask(
        id=entity.task_id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        type=entity.type,
        status=str(entity.status),
        priority=entity.priority,
        execution_mode=entity.execution_mode,
        payload=dict(entity.payload or {}) or None,
        result=dict(entity.result) if entity.result is not None else None,
    )


class SqlTaskRepository:
    """基于 SQLAlchemy 的任务仓储（``task`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Task | None:
        """按主键获取任务，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTask, entity_id)
            return task_to_domain(row) if row is not None else None

    def add(self, entity: Task) -> Task:
        """新增任务并返回。"""
        with session_scope(self._session_factory) as session:
            row = task_to_orm(entity)
            row.created_at = _dt(entity.created_at)
            row.updated_at = _dt(entity.updated_at)
            session.add(row)
            session.flush()
            return task_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[Task]:
        """按等值条件列出任务。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmTask)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmTask, field) == value)
            rows = session.execute(statement).scalars().all()
            return [task_to_domain(row) for row in rows]

    def update(self, entity: Task) -> Task:
        """更新任务并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTask, entity.task_id)
            if row is None:
                row = task_to_orm(entity)
                session.add(row)
                session.flush()
                return task_to_domain(row)
            row.workspace_id = entity.workspace_id
            row.type = entity.type
            row.status = str(entity.status)
            row.priority = entity.priority
            row.execution_mode = entity.execution_mode
            row.payload = dict(entity.payload or {}) or None
            row.result = dict(entity.result) if entity.result is not None else None
            row.updated_at = _dt(entity.updated_at)
            session.flush()
            return task_to_domain(row)

    def delete(self, entity: Task) -> None:
        """删除任务。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTask, entity.task_id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_type(self, task_type: str) -> builtins.list[Task]:
        """列出某类型的全部任务。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmTask).where(OrmTask.type == task_type).order_by(OrmTask.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [task_to_domain(row) for row in rows]

    def list_by_status(self, status: str) -> builtins.list[Task]:
        """列出某状态的全部任务。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmTask).where(OrmTask.status == status).order_by(OrmTask.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [task_to_domain(row) for row in rows]
