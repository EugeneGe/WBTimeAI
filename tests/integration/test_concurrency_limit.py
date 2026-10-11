"""并发约束集成测试（T1-24 / ``N-P1-02``）。

同 Conversation 活跃 Run 超限 → 拒绝新 Run（``CONFLICT`` → 409，**非静默排队**）；
原子性由注入的 SQL 仓储 ``add_guarded`` 保证（Runtime 零 SQL）。
"""

from __future__ import annotations

import pytest
from astra_conversation import SqlAgentRunRepository
from astra_core import DomainError, ErrorCode
from astra_domain import RUN_STATUS_RUNNING, AgentRun, ConcurrencyConfig
from astra_runtime import ConcurrencyController


def test_conflict_when_active_run_limit_exceeded(session_factory) -> None:  # noqa: ANN001
    run_repo = SqlAgentRunRepository(session_factory)
    controller = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=1))

    # 预置一个活跃 Run。
    run_repo.add(
        AgentRun(
            conversation_id="c1", agent_id="a1", agent_version_id="v1", status=RUN_STATUS_RUNNING
        )
    )
    second = AgentRun(conversation_id="c1", agent_id="a1", agent_version_id="v1")

    with pytest.raises(DomainError) as excinfo:
        controller.guard_run_creation(run_repo, second)
    assert excinfo.value.code is ErrorCode.CONFLICT

    # 不同 Conversation 不受影响。
    other = controller.guard_run_creation(
        run_repo, AgentRun(conversation_id="c2", agent_id="a1", agent_version_id="v1")
    )
    assert other is not None
    assert other.conversation_id == "c2"


def test_guard_returns_run_when_within_limit(session_factory) -> None:  # noqa: ANN001
    run_repo = SqlAgentRunRepository(session_factory)
    controller = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=2))
    created = controller.guard_run_creation(
        run_repo, AgentRun(conversation_id="c9", agent_id="a1", agent_version_id="v1")
    )
    assert created.id
    assert len(run_repo.list_active_by_conversation("c9")) == 1


def test_tool_slot_semaphore() -> None:
    controller = ConcurrencyController(ConcurrencyConfig(max_parallel_tools=1))
    with controller.tool_slot():
        assert controller.max_parallel_tools == 1
    # 释放后可再次获取。
    with controller.tool_slot():
        assert True
