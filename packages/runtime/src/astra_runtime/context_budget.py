"""上下文预算与溢出策略（设计 §2.7.1；W5 / T1-24）。

- :func:`count_tokens` 默认估算（字符数 / 4）；
- :func:`truncate_text` 工具输出截断（附 ``[...truncated N chars]`` 标记）——**仅作用于喂模型的
  消息副本**，``tool_call.output`` 仍落完整原文（§5 #1）；
- :func:`apply_budget` 预算分配 + ``TRUNCATE_OLDEST`` 溢出（``system_prompt`` 永不淘汰；
  超窗仍不满足 → ``DomainError(CONTEXT_LENGTH_EXCEEDED)``）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

from astra_domain.constants import DEFAULT_MAX_INPUT_TOKENS, DEFAULT_RESERVE_OUTPUT_TOKENS
from astra_model import ChatMessage

from .errors import context_length_exceeded_error

__all__ = [
    "TokenCounter",
    "TruncationResult",
    "count_tokens",
    "truncate_text",
    "messages_token_count",
    "apply_budget",
]

#: token 计数器类型（默认 :func:`count_tokens`）。
TokenCounter = Callable[[str], int]

#: 截断标记模板。
TRUNCATION_MARKER = "[...truncated {n} chars]"


class TruncationResult(NamedTuple):
    """截断结果（``text`` 为截断后文本，``dropped_chars`` 为丢弃字符数）。"""

    text: str
    dropped_chars: int


def count_tokens(text: str) -> int:
    """默认 token 估算（字符数 / 4，向上至少 1）。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def truncate_text(text: str, max_chars: int) -> TruncationResult:
    """按 ``max_chars`` 截断文本，附 ``[...truncated N chars]`` 标记。

    Args:
        text: 原文。
        max_chars: 最大保留字符数（``<=0`` 视为全部丢弃）。

    Returns:
        :class:`TruncationResult`（``text`` 已含标记；``dropped_chars`` 为丢弃字符数）。
    """
    if max_chars is None or max_chars < 0:
        max_chars = 0
    if len(text) <= max_chars:
        return TruncationResult(text, 0)
    keep = max_chars
    dropped = len(text) - keep
    marker = TRUNCATION_MARKER.format(n=dropped)
    return TruncationResult(text[:keep] + marker, dropped)


def messages_token_count(messages: Sequence[ChatMessage], counter: TokenCounter) -> int:
    """统计消息序列的 token 数（含每条约 4 token 的角色开销）。"""
    total = 0
    for message in messages:
        total += counter(message.content) + 4
    return total


def apply_budget(
    messages: list[ChatMessage],
    *,
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    reserve_output_tokens: int = DEFAULT_RESERVE_OUTPUT_TOKENS,
    counter: TokenCounter = count_tokens,
    overflow_strategy: str = "TRUNCATE_OLDEST",
) -> list[ChatMessage]:
    """预算分配 + ``TRUNCATE_OLDEST`` 溢出策略（设计 §2.7.1）。

    ``system`` 消息**永不淘汰**；从最旧的**非 system** 消息开始淘汰，直至满足预算。
    若淘汰全部非 system 消息后仍超窗 → 抛 ``DomainError(CONTEXT_LENGTH_EXCEEDED)``。

    Args:
        messages: 待发送消息（首条通常为 system）。
        max_input_tokens: 可用输入 token 预算。
        reserve_output_tokens: 为输出保留的 token。
        counter: token 计数器。
        overflow_strategy: 溢出策略（Phase 1 仅 ``TRUNCATE_OLDEST``）。

    Returns:
        预算内的消息列表（保持原相对顺序）。

    Raises:
        DomainError: 超窗仍不满足（``CONTEXT_LENGTH_EXCEEDED``）。
    """
    budget = int(max_input_tokens) - int(reserve_output_tokens)
    if budget <= 0:
        raise context_length_exceeded_error(
            "上下文预算非正（max_input_tokens - reserve_output_tokens <= 0）",
            max_input_tokens=max_input_tokens,
            reserve_output_tokens=reserve_output_tokens,
        )
    if overflow_strategy != "TRUNCATE_OLDEST":
        # Phase 1 仅实现 TRUNCATE_OLDEST；其它策略不静默降级。
        raise context_length_exceeded_error(
            f"不支持的溢出策略：{overflow_strategy}",
            overflow_strategy=overflow_strategy,
        )

    system_messages = [message for message in messages if message.role == "system"]
    others = [message for message in messages if message.role != "system"]
    if messages_token_count(system_messages, counter) > budget:
        raise context_length_exceeded_error(
            "system_prompt 自身超出上下文预算（system 永不淘汰）",
            system_tokens=messages_token_count(system_messages, counter),
            budget=budget,
        )

    kept_reversed: list[ChatMessage] = []
    current = messages_token_count(system_messages, counter)
    for message in reversed(others):
        cost = counter(message.content) + 4
        if current + cost <= budget:
            kept_reversed.append(message)
            current += cost
        else:
            break
    kept = list(reversed(kept_reversed))
    return [*system_messages, *kept]
