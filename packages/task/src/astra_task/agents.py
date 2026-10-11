"""解锁 ``SCHEDULED_AGENT`` / ``EVENT_AGENT``（W7 / T2-39）。

W7 起，调度基座解锁两类「触发型」Agent：``SCHEDULED_AGENT``（cron 定时）与
``EVENT_AGENT``（事件驱动）。:class:`ScheduledAgentUnlocker` 提供两种 Agent 类型 →
触发类型的映射与校验。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁，R2）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode
from astra_domain import AGENT_TYPE_EVENT_AGENT, AGENT_TYPE_SCHEDULED_AGENT

from .scheduler.triggers import TRIGGER_CRON, TRIGGER_EVENT

__all__ = [
    "SCHEDULED_AGENT",
    "EVENT_AGENT",
    "AGENT_TYPE_TO_TRIGGER",
    "UNLOCKED_AGENT_TYPES",
    "ScheduledAgentUnlocker",
]

#: 定时 Agent 类型（= ``astra_domain`` 常量，冻结词表）。
SCHEDULED_AGENT = AGENT_TYPE_SCHEDULED_AGENT

#: 事件 Agent 类型（= ``astra_domain`` 常量，冻结词表）。
EVENT_AGENT = AGENT_TYPE_EVENT_AGENT

#: Agent 类型 → 触发类型映射（W7 解锁契约）。
AGENT_TYPE_TO_TRIGGER: dict[str, str] = {
    SCHEDULED_AGENT: TRIGGER_CRON,
    EVENT_AGENT: TRIGGER_EVENT,
}

#: 已解锁（可调度）的 Agent 类型集合。
UNLOCKED_AGENT_TYPES: frozenset[str] = frozenset(AGENT_TYPE_TO_TRIGGER)


@runtime_checkable
class _Unlocker(Protocol):
    """解锁器接口（结构化契约）。"""

    def is_unlocked(self, agent_type: str) -> bool:
        """判断该 Agent 类型是否已解锁。"""
        ...


class ScheduledAgentUnlocker:
    """``SCHEDULED_AGENT`` / ``EVENT_AGENT`` 解锁器（W7）。"""

    def is_unlocked(self, agent_type: str) -> bool:
        """判断 ``agent_type`` 是否为已解锁的触发型 Agent。"""
        return agent_type in UNLOCKED_AGENT_TYPES

    def resolve_trigger(self, agent_type: str) -> str:
        """返回该 Agent 类型对应的触发类型。

        Raises:
            DomainError: 未解锁的 Agent 类型（``VALIDATION_ERROR``）。
        """
        try:
            return AGENT_TYPE_TO_TRIGGER[agent_type]
        except KeyError as exc:
            raise DomainError(
                f"Agent 类型未解锁调度：{agent_type}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "agent_type"},
            ) from exc

    def assert_unlocked(self, agent_type: str) -> None:
        """断言 Agent 类型已解锁。

        Raises:
            DomainError: 未解锁（``VALIDATION_ERROR``）。
        """
        if not self.is_unlocked(agent_type):
            raise DomainError(
                f"Agent 类型未解锁调度：{agent_type}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "agent_type"},
            )
