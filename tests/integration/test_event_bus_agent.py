"""EventBus × Agent 事件集成测试（T1-21 / ``I-P1-08``）。

7 类产出事件经 ``LocalEventBus`` 发布（订阅者收到）且**批量落库**可回放；
``mcp_call.*`` 定义但不产出。
"""

from __future__ import annotations

from astra_conversation import SqlAgentEventRepository
from astra_event import (
    AgentCompleted,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    LocalEventBus,
    ToolCallCompleted,
    ToolCallStarted,
)
from astra_runtime import EventDispatcher

PRODUCED_TYPES = [
    "agent.started",
    "agent.thinking",
    "tool_call.started",
    "tool_call.completed",
    "agent.message",
    "agent.completed",
    "agent.failed",
]


def _emit_produced(dispatcher: EventDispatcher, run_id: str) -> None:
    dispatcher.emit(AgentStarted.create(run_id=run_id, agent_id="a1"), run_id=run_id)
    dispatcher.emit(AgentThinking.create(run_id=run_id, iteration=1), run_id=run_id)
    dispatcher.emit(
        ToolCallStarted.create(run_id=run_id, tool_call_id="tc1", tool_name="echo"),
        run_id=run_id,
    )
    dispatcher.emit(
        ToolCallCompleted.create(
            run_id=run_id, tool_call_id="tc1", tool_name="echo", status="SUCCESS"
        ),
        run_id=run_id,
    )
    dispatcher.emit(
        AgentMessage.create(run_id=run_id, message_id="m1", role="assistant"), run_id=run_id
    )
    dispatcher.emit(AgentCompleted.create(run_id=run_id), run_id=run_id)


def test_produced_events_published_and_persisted(session_factory) -> None:  # noqa: ANN001
    bus = LocalEventBus()
    received: list[str] = []
    for event_type in PRODUCED_TYPES:
        bus.subscribe(event_type, lambda event: received.append(event.type))

    dispatcher = EventDispatcher(
        event_bus=bus, event_repository=SqlAgentEventRepository(session_factory)
    )
    dispatcher.bind("run-1", trace_id="trace-1")
    _emit_produced(dispatcher, "run-1")
    # 追加一个失败事件（第 7 类）。
    from astra_event import AgentFailed

    dispatcher.emit(AgentFailed.create(run_id="run-1", error_type="MAX_ITERATIONS"), run_id="run-1")

    assert received == PRODUCED_TYPES
    assert dispatcher.pending == 7

    persisted = dispatcher.flush()
    assert [event.type for event in persisted] == PRODUCED_TYPES
    assert dispatcher.pending == 0

    # 落库可回放（seq 递增）。
    stored = SqlAgentEventRepository(session_factory).list_by_run("run-1")
    assert [event.type for event in stored] == PRODUCED_TYPES
    assert [event.seq for event in stored] == list(range(1, 8))


def test_mcp_events_not_produced(session_factory) -> None:  # noqa: ANN001
    repo = SqlAgentEventRepository(session_factory)
    dispatcher = EventDispatcher(event_bus=LocalEventBus(), event_repository=repo)
    dispatcher.bind("run-mcp")
    _emit_produced(dispatcher, "run-mcp")
    dispatcher.flush()
    stored = repo.list_by_run("run-mcp")
    assert all(not event.type.startswith("mcp_call.") for event in stored)
