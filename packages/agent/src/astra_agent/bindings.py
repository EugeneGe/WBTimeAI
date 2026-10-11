"""``agent_skill`` 绑定解析（薄模块；设计 §2.3；W2 裁定 R6 §6.2）。

📌 **落点勘误（Erratum-5 / F15）**：任务卡 T2-09 写「修改 ``astra_agent/bindings.py``」，
实测**该文件不存在**——故本文件为**新增**。

本模块**零 ORM**，只编排**注入的**领域 Protocol 仓储（:class:`AgentSkillRepository`），
同构 Phase 1 ``agent_tool`` 的绑定解析；Skill 绑定**随 ``AgentVersion`` 版本化**，可回滚。
"""

from __future__ import annotations

from astra_domain import AgentSkill, AgentSkillRepository

__all__ = ["load_skill_bindings"]


def load_skill_bindings(
    agent_skill_repository: AgentSkillRepository,
    agent_version_id: str,
) -> list[AgentSkill]:
    """加载某 ``AgentVersion`` 绑定的全部 Skill（按 ``id`` 升序）。

    Args:
        agent_skill_repository: 领域 ``AgentSkillRepository``（DI 注入）。
        agent_version_id: 目标 ``AgentVersion`` 标识。

    Returns:
        该版本的 :class:`~astra_domain.AgentSkill` 绑定列表（按 ``id`` 升序，与
        ``list_by_agent_version`` 一致）。
    """
    return agent_skill_repository.list_by_agent_version(agent_version_id)
