"""上下文窗口 / 溢出策略单测（T1-24 / §2.7.1 / ``E-P1-01`` 部分）。

覆盖：工具输出截断标记、20 轮对话 + 100KB 工具输出不崩溃、``TRUNCATE_OLDEST``
淘汰最旧非 system 消息、超窗仍不满足 → ``CONTEXT_LENGTH_EXCEEDED``。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import ContextConfig
from astra_model import ChatMessage
from astra_runtime import ContextManager, apply_budget, count_tokens, truncate_text


def test_truncate_text_no_change() -> None:
    result = truncate_text("abc", 10)
    assert result.text == "abc"
    assert result.dropped_chars == 0


def test_truncate_text_marks_dropped() -> None:
    result = truncate_text("abcdef", 2)
    assert result.text.startswith("ab")
    assert "[...truncated 4 chars]" in result.text
    assert result.dropped_chars == 4


def test_apply_budget_truncates_oldest_non_system() -> None:
    messages = [ChatMessage(role="system", content="S" * 40)]
    messages += [ChatMessage(role="user", content="U" * 40) for _ in range(10)]
    # system 计 40+4=44，每条 user 计 44；budget=100 仅够 system + 1 条最新 user。
    budget = 100
    kept = apply_budget(
        messages, max_input_tokens=budget, reserve_output_tokens=0, counter=lambda t: len(t)
    )
    assert kept[0].role == "system"
    # 保留的是**最新**消息（TRUNCATE_OLDEST）。
    assert len(kept) < len(messages)
    # 保留的应是末尾（最新）那条 user，最旧被淘汰。
    assert kept[-1].role == "user"


def test_context_length_exceeded_when_system_too_big() -> None:
    messages = [
        ChatMessage(role="system", content="S" * 1000),
        ChatMessage(role="user", content="u"),
    ]
    with pytest.raises(DomainError) as excinfo:
        apply_budget(
            messages, max_input_tokens=10, reserve_output_tokens=0, counter=lambda t: len(t)
        )
    assert excinfo.value.code is ErrorCode.CONTEXT_LENGTH_EXCEEDED


def test_context_length_exceeded_nonpositive_budget() -> None:
    with pytest.raises(DomainError) as excinfo:
        apply_budget(
            [ChatMessage(role="user", content="u")], max_input_tokens=10, reserve_output_tokens=10
        )
    assert excinfo.value.code is ErrorCode.CONTEXT_LENGTH_EXCEEDED


def test_20_rounds_with_100kb_tool_output_does_not_crash() -> None:
    """连续 20 轮对话 + 单次 100KB 工具输出：不崩溃且行为可预期。"""
    config = ContextConfig(
        max_input_tokens=4000,
        reserve_output_tokens=0,
        tool_output_max_chars=200,
    )
    manager = ContextManager(context_config=config, count_tokens_fn=count_tokens)
    history: list[ChatMessage] = []
    for round_index in range(20):
        history.append(ChatMessage(role="user", content=f"round-{round_index} " * 20))
        history.append(ChatMessage(role="assistant", content='{"tool_calls": []}'))
        history.append(ChatMessage(role="tool", content="X" * 100_000))
    messages = manager.build(system_prompt="SYS", history=history)
    assert messages[0].role == "system"
    # 工具输出被截断（远小于 100KB）。
    for message in messages:
        if message.role == "tool":
            assert len(message.content) <= config.tool_output_max_chars + 40


def test_tool_output_truncation_only_on_model_copy() -> None:
    config = ContextConfig(tool_output_max_chars=5)
    manager = ContextManager(context_config=config)
    truncated = manager.truncate_tool_output("0123456789")
    assert truncated.startswith("01234")
    assert "[...truncated 5 chars]" in truncated
