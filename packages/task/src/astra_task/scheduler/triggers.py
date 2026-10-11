"""调度触发器（Cron / Event / Webhook / Manual；W7 / T2-39）。

- :class:`ScheduleSpec`：**零 ORM** 调度定义（域实体，映射 ``schedule`` 表）；
- :class:`Trigger`：触发策略 Protocol（``is_due`` / ``next_fire``）；
- 具体触发：:class:`CronTrigger` / :class:`EventTrigger` / :class:`WebhookTrigger` /
  :class:`ManualTrigger`；:func:`resolve_trigger` 按 ``trigger`` 词表选路。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁，R2）；
   持久化经注入的 ``ScheduleRepository`` Protocol（``astra_domain``）。
🔴 时间**显式传入**（``next_fire(now, schedule)``），可注入 **fake clock**（R14）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from astra_common.time import ensure_utc, utcnow
from astra_core import DomainError, ErrorCode, generate_id

__all__ = [
    "ScheduleSpec",
    "Trigger",
    "CronTrigger",
    "EventTrigger",
    "WebhookTrigger",
    "ManualTrigger",
    "resolve_trigger",
    "TRIGGER_CRON",
    "TRIGGER_EVENT",
    "TRIGGER_WEBHOOK",
    "TRIGGER_MANUAL",
    "TRIGGERS",
    "TARGET_TYPE_AGENT",
    "TARGET_TYPE_WORKFLOW",
    "TARGET_TYPES",
]

#: 触发类型词表（冻结契约，§3.4）。
TRIGGER_CRON = "cron"
TRIGGER_EVENT = "event"
TRIGGER_WEBHOOK = "webhook"
TRIGGER_MANUAL = "manual"
TRIGGERS: frozenset[str] = frozenset({TRIGGER_CRON, TRIGGER_EVENT, TRIGGER_WEBHOOK, TRIGGER_MANUAL})

#: 目标类型词表（冻结契约，§3.4）。
TARGET_TYPE_AGENT = "agent"
TARGET_TYPE_WORKFLOW = "workflow"
TARGET_TYPES: frozenset[str] = frozenset({TARGET_TYPE_AGENT, TARGET_TYPE_WORKFLOW})


@dataclass
class ScheduleSpec:
    """调度定义（**零 ORM** 域实体；映射 ``schedule`` 表，§3.4）。

    Attributes:
        id: 调度标识（UUIDv7）。
        tenant_id: 所属租户（硬隔离，I-1）。
        workspace_id: 归属 Workspace（可空）。
        organization_id: 组织归属（可空，A-7）。
        name: 调度名称。
        target_type: 目标类型（``agent`` / ``workflow``）。
        target_id: 目标标识。
        trigger: 触发类型（``cron`` / ``event`` / ``webhook`` / ``manual``）。
        cron: cron 表达式（``trigger=cron`` 时必填）。
        event_type: 事件类型（``trigger=event`` 时必填）。
        payload: 触发载荷。
        enabled: 是否启用。
        last_run_at: 上次触发时间（可空）。
        next_run_at: 下次触发时间（可空，到期轮询锚）。
        created_at / updated_at: 时间戳（UTC）。
    """

    tenant_id: str = ""
    workspace_id: str | None = None
    organization_id: str | None = None
    name: str = ""
    target_type: str = TARGET_TYPE_AGENT
    target_id: str = ""
    trigger: str = TRIGGER_MANUAL
    cron: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    id: str = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def touch(self) -> None:
        """刷新 ``updated_at`` 为当前 UTC。"""
        self.updated_at = utcnow()

    def assert_valid(self) -> None:
        """断言调度定义合法（词表 + 条件必填）。

        Raises:
            DomainError: 字段非法（``VALIDATION_ERROR``）。
        """
        if not (self.name or "").strip():
            raise DomainError(
                "调度名称不能为空", code=ErrorCode.VALIDATION_ERROR, data={"field": "name"}
            )
        if self.target_type not in TARGET_TYPES:
            raise DomainError(
                f"目标类型非法：{self.target_type}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "target_type"},
            )
        if not (self.target_id or "").strip():
            raise DomainError(
                "目标标识不能为空", code=ErrorCode.VALIDATION_ERROR, data={"field": "target_id"}
            )
        if self.trigger not in TRIGGERS:
            raise DomainError(
                f"触发类型非法：{self.trigger}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "trigger"},
            )
        if self.trigger == TRIGGER_CRON and not (self.cron or "").strip():
            raise DomainError(
                "cron 触发必须提供 cron 表达式",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "cron"},
            )
        if self.trigger == TRIGGER_EVENT and not (self.event_type or "").strip():
            raise DomainError(
                "event 触发必须提供事件类型",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "event_type"},
            )


@runtime_checkable
class Trigger(Protocol):
    """触发策略接口（**零 ORM**）。"""

    trigger_type: str

    def is_due(self, now: datetime, schedule: ScheduleSpec) -> bool:
        """在 ``now`` 时刻，该调度是否到期应触发。"""
        ...

    def next_fire(self, now: datetime, schedule: ScheduleSpec) -> datetime | None:
        """计算 ``now`` 之后的下次触发时间（无则 ``None``）。"""
        ...


class CronTrigger:
    """Cron 触发（``next_fire`` 用 APScheduler cron 解析；懒导入）。"""

    trigger_type = TRIGGER_CRON

    def is_due(self, now: datetime, schedule: ScheduleSpec) -> bool:
        """到期判定：``next_run_at`` 非空且不晚于 ``now``（时间归一化为 UTC 感知）。"""
        if schedule.next_run_at is None:
            return False
        return ensure_utc(schedule.next_run_at) <= ensure_utc(now)

    def next_fire(self, now: datetime, schedule: ScheduleSpec) -> datetime | None:
        """按 ``schedule.cron`` 计算 ``now`` 之后的下次触发时间。

        Raises:
            DomainError: cron 表达式非法（``VALIDATION_ERROR``）。
        """
        cron = (schedule.cron or "").strip()
        if not cron:
            return None

        from apscheduler.triggers.cron import CronTrigger as _ApsCronTrigger

        try:
            trigger = _ApsCronTrigger.from_crontab(cron, timezone=UTC)
        except ValueError as exc:
            raise DomainError(
                f"cron 表达式非法：{schedule.cron}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "cron"},
            ) from exc
        # 以**调度自身上次计划触发时间**（``next_run_at``）为锚，返回**严格晚于**它的下次触发，
        # 避免下一时刻仍等于 ``now`` 导致调度「滞留到期」（幂等亦兜底）。
        previous = schedule.next_run_at if schedule.next_run_at is not None else now
        return trigger.get_next_fire_time(ensure_utc(previous), ensure_utc(now))


class EventTrigger:
    """Event 触发（事件到达时外部设置 ``next_run_at``；本类按到期判定）。"""

    trigger_type = TRIGGER_EVENT

    def is_due(self, now: datetime, schedule: ScheduleSpec) -> bool:
        """到期判定：``next_run_at`` 非空且不晚于 ``now``（事件驱动，无周期预测）。"""
        if schedule.next_run_at is None:
            return False
        return ensure_utc(schedule.next_run_at) <= ensure_utc(now)

    def next_fire(self, now: datetime, schedule: ScheduleSpec) -> datetime | None:
        """事件触发无周期预测 → ``None``。"""
        return None


class WebhookTrigger:
    """Webhook 触发（回调到达时执行；回调地址须经 ``EgressPolicy``）。"""

    trigger_type = TRIGGER_WEBHOOK

    def is_due(self, now: datetime, schedule: ScheduleSpec) -> bool:
        """到期判定：``next_run_at`` 非空且不晚于 ``now``。"""
        if schedule.next_run_at is None:
            return False
        return ensure_utc(schedule.next_run_at) <= ensure_utc(now)

    def next_fire(self, now: datetime, schedule: ScheduleSpec) -> datetime | None:
        """Webhook 触发无周期预测 → ``None``。"""
        return None


class ManualTrigger:
    """Manual 触发（仅显式调用 `SchedulerTick.fire_now`；不参与到期轮询）。"""

    trigger_type = TRIGGER_MANUAL

    def is_due(self, now: datetime, schedule: ScheduleSpec) -> bool:
        """手动触发不参与到期轮询 → 恒 ``False``。"""
        return False

    def next_fire(self, now: datetime, schedule: ScheduleSpec) -> datetime | None:
        """手动触发无周期预测 → ``None``。"""
        return None


#: 触发类型 → 策略实例（无状态，进程级复用）。
_TRIGGER_STRATEGIES: dict[str, Trigger] = {
    TRIGGER_CRON: CronTrigger(),
    TRIGGER_EVENT: EventTrigger(),
    TRIGGER_WEBHOOK: WebhookTrigger(),
    TRIGGER_MANUAL: ManualTrigger(),
}


def resolve_trigger(trigger_type: str) -> Trigger:
    """按触发类型词表选路。

    Raises:
        DomainError: 未知触发类型（``VALIDATION_ERROR``）。
    """
    try:
        return _TRIGGER_STRATEGIES[trigger_type]
    except KeyError as exc:
        raise DomainError(
            f"未知触发类型：{trigger_type}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"field": "trigger"},
        ) from exc
