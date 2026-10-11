"""RP-01 · ``SkillResolver``（技能解析预留位；总纲 §12.2）。

Phase 1 仅提供**完整 Protocol 签名 + 可装配空实现**；Phase 2 填充实现时**不得改签名**。
输入输出类型落 ``astra_domain.ports``（跨包共享）。

W2 / T2-09 **接线口径**（Erratum-1/2）：

- 本文件**保留** :class:`SkillResolver` Protocol 与 :class:`NullSkillResolver`（签名**不变**）；
- **真实实现**落 ``astra_skill.resolver.SkillResolver``（**结构化契合**本 Protocol，
  **不落 runtime**，保 runtime 抽象包不变量），由**组合根**经 ``AgentRuntime.build(...)``
  ``skill_resolver=`` 注入（默认 :class:`NullSkillResolver`，向后兼容）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import ResolvedSkill, SkillQuery

__all__ = ["SkillResolver", "NullSkillResolver"]


@runtime_checkable
class SkillResolver(Protocol):
    """技能解析器（RP-01）。"""

    def resolve(self, query: SkillQuery) -> list[ResolvedSkill]:
        """按查询解析可用技能（无匹配返回空列表）。

        Raises:
            DomainError: 解析失败（``INTERNAL_ERROR``）。
        """
        ...


class NullSkillResolver:
    """空实现（Phase 1）：恒返回空列表（可装配，不抛错）。"""

    def resolve(self, query: SkillQuery) -> list[ResolvedSkill]:
        """恒返回空列表。"""
        return []
