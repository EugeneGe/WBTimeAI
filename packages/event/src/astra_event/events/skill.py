"""Skill 解析事件（Phase 2 · W3 / T2-16；设计 §2.11；裁定 §6.1）。

1 类事件，**继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02）。

- ``SkillResolved``：``skill.resolved`` —— Skill 解析结果（2a 产出）。

🔴 本模块**只定义事件类型**，``EventBus`` Protocol 保持不变（C-02）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["SkillResolved"]


@dataclass
class SkillResolved(DomainEvent):
    """Skill 解析事件（``skill.resolved``）。"""

    type: ClassVar[str] = "skill.resolved"

    @classmethod
    def create(
        cls,
        *,
        skill_name: str,
        skill_id: str | None = None,
        version: str | None = None,
        run_id: str | None = None,
    ) -> SkillResolved:
        """便捷构造。"""
        payload: dict[str, Any] = {"skill_name": skill_name}
        if skill_id is not None:
            payload["skill_id"] = skill_id
        if version is not None:
            payload["version"] = version
        if run_id is not None:
            payload["run_id"] = run_id
        return cls(payload=payload)
