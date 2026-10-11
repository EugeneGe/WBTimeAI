"""``AgentSkill`` 绑定实体（设计 §2.3 / 修订 C2-09；W2 裁定 R6）。

Skill 绑定**随 ``AgentVersion`` 一起版本化**（与 ``AgentTool`` **完全同构**）：
一次发布 = 一个新 ``AgentVersion`` → 旧绑定随旧版本冻结；回滚 = 指向旧
``agent_version_id``。故 Agent 行为（含挂载的 Skill 指令）可回滚、可重建。

纯 dataclass，零框架依赖（C-03）；主键经 :class:`~astra_domain.entities.base.Entity`
默认由 :func:`astra_core.generate_id` 生成（C-04）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import AggregateRoot

__all__ = ["AgentSkill"]


@dataclass
class AgentSkill(AggregateRoot):
    """AgentSkill 聚合根（绑定到 AgentVersion 的 Skill + 附加 config）。

    Attributes:
        agent_version_id: 绑定的 AgentVersion 标识。
        skill_id: 绑定的 Skill 标识。
        enabled: 是否启用（默认 ``True``）。
        config: 绑定额外配置（JSON 结构，可空；如覆盖指令 / 变量）。
    """

    agent_version_id: str = ""
    skill_id: str = ""
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
