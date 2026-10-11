"""``SqlScheduleRepository``（实现领域 ``ScheduleRepository``；W7 / T2-39）。

🔴 落在 ``astra_database``（ORM 允许位置，R2）；``packages/task`` 保持零 ORM。
领域实体 :class:`astra_task.ScheduleSpec`（零 ORM）。

对应 ORM 表：``schedule``（随迁移 ``0015`` 落地）；唯一键
``(tenant_id, target_type, target_id, name)``。

🔴 **幂等契约（R6）**：:meth:`get_or_create_task` 封装「同一 ``idempotency_key`` 只建 1 个
   ``task``」——命中 ``task.idempotency_key`` 唯一索引 → 返回既有 ``task_id``（``created=False``）。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from astra_common.time import ensure_utc, utcnow
from astra_task import ScheduleSpec
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astra_database.models.task import Task as OrmTask
from astra_database.models.task_ext import Schedule as OrmSchedule

from ..session import session_scope

__all__ = ["SqlScheduleRepository"]


def _utc(value: datetime | None) -> datetime | None:
    """把（可能因 SQLite 丢 tz 而变为 naive 的）时间戳归一化为 UTC 感知对象。"""
    return ensure_utc(value) if value is not None else None


def schedule_to_domain(row: OrmSchedule) -> ScheduleSpec:
    """ORM ``schedule`` 行 → 领域 ``ScheduleSpec``（时间戳归一化为 UTC 感知）。"""
    return ScheduleSpec(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        name=row.name,
        target_type=row.target_type,
        target_id=row.target_id,
        trigger=row.trigger,
        cron=row.cron,
        event_type=row.event_type,
        payload=dict(row.payload) if row.payload else {},
        enabled=bool(row.enabled),
        last_run_at=_utc(row.last_run_at),
        next_run_at=_utc(row.next_run_at),
        created_at=_utc(row.created_at) or utcnow(),
        updated_at=_utc(row.updated_at) or utcnow(),
    )


def schedule_to_orm(entity: ScheduleSpec) -> OrmSchedule:
    """领域 ``ScheduleSpec`` → ORM ``schedule`` 行。"""
    return OrmSchedule(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        organization_id=entity.organization_id,
        name=entity.name,
        target_type=entity.target_type,
        target_id=entity.target_id,
        trigger=entity.trigger,
        cron=entity.cron,
        event_type=entity.event_type,
        payload=dict(entity.payload) if entity.payload else {},
        enabled=bool(entity.enabled),
        last_run_at=entity.last_run_at,
        next_run_at=entity.next_run_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class SqlScheduleRepository:
    """基于 SQLAlchemy 的 ``schedule`` 仓储（风格②：自持 ``sessionmaker``）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- CRUD ---------------------------------------------------------------

    def get(self, entity_id: str) -> ScheduleSpec | None:
        """按主键获取调度，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSchedule, entity_id)
            return schedule_to_domain(row) if row is not None else None

    def create(
        self,
        *,
        tenant_id: str,
        name: str,
        target_type: str,
        target_id: str,
        trigger: str,
        workspace_id: str | None = None,
        organization_id: str | None = None,
        cron: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> ScheduleSpec:
        """创建调度（以原语入参，内部构造领域实体 + 校验）。

        Raises:
            DomainError: 字段非法（``VALIDATION_ERROR``）。
        """
        entity = ScheduleSpec(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            organization_id=organization_id,
            name=(name or "").strip(),
            target_type=target_type,
            target_id=target_id,
            trigger=trigger,
            cron=cron,
            event_type=event_type,
            payload=dict(payload) if payload else {},
            enabled=bool(enabled),
        )
        entity.assert_valid()
        return self.add(entity)

    def add(self, entity: ScheduleSpec) -> ScheduleSpec:
        """新增调度并返回。"""
        with session_scope(self._session_factory) as session:
            row = schedule_to_orm(entity)
            session.add(row)
            session.flush()
            return schedule_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[ScheduleSpec]:
        """按等值条件列出调度。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSchedule)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmSchedule, field) == value)
            rows = session.execute(statement).scalars().all()
            return [schedule_to_domain(row) for row in rows]

    def update(self, entity: ScheduleSpec) -> ScheduleSpec:
        """更新调度并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSchedule, entity.id)
            if row is None:
                row = schedule_to_orm(entity)
                session.add(row)
                session.flush()
                return schedule_to_domain(row)
            row.name = entity.name
            row.target_type = entity.target_type
            row.target_id = entity.target_id
            row.trigger = entity.trigger
            row.cron = entity.cron
            row.event_type = entity.event_type
            row.payload = dict(entity.payload) if entity.payload else {}
            row.enabled = bool(entity.enabled)
            row.last_run_at = entity.last_run_at
            row.next_run_at = entity.next_run_at
            row.updated_at = utcnow()
            session.flush()
            return schedule_to_domain(row)

    def delete(self, entity: ScheduleSpec) -> None:
        """删除调度。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSchedule, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    # -- 查询 / 触发 --------------------------------------------------------

    def list_due(
        self, *, now: datetime, tenant_id: str | None = None, limit: int | None = None
    ) -> builtins.list[ScheduleSpec]:
        """列出 ``enabled`` 且 ``next_run_at <= now`` 的到期调度（按 ``next_run_at`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSchedule).where(
                OrmSchedule.enabled.is_(True),
                OrmSchedule.next_run_at.is_not(None),
                OrmSchedule.next_run_at <= now,
            )
            if tenant_id is not None:
                statement = statement.where(OrmSchedule.tenant_id == tenant_id)
            statement = statement.order_by(OrmSchedule.next_run_at.asc())
            if limit is not None and limit > 0:
                statement = statement.limit(int(limit))
            rows = session.execute(statement).scalars().all()
            return [schedule_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[ScheduleSpec]:
        """列出某租户的全部调度。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmSchedule)
                .where(OrmSchedule.tenant_id == tenant_id)
                .order_by(OrmSchedule.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [schedule_to_domain(row) for row in rows]

    def mark_fired(
        self, schedule_id: str, *, fired_at: datetime, next_run_at: datetime | None
    ) -> ScheduleSpec | None:
        """标记调度已触发（写 ``last_run_at`` / ``next_run_at``），返回更新后的调度。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSchedule, schedule_id)
            if row is None:
                return None
            row.last_run_at = fired_at
            row.next_run_at = next_run_at
            row.updated_at = utcnow()
            session.flush()
            return schedule_to_domain(row)

    def get_or_create_task(
        self,
        *,
        tenant_id: str,
        workspace_id: str | None,
        task_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, bool]:
        """幂等创建 ``task``（R6）：命中 ``idempotency_key`` 返回既有 id；否则新建。

        Returns:
            ``(task_id, created)``。
        """
        with session_scope(self._session_factory) as session:
            existing = (
                session.execute(select(OrmTask).where(OrmTask.idempotency_key == idempotency_key))
                .scalars()
                .first()
            )
            if existing is not None:
                return existing.id, False
            row = OrmTask(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                type=task_type,
                status="CREATED",
                priority=0,
                execution_mode="QUEUED",
                payload=dict(payload),
                idempotency_key=idempotency_key,
            )
            session.add(row)
            session.flush()
            return row.id, True
