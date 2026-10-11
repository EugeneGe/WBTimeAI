"""Run 遥测集成测试（T1-23 / ``I-P1-29``）。

成功 / 模型失败 / 工具失败三种情形均写 ``error_type`` / ``tool_error_count`` /
``duration_ms`` / ``success``，且 ``agent_run`` 终态与 status 一致。
"""

from __future__ import annotations

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_core import ErrorCode
from astra_event import LocalEventBus
from astra_runtime import AgentRuntime, RunContext, RuntimePermissionChecker
from astra_tool import ToolRegistry

from tests.unit.runtime_stubs import (
    EchoTool,
    ErrorModelProvider,
    StubModelProvider,
    allow_tool,
    build_model_router,
    make_agent_version,
    tool_call_content,
)


def _build_runtime(factory, provider, registry) -> AgentRuntime:  # noqa: ANN001
    return AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_bus=LocalEventBus(),
        model_router=build_model_router(provider),
        tool_registry=registry,
        permission_checker=(
            RuntimePermissionChecker(allow_tool("echo")) if "echo" in registry.names() else None
        ),
        event_repository=SqlAgentEventRepository(factory),
    )


def _run(runtime: AgentRuntime, *, max_iterations: int = 5):  # noqa: ANN201
    return runtime.run(
        RunContext(
            conversation_id="conv-tel",
            agent_id="agent-1",
            agent_version=make_agent_version(max_iterations=max_iterations),
            tenant_id="tenant-1",
            user_message="hi",
        )
    )


def test_success_telemetry(session_factory) -> None:  # noqa: ANN001
    registry = ToolRegistry()
    registry.register("echo", EchoTool(name="echo", output="ok"))
    runtime = _build_runtime(session_factory, StubModelProvider(["final"]), registry)
    result = _run(runtime)

    assert result.status == "SUCCESS"
    assert result.success is True
    assert result.error_type is None
    assert result.duration_ms >= 0
    assert result.tool_error_count == 0

    run = SqlAgentRunRepository(session_factory).get(result.run_id)
    assert run is not None
    assert run.status == "SUCCESS"
    assert run.success is True
    assert run.error_type is None
    assert run.duration_ms is not None
    assert run.tool_error_count == 0


def test_tool_failure_telemetry(session_factory) -> None:  # noqa: ANN001
    registry = ToolRegistry()
    registry.register(
        "echo",
        EchoTool(
            name="echo", ok=False, error="bad input", error_code=str(ErrorCode.VALIDATION_ERROR)
        ),
    )
    runtime = _build_runtime(
        session_factory,
        StubModelProvider([tool_call_content("echo"), "recovered"]),
        registry,
    )
    result = _run(runtime)

    # 工具失败但 Run 可继续（模型给出最终答复）→ Run 成功，tool_error_count=1。
    assert result.status == "SUCCESS"
    assert result.success is True
    assert result.error_type is None
    assert result.tool_error_count == 1

    run = SqlAgentRunRepository(session_factory).get(result.run_id)
    assert run is not None
    assert run.tool_error_count == 1
    assert run.duration_ms is not None


def test_model_failure_telemetry(session_factory) -> None:  # noqa: ANN001
    runtime = _build_runtime(session_factory, ErrorModelProvider(), ToolRegistry())
    result = _run(runtime)

    assert result.status == "FAILED"
    assert result.success is False
    assert result.error_type == str(ErrorCode.INTERNAL_ERROR)

    run = SqlAgentRunRepository(session_factory).get(result.run_id)
    assert run is not None
    assert run.status == "FAILED"
    assert run.success is False
    assert run.error_type == "INTERNAL_ERROR"
    assert run.duration_ms is not None
