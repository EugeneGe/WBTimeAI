"""``ContextManager``（组装 messages；设计 §2.7.1 / W2 裁定 R5 §5.3）。

把 ``system_prompt`` + 历史消息（含工具结果）组装为喂给模型的 :class:`ChatMessage` 序列，
并对**工具输出副本**按 ``tool_output_max_chars`` 截断，最后经 :func:`apply_budget` 做
预算分配 + ``TRUNCATE_OLDEST`` 溢出。

🔴 **签名冻结**（R5 §5.3）：本管理器**不感知** Skill——Skill 指令段由 ``PromptManager.
   compose_system_prompt`` 预先合成，调用方传入**已合成**的 ``system_prompt`` 字面量，
   ``build(*, system_prompt, history)`` 一字不变。
"""

from __future__ import annotations

from collections.abc import Sequence

from astra_domain import ContextConfig
from astra_model import ChatMessage

from .context_budget import TokenCounter, apply_budget, count_tokens, truncate_text

__all__ = ["ContextManager"]


class ContextManager:
    """上下文组装器（system_prompt + 历史 + 工具结果 → messages）。"""

    def __init__(
        self,
        *,
        context_config: ContextConfig | None = None,
        count_tokens_fn: TokenCounter | None = None,
    ) -> None:
        self._config = context_config or ContextConfig()
        self._count = count_tokens_fn or count_tokens

    @property
    def context_config(self) -> ContextConfig:
        """当前上下文配置段。"""
        return self._config

    def truncate_tool_output(self, text: str) -> str:
        """按 ``tool_output_max_chars`` 截断工具输出（附截断标记）。"""
        truncated, _ = truncate_text(text, self._config.tool_output_max_chars)
        return truncated

    def build(
        self,
        *,
        system_prompt: str,
        history: Sequence[ChatMessage],
    ) -> list[ChatMessage]:
        """组装并裁剪喂给模型的消息序列。

        Args:
            system_prompt: 系统提示词（来自明确 ``agent_version``）。
            history: 历史消息（user / assistant / tool）。

        Returns:
            预算内的消息列表（首条为 system）。

        Raises:
            DomainError: 超窗仍不满足（``CONTEXT_LENGTH_EXCEEDED``）。
        """
        messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
        for message in history:
            if message.role == "tool":
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=self.truncate_tool_output(message.content),
                        name=message.name,
                        metadata=dict(message.metadata),
                    )
                )
            else:
                messages.append(message)
        return apply_budget(
            messages,
            max_input_tokens=self._config.max_input_tokens,
            reserve_output_tokens=self._config.reserve_output_tokens,
            counter=self._count,
            overflow_strategy=self._config.overflow_strategy,
        )
