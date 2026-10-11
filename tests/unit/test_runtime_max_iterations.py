"""ReAct 迭代上界单测（T1-23 / ``U-P1-24``）。

``max_iterations=N`` + fake model 恒返工具调用 → 迭代次数 == N，终态 ``FAILED``，
``error_type == MAX_ITERATIONS``。
"""

from __future__ import annotations

from pathlib import Path

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
    StubModelProvider,
    allow_tool,
    build_model_router,
    build_session_factory,
    make_agent_version,
    tool_call_content,
)


def test_max_iterations_reached(tmp_path: Path) -> None:
    factory, engine = build_session_factory(tmp_path / "maxiter.db")
    try:
        registry = ToolRegistry()
        registry.register("echo", EchoTool(name="echo", output="ok"))
        runtime = AgentRuntime.build(
            run_repository=SqlAgentRunRepository(factory),
            message_repository=SqlMessageRepository(factory),
            tool_call_repository=SqlToolCallRepository(factory),
            event_bus=LocalEventBus(),
            model_router=build_model_router(StubModelProvider([tool_call_content("echo")])),
            tool_registry=registry,
            permission_checker=RuntimePermissionChecker(allow_tool("echo")),
            event_repository=SqlAgentEventRepository(factory),
        )
        version = make_agent_version(max_iterations=3)
        result = runtime.run(
            RunContext(
                conversation_id="conv-1",
                agent_id="agent-1",
                agent_version=version,
                tenant_id="tenant-1",
                user_message="go",
            )
        )

        assert result.iterations == 3
        assert result.status == "FAILED"
        assert result.success is False
        assert result.error_type == str(ErrorCode.MAX_ITERATIONS)

        run = SqlAgentRunRepository(factory).get(result.run_id)
        assert run is not None
        assert run.status == "FAILED"
        assert run.error_type == "MAX_ITERATIONS"
        assert run.success is False

        events = SqlAgentEventRepository(factory).list_by_run(result.run_id)
        assert events[-1].type == "agent.failed"
        assert events[-1].payload["error_type"] == "MAX_ITERATIONS"

        # 每个迭代各产生一条 tool_call（同一工具，attempt 逐次递增）。
        rows = SqlToolCallRepository(factory).list_by_run(result.run_id)
        assert len(rows) == 3
        assert [row.attempt for row in rows] == [1, 2, 3]
    finally:
        engine.dispose()
