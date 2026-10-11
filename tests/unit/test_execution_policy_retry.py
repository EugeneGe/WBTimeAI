"""执行策略单测（T1-24 / §2.7.2）：重试 / 不重试矩阵 + ``attempt`` 新行（R-09）。

- 仅对 ``429`` / ``5xx`` / ``timeout`` 重试；
- **不重试**入参校验失败 / 权限拒绝 / 其它 4xx；
- 失败重试产生**新的 ``tool_call`` 行**（``attempt`` 递增），非覆盖。
"""

from __future__ import annotations

import random
from pathlib import Path

from astra_domain import AgentRun, ExecutionPolicy, RuntimeConfig
from astra_event import LocalEventBus
from astra_runtime import (
    ContextManager,
    EventDispatcher,
    ExecutionManager,
    ExecutionPolicyEngine,
    RuntimePermissionChecker,
    ToolExecutor,
)
from astra_runtime.model_executor import ToolCallRequest
from astra_tool import ToolContext, ToolRegistry

from tests.unit.runtime_stubs import (
    EchoTool,
    allow_tool,
    build_session_factory,
)


def _engine(max_retry: int = 2) -> ExecutionPolicyEngine:
    return ExecutionPolicyEngine(ExecutionPolicy(max_retry=max_retry))


def test_retryable_codes() -> None:
    engine = _engine()
    assert engine.is_retryable(error_code="HTTP_429") is True
    assert engine.is_retryable(error_code="HTTP_500") is True
    assert engine.is_retryable(status="503") is True
    assert engine.is_retryable(error_code="TOOL_TIMEOUT") is True


def test_non_retryable_codes() -> None:
    engine = _engine()
    assert engine.is_retryable(error_code="HTTP_400") is False
    assert engine.is_retryable(error_code="VALIDATION_ERROR") is False
    assert engine.is_retryable(error_code="PERMISSION_DENIED") is False
    assert engine.is_retryable(status="404") is False


def test_should_retry_respects_max_retry() -> None:
    engine = _engine(max_retry=2)
    assert engine.should_retry(attempt=1, error_code="HTTP_500") is True
    assert engine.should_retry(attempt=2, error_code="HTTP_500") is True
    assert engine.should_retry(attempt=3, error_code="HTTP_500") is False


def test_backoff_is_exponential_with_jitter_bounds() -> None:
    engine = _engine()
    rng = random.Random(1234)
    first = engine.backoff_ms(1, rng=rng)
    third = engine.backoff_ms(3, rng=rng)
    assert 0 <= first <= 1000
    assert 0 <= third <= 4000


def test_retry_produces_new_tool_call_rows(tmp_path: Path) -> None:
    from astra_conversation import (
        SqlAgentRunRepository,
        SqlMessageRepository,
        SqlToolCallRepository,
    )

    factory, engine = build_session_factory(tmp_path / "retry.db")
    try:
        run_repo = SqlAgentRunRepository(factory)
        tool_repo = SqlToolCallRepository(factory)
        run = run_repo.add(AgentRun(conversation_id="c1", agent_id="a1", agent_version_id="v1"))
        registry = ToolRegistry()
        registry.register(
            "flaky", EchoTool(name="flaky", ok=False, error="server error", error_code="HTTP_500")
        )
        tool_executor = ToolExecutor(
            tool_registry=registry,
            permission_checker=RuntimePermissionChecker(allow_tool("flaky")),
            tool_timeout_ms=10**9,
        )
        dispatcher = EventDispatcher(event_bus=LocalEventBus())
        dispatcher.bind(run.id)
        manager = ExecutionManager(
            run_repository=run_repo,
            message_repository=SqlMessageRepository(factory),
            tool_call_repository=tool_repo,
            model_executor=None,  # type: ignore[arg-type] - 本路径不调用模型
            tool_executor=tool_executor,
            context_manager=ContextManager(),
            event_dispatcher=dispatcher,
            execution_policy=_engine(max_retry=2),
        )
        tool_call = manager._execute_tool_with_retry(  # noqa: SLF001 - 直接验证重试语义
            run=run,
            ctx=None,  # type: ignore[arg-type]
            tool_ctx=ToolContext(),
            request=ToolCallRequest("flaky", {"x": 1}),
            runtime_config=RuntimeConfig(),
            sessions=[],
        )
        rows = tool_repo.list_by_run(run.id)
        assert [row.attempt for row in rows] == [1, 2, 3]
        assert all(row.status == "FAILED" for row in rows)
        assert tool_call.attempt == 3
    finally:
        engine.dispose()
