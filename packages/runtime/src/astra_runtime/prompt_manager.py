"""``PromptManager``（装载 / 合成 ``system_prompt``；设计 §2.7 / W2 裁定 R5）。

- :meth:`PromptManager.load_system_prompt`：返回明确 ``agent_version`` 的 ``system_prompt``；
- :meth:`PromptManager.compose_system_prompt`（W2 新增）：**Agent ``system_prompt`` 为主 +
  Skill 指令按绑定顺序追加**（默认 ``separator="\\n\\n"``），合成策略数据驱动
  （``agent_version.runtime_config.prompt`` = :class:`~astra_domain.PromptMergeConfig`）；
- :meth:`PromptManager.build_system_message`：构造首条 system 消息。

🔴 **签名冻结**：``ContextManager.build(*, system_prompt, history)`` 不变（R5 §5.2）——
   合成**只**在 ``PromptManager`` 完成，调用方传入**已合成**的 ``system_prompt``。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from astra_domain import AgentVersion, ResolvedSkill, RuntimeConfig

__all__ = ["PromptManager"]


class PromptManager:
    """系统提示词装载 / 合成器（无状态）。"""

    def load_system_prompt(self, agent_version: AgentVersion) -> str:
        """返回明确 ``agent_version`` 的 ``system_prompt``。"""
        return agent_version.system_prompt

    def compose_system_prompt(
        self,
        agent_version: AgentVersion,
        resolved_skills: Sequence[ResolvedSkill],
    ) -> str:
        """合成生效 ``system_prompt``（Agent 为主 + Skill 指令按绑定顺序追加）。

        合成策略取自 ``agent_version.runtime_config.prompt``
        （:class:`~astra_domain.PromptMergeConfig`；缺省 ``skill_order="after"`` /
        ``skill_separator="\\n\\n"``）。**无 Skill（或全部内容为空）时**原样返回
        ``agent_version.system_prompt``（向后兼容）。

        Args:
            agent_version: 明确版本（提供 Agent 主提示词与合成策略）。
            resolved_skills: 已解析技能（按**绑定顺序**；``content`` 为空者跳过）。

        Returns:
            合成后的 ``system_prompt``。
        """
        prompt = self.load_system_prompt(agent_version)
        blocks = [skill.content for skill in resolved_skills if skill.content]
        if not blocks:
            return prompt
        config = _coerce_runtime_config(agent_version.runtime_config).prompt
        separator = config.skill_separator
        parts = [*blocks, prompt] if config.skill_order == "before" else [prompt, *blocks]
        return separator.join(parts)

    def build_system_message(self, agent_version: AgentVersion):
        """构造首条 system :class:`~astra_model.ChatMessage`。"""
        from astra_model import ChatMessage

        return ChatMessage(role="system", content=self.load_system_prompt(agent_version))


def _coerce_runtime_config(value: Any) -> RuntimeConfig:
    """把 ``agent_version.runtime_config``（dict / RuntimeConfig）归一化为 ``RuntimeConfig``。"""
    if isinstance(value, RuntimeConfig):
        return value
    if isinstance(value, dict):
        return RuntimeConfig.from_dict(value)
    return RuntimeConfig()
