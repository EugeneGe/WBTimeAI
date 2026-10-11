"""RP-05 · ``Planner``（规划预留位；总纲 §12.2）。

Phase 1 仅提供**完整 Protocol 签名 + 可装配空实现**；Phase 2 填充实现时**不得改签名**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import Plan

__all__ = ["Planner", "NullPlanner"]


@runtime_checkable
class Planner(Protocol):
    """规划器（RP-05）。"""

    def plan(self, goal: str, context: dict[str, object] | None = None) -> Plan:
        """为一个目标产出执行计划。

        Raises:
            DomainError: 规划失败（``INTERNAL_ERROR``）。
        """
        ...


class NullPlanner:
    """空实现（Phase 1）：返回仅含目标、无步骤的空计划。"""

    def plan(self, goal: str, context: dict[str, object] | None = None) -> Plan:
        """返回空计划（``goal`` 原样透传）。"""
        return Plan(goal=goal, steps=[])
