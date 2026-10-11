"""``SchedulerTick``——调度轮询执行体（**零 ORM**；W7 / T2-39；R14）。

``tick(now)`` **显式接收 ``now``**（可注入 **fake clock**）：
1. 取到期调度（``next_run_at <= now``，带租户范围）；
2. 生成幂等键 ``f"{target_type}:{target_id}:{fire_time}"`` → **幂等**创建 ``task``
   （命中唯一索引 → 返回既有 task，**不重复建**）；
3. 首次创建时落 ``task_execution``（``attempt`` 自增）；
4. 推进 ``schedule.next_run_at / last_run_at``。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁，R2）；
   持久化经注入的 ``ScheduleRepository`` / ``TaskExecutionRepository`` Protocol。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from astra_common.time import ensure_utc

from ..agents import ScheduledAgentUnlocker
from .idempotency import IdempotencyKey
from .triggers import ScheduleSpec, Trigger, resolve_trigger

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_domain.repositories import ScheduleRepository, TaskExecutionRepository

    from ..execution_record import ExecutionRecorder

__all__ = ["SchedulerTick"]

#: 默认单次 tick 处理上限。
DEFAULT_TICK_LIMIT = 100


@dataclass
class SchedulerTick:
    """调度轮询执行体（组合根注入仓储 / 记录器 / 触发策略）。

    Attributes:
        schedules: 调度仓储（``ScheduleRepository`` Protocol）。
        executions: 任务执行记录仓储（``TaskExecutionRepository`` Protocol）。
        recorder: 执行记录器（缺省按 ``executions`` 构造）。
        agents: ``SCHEDULED_AGENT`` / ``EVENT_AGENT`` 解锁器。
        trigger_resolver: 触发类型 → 策略解析器（缺省 :func:`resolve_trigger`）。
    """

    schedules: ScheduleRepository
    executions: TaskExecutionRepository
    recorder: ExecutionRecorder | None = None
    agents: ScheduledAgentUnlocker = field(default_factory=ScheduledAgentUnlocker)
    trigger_resolver: Callable[[str], Trigger] = resolve_trigger

    def __post_init__(self) -> None:
        """装配缺省执行记录器。"""
        if self.recorder is None:
            from ..execution_record import ExecutionRecorder

            self.recorder = ExecutionRecorder(self.executions)

    # -- 轮询 ---------------------------------------------------------------

    def tick(
        self, now: datetime, *, tenant_id: str | None = None, limit: int = DEFAULT_TICK_LIMIT
    ) -> list[str]:
        """轮询到期调度并触发；返回**本次新建**的 ``task_id`` 列表。

        Args:
            now: 当前时间（**显式注入**，可 fake clock）。
            tenant_id: 租户范围过滤（可选）。
            limit: 单次处理上限。

        Returns:
            本次新建的 ``task_id`` 列表（幂等命中既有 task 时**不计入**）。
        """
        fired: list[str] = []
        now = ensure_utc(now)
        for schedule in self.schedules.list_due(now=now, tenant_id=tenant_id, limit=limit):
            if not schedule.enabled:
                continue
            trigger = self.trigger_resolver(schedule.trigger)
            if not trigger.is_due(now, schedule):
                continue
            fire_time = (
                ensure_utc(schedule.next_run_at) if schedule.next_run_at is not None else now
            )
            task_id, created = self._fire(schedule, fire_time=fire_time, now=now)
            if created:
                fired.append(task_id)
        return fired

    def fire_now(self, now: datetime, schedule: ScheduleSpec) -> str | None:
        """显式触发一次（manual / webhook 路径）；返回 ``task_id``。

        Raises:
            DomainError: 未解锁的 Agent 目标类型（``VALIDATION_ERROR``）。
        """
        moment = ensure_utc(now)
        task_id, _created = self._fire(schedule, fire_time=moment, now=moment)
        return task_id

    # -- 内部 ---------------------------------------------------------------

    def _fire(
        self, schedule: ScheduleSpec, *, fire_time: datetime, now: datetime
    ) -> tuple[str, bool]:
        """触发一条调度（幂等建 task + 落执行记录 + 推进 next_run_at）。"""
        fire_time = ensure_utc(fire_time)
        now = ensure_utc(now)
        key = IdempotencyKey.key(schedule.target_type, schedule.target_id, fire_time)
        task_type = f"{schedule.target_type}.{schedule.trigger}"
        payload: dict[str, Any] = dict(schedule.payload or {})
        payload.update(
            {
                "schedule_id": schedule.id,
                "target_type": schedule.target_type,
                "target_id": schedule.target_id,
                "fire_time": fire_time.isoformat(),
            }
        )
        task_id, created = self.schedules.get_or_create_task(
            tenant_id=schedule.tenant_id,
            workspace_id=schedule.workspace_id,
            task_type=task_type,
            payload=payload,
            idempotency_key=key,
        )
        if created and self.recorder is not None:
            self.recorder.begin(task_id=task_id, started_at=now)
        next_run = self.trigger_resolver(schedule.trigger).next_fire(now, schedule)
        self.schedules.mark_fired(schedule.id, fired_at=now, next_run_at=next_run)
        return task_id, created
