"""9 类 Agent 生命周期事件单测（T1-21 / ``I-P1-08``）。

仅断言 ``type`` 字符串 + ``create()`` + 序列化（``to_dict()``）；
``mcp_call.*`` **定义但不产出**（§5 #14）。
"""

from __future__ import annotations

import json

import pytest
from astra_core import DomainEvent
from astra_event import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    MCPCallCompleted,
    MCPCallStarted,
    ToolCallCompleted,
    ToolCallStarted,
)

EXPECTED_TYPES = {
    AgentStarted: "agent.started",
    AgentThinking: "agent.thinking",
    ToolCallStarted: "tool_call.started",
    ToolCallCompleted: "tool_call.completed",
    MCPCallStarted: "mcp_call.started",
    MCPCallCompleted: "mcp_call.completed",
    AgentMessage: "agent.message",
    AgentCompleted: "agent.completed",
    AgentFailed: "agent.failed",
}


def test_all_inherit_domain_event() -> None:
    for cls in EXPECTED_TYPES:
        assert issubclass(cls, DomainEvent)


@pytest.mark.parametrize(("cls", "expected"), list(EXPECTED_TYPES.items()))
def test_type_strings(cls: type, expected: str) -> None:
    assert cls.type == expected


def test_create_and_serialize() -> None:
    events = [
        AgentStarted.create(
            run_id="r1",
            agent_id="a1",
            agent_version_id="v1",
            conversation_id="c1",
            run_mode="INLINE",
        ),
        AgentThinking.create(run_id="r1", iteration=1),
        ToolCallStarted.create(
            run_id="r1", tool_call_id="tc1", tool_name="echo", attempt=1, arguments={"x": 1}
        ),
        ToolCallCompleted.create(
            run_id="r1", tool_call_id="tc1", tool_name="echo", status="SUCCESS", duration_ms=7
        ),
        MCPCallStarted.create(run_id="r1", mcp_call_id="m1", server="srv", tool_name="t"),
        MCPCallCompleted.create(run_id="r1", mcp_call_id="m1", server="srv", status="SUCCESS"),
        AgentMessage.create(run_id="r1", message_id="m1", role="assistant", content="hi"),
        AgentCompleted.create(run_id="r1", duration_ms=12, iterations=1),
        AgentFailed.create(run_id="r1", error_type="MAX_ITERATIONS", error="boom"),
    ]
    for event in events:
        payload = event.to_dict()
        assert payload["type"] == type(event).type
        assert payload["payload"]["run_id"] == "r1"
        assert payload["event_id"]
        # 可 JSON 序列化（datetime → str 兜底）。
        json.dumps(payload, default=str)


def test_mcp_events_defined_but_flagged() -> None:
    # 定义但不产出：仅断言 type 与序列化可用。
    assert MCPCallStarted.type == "mcp_call.started"
    assert MCPCallCompleted.type == "mcp_call.completed"
    assert MCPCallStarted.create(run_id="r", mcp_call_id="m", server="s").to_dict()["payload"]
