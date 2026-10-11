"""TaskExecution / Schedule ORM 表（设计 §2.9 / §2.15；W7 / T2-37）。

- :class:`TaskExecution`：任务每次 **attempt** 的执行记录（``task`` 1:N ``task_execution``）；
  唯一键 ``(task_id, attempt)``（``uq_task_execution_task_attempt``，§2.9.1 冻结契约）。
- :class:`Schedule`：任务调度定义（``cron`` / ``event`` / ``webhook`` / ``manual``）；
  唯一键 ``(tenant_id, target_type, target_id, name)``（``uq_schedule_target_name``，冻结契约）。

🔴 **本模块独立于 ``task.py``（R5）**：避免 ``task.py`` 膨胀，且 ``0018``（远端执行增量）
   对 ``task_execution`` 加列时自然映射（§2.15.5）。
🔴 **``astra_task`` 零 ORM（R2）**：任务执行记录 / 调度的 **ORM + SQL 一律落
   ``astra_database``**（本模块 + ``repositories/task_execution_repository.py`` /
   ``schedule_repository.py``）；``packages/task`` 经**注入 Protocol** 使用。
🔴 ``task_execution`` **仅建基础列**（§3.3）；``0018`` 预留列（``project_id`` / ``checkout_ref``
   / ``base_commit`` / ``result_commit`` / ``environment_digest`` / ``artifact_refs`` /
   ``heartbeat_at`` / ``lease_expires_at``）**本波不建**。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_core import generate_id
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Schedule", "TaskExecution"]


class TaskExecution(Base):
    """``task_execution``：任务某次尝试的执行记录（``task`` 1:N，§2.9.1）。

    Attributes:
        task_id: 归属任务标识（NOT NULL）。
        attempt: 尝试序号（**从 1 起**）。
        worker_id: 执行 worker 标识（可空）。
        status: 执行状态（复用 ``TaskStatus`` 词表）。
        started_at: 开始时间（可空）。
        finished_at: 结束时间（可空）。
        duration_ms: 持续毫秒（可空）。
        error: 错误信息（可空）。
    """

    __tablename__ = "task_execution"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_task_execution_task_attempt"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    task_id: Mapped[str] = mapped_column(GUID(), ForeignKey("task.id"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer(), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class Schedule(Base, TimestampMixin):
    """``schedule``：任务调度定义（§3.4；唯一键 ``(tenant_id, target_type, target_id, name)``）。

    Attributes:
        tenant_id: 所属租户（硬隔离，I-1）。
        organization_id: 组织归属（可空，A-7；``0015`` 建表即含，``0016`` 仅回填）。
        workspace_id: 归属 Workspace（可空）。
        name: 调度名称。
        target_type: 目标类型（``agent`` / ``workflow``）。
        target_id: 目标标识。
        trigger: 触发类型（``cron`` / ``event`` / ``webhook`` / ``manual``）。
        cron: cron 表达式（``trigger=cron`` 时必填，应用层校验）。
        event_type: 事件类型（``trigger=event`` 时必填）。
        payload: 触发载荷（JSON 结构，可承载 ``schedule_id`` 关联）。
        enabled: 是否启用（默认 ``True``）。
        last_run_at: 上次触发时间（可空）。
        next_run_at: 下次触发时间（可空，到期轮询锚，索引）。
    """

    __tablename__ = "schedule"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_id",
            "name",
            name="uq_schedule_target_name",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(GUID(), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    cron: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
