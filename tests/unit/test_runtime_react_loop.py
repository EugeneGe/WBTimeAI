"""ReAct 循环单测（T1-23 / §2.17）。

用 stub Provider + fake Tool 跑通 ReAct 循环与事件序列；断言 run 终态、消息、tool_call
持久化；并验证**替换总线实现不改上层**（``I-P1-08`` ③）。
"""

from __future__ import annotations

from pathlib import Path

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_event import LocalEventBus
from astra_runtime import AgentRuntime, RunContext, RuntimePermissionChecker
from astra_tool import ToolRegistry

from tests.unit.runtime_stubs import (
    EchoTool,
    StubModelProvider,
    allow_tool,
    build_model_router,
    build_session_factory,
    make_agent_version,
    tool_call_content,
)

EXPECTED_EVENT_SEQUENCE = [
    "agent.started",
    "agent.thinking",
    "agent.message",
    "tool_call.started",
    "tool_call.completed",
    "agent.thinking",
    "agent.message",
    "agent.completed",
]


class RecordingBus:
    """自定义 ``EventBus`` 实现（验证总线可替换）。"""

    def __init__(self) -> None:
        self.received: list[str] = []

    def publish(self, event) -> None:  # noqa: ANN001
        self.received.append(event.type)

    def subscribe(self, event_type: str, handler) -> None:  # noqa: ANN001
        return None

    def unsubscribe(self, event_type: str, handler) -> None:  # noqa: ANN001
        return None


def _runtime(factory, bus, *, responses, tool=None):  # noqa: ANN001
    provider = StubModelProvider(responses)
    registry = ToolRegistry()
    registry.register("echo", tool or EchoTool(name="echo", output={"echoed": True}))
    return AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_bus=bus,
        model_router=build_model_router(provider),
        tool_registry=registry,
        permission_checker=RuntimePermissionChecker(allow_tool("echo")),
        event_repository=SqlAgentEventRepository(factory),
    )


def _run(runtime: AgentRuntime, version) -> object:  # noqa: ANN001
    return runtime.run(
        RunContext(
            conversation_id="conv-1",
            agent_id="agent-1",
            agent_version=version,
            tenant_id="tenant-1",
            user_message="hello",
        )
    )


def test_react_loop_success_sequence(tmp_path: Path) -> None:
    factory, engine = build_session_factory(tmp_path / "loop.db")
    try:
        bus = RecordingBus()
        version = make_agent_version(max_iterations=5)
        runtime = _runtime(
            factory,
            bus,
            responses=[tool_call_content("echo", {"x": 1}), "final answer"],
        )
        result = _run(runtime, version)

        events = SqlAgentEventRepository(factory).list_by_run(result.run_id)
        assert [event.type for event in events] == EXPECTED_EVENT_SEQUENCE
        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        assert bus.received == EXPECTED_EVENT_SEQUENCE

        assert result.status == "SUCCESS"
        assert result.success is True
        assert result.error_type is None
        assert result.duration_ms >= 0
        assert [message.role for message in result.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]

        rows = SqlToolCallRepository(factory).list_by_run(result.run_id)
        assert len(rows) == 1
        assert rows[0].tool_name == "echo"
        assert rows[0].status == "SUCCESS"
        assert rows[0].attempt == 1
        assert rows[0].output == {"echoed": True}

        run = SqlAgentRunRepository(factory).get(result.run_id)
        assert run is not None
        assert run.status == "SUCCESS"
        assert run.success is True
    finally:
        engine.dispose()


def test_bus_implementation_does_not_change_upper_layer(tmp_path: Path) -> None:
    factory, engine = build_session_factory(tmp_path / "bus.db")
    try:
        local_bus = LocalEventBus()
        version = make_agent_version(max_iterations=5)
        runtime = _runtime(factory, local_bus, responses=[tool_call_content("echo"), "done"])
        result = _run(runtime, version)
        assert result.status == "SUCCESS"
        # 落库事件序列与总线无关（上层不感知总线实现）。
        events = SqlAgentEventRepository(factory).list_by_run(result.run_id)
        assert [event.type for event in events] == EXPECTED_EVENT_SEQUENCE
    finally:
        engine.dispose()
