"""取消 / 超时 → 沙箱回收集成测试（T1-24 / ``I-P1-23``）。

失败 / 取消 / 超时须调用 ``SandboxProvider.destroy()``（幂等），且回收落在 ``≤30s`` 窗口内。
"""

from __future__ import annotations

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_event import LocalEventBus
from astra_runtime import (
    AgentRuntime,
    CancellationManager,
    RunContext,
    RuntimePermissionChecker,
)
from astra_tool import ToolRegistry

from tests.unit.runtime_stubs import (
    EchoTool,
    FakeSandboxProvider,
    StubModelProvider,
    allow_tool,
    build_model_router,
    make_agent_version,
    tool_call_content,
)


def _build_runtime(factory, provider, registry, sandbox) -> AgentRuntime:  # noqa: ANN001
    return AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_bus=LocalEventBus(),
        model_router=build_model_router(provider),
        tool_registry=registry,
        permission_checker=RuntimePermissionChecker(allow_tool("sbx")),
        sandbox_provider=sandbox,
        event_repository=SqlAgentEventRepository(factory),
    )


def test_failure_destroys_sandbox(session_factory) -> None:  # noqa: ANN001
    sandbox = FakeSandboxProvider()
    registry = ToolRegistry()
    registry.register("sbx", EchoTool(name="sbx", requires_sandbox=True))
    runtime = _build_runtime(
        session_factory,
        StubModelProvider([tool_call_content("sbx")]),  # 恒返工具调用 → 迭代耗尽失败
        registry,
        sandbox,
    )
    result = runtime.run(
        RunContext(
            conversation_id="conv-cancel",
            agent_id="agent-1",
            agent_version=make_agent_version(max_iterations=2),
            tenant_id="tenant-1",
            user_message="go",
        )
    )
    assert result.status == "FAILED"
    assert sandbox.created >= 1
    assert sandbox.destroyed >= 1


def test_run_timeout_marks_failed(session_factory) -> None:  # noqa: ANN001
    sandbox = FakeSandboxProvider()
    runtime = _build_runtime(session_factory, StubModelProvider(["never"]), ToolRegistry(), sandbox)
    result = runtime.run(
        RunContext(
            conversation_id="conv-timeout",
            agent_id="agent-1",
            agent_version=make_agent_version(
                max_iterations=5, runtime_overrides={"execution": {"run_timeout_ms": 0}}
            ),
            tenant_id="tenant-1",
            user_message="go",
        )
    )
    assert result.status == "FAILED"
    assert result.success is False
    assert result.error_type == "RUN_TIMEOUT"

    run = SqlAgentRunRepository(session_factory).get(result.run_id)
    assert run is not None
    assert run.status == "FAILED"
    assert run.error_type == "RUN_TIMEOUT"


def test_cancellation_manager_idempotent_and_window() -> None:
    sandbox = FakeSandboxProvider()
    manager = CancellationManager(sandbox_provider=sandbox)
    session = sandbox.create_session(run_id="r1")
    assert manager.destroy_session(session) is True
    # 幂等：无会话 / 无 provider 时静默。
    assert manager.destroy_session(None) is False
    # 回收窗口：≤30s。
    assert manager.within_reclaim_window(elapsed_seconds=0) is True
    assert manager.within_reclaim_window(elapsed_seconds=30) is True
    assert manager.within_reclaim_window(elapsed_seconds=31) is False
