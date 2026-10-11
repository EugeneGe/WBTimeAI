"""Conversation 组回放集成测试（T1-21 / ``I-P1-06``）。

由 ``agent_event(seq)`` + ``tool_call`` + ``message`` 重放出 ``(role, content)`` 序列
== golden 快照；断言 ``seq`` 严格递增且可按 ``Last-Event-ID`` 续传。
"""

from __future__ import annotations

from astra_conversation import build_conversation_services

GOLDEN_ROLES = ["user", "assistant", "tool", "assistant"]
GOLDEN_EVENT_TYPES = [
    "agent.started",
    "agent.thinking",
    "agent.message",
    "tool_call.started",
    "tool_call.completed",
    "agent.message",
    "agent.completed",
]


def test_conversation_replay_matches_golden(session_factory) -> None:  # noqa: ANN001
    services = build_conversation_services(session_factory)
    conversation = services.conversation_service.create_conversation(
        tenant_id="t1", workspace_id="w1", agent_id="a1", user_id="u1", title="demo"
    )
    conversation_id = conversation.id

    # 消息（含工具调用与工具结果）。
    services.conversation_service.append_message(
        conversation_id=conversation_id, role="user", content="hello"
    )
    services.conversation_service.append_message(
        conversation_id=conversation_id,
        role="assistant",
        content='{"tool_calls": [{"name": "echo", "arguments": {"x": 1}}]}',
    )
    services.conversation_service.append_message(
        conversation_id=conversation_id, role="tool", content="echoed"
    )
    services.conversation_service.append_message(
        conversation_id=conversation_id, role="assistant", content="final answer"
    )

    # 事件（7 类经 EventBus 产出，落库 seq 递增）。
    run_id = "run-1"
    events = [
        {"type": "agent.started", "payload": {"run_id": run_id}},
        {"type": "agent.thinking", "payload": {"run_id": run_id, "iteration": 1}},
        {"type": "agent.message", "payload": {"run_id": run_id}},
        {"type": "tool_call.started", "payload": {"run_id": run_id, "tool_name": "echo"}},
        {"type": "tool_call.completed", "payload": {"run_id": run_id, "status": "SUCCESS"}},
        {"type": "agent.message", "payload": {"run_id": run_id}},
        {"type": "agent.completed", "payload": {"run_id": run_id}},
    ]
    services.conversation_service.append_event  # noqa: B018 - 引用检查
    for item in events:
        services.conversation_service.append_event(
            run_id=run_id, type=item["type"], payload=item["payload"]
        )

    # tool_call 行。
    from astra_domain import ToolCall

    services.tool_calls.add(
        ToolCall(run_id=run_id, tool_name="echo", status="SUCCESS", output={"echoed": True})
    )

    # -- 回放 ---------------------------------------------------------------
    replayed_events = services.events.list_by_run(run_id)
    assert [event.type for event in replayed_events] == GOLDEN_EVENT_TYPES
    assert [event.seq for event in replayed_events] == [1, 2, 3, 4, 5, 6, 7]

    replayed_messages = services.messages.list_by_conversation(conversation_id)
    assert [message.role for message in replayed_messages] == GOLDEN_ROLES
    assert replayed_messages[0].content == "hello"

    replayed_tool_calls = services.tool_calls.list_by_run(run_id)
    assert [tc.tool_name for tc in replayed_tool_calls] == ["echo"]

    # -- Last-Event-ID 续传 ------------------------------------------------
    after = services.events.list_after_seq(run_id, last_event_id=4)
    assert [event.seq for event in after] == [5, 6, 7]


def test_event_add_many_batch_and_seq(session_factory) -> None:  # noqa: ANN001
    """``add_many`` 批量写入并按 ``run_id`` 补 ``seq``（§5 #13）。"""
    from astra_domain import AgentEvent

    services = build_conversation_services(session_factory)
    persisted = services.events.add_many(
        [
            AgentEvent(run_id="run-x", type="agent.started", payload={"a": 1}),
            AgentEvent(run_id="run-x", type="agent.thinking", payload={"a": 2}),
            AgentEvent(run_id="run-x", type="agent.completed", payload={"a": 3}),
        ]
    )
    assert [event.seq for event in persisted] == [1, 2, 3]
    # 再写一批：seq 继续递增。
    more = services.events.add_many(
        [AgentEvent(run_id="run-x", type="agent.failed", payload={"a": 4})]
    )
    assert more[0].seq == 4
