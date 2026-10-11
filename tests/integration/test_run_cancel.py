"""Run 取消集成测试（W6 / T1-28；设计 §2.6 / §2.9）。

- ``POST /runs/{id}/cancel``：置取消信号 + 终态 ``CANCELLED`` + 同步 ``task``（如有）；
- ``GET /runs/{id}`` 详情 / 不存在 → 404。

为稳定构造「活跃 Run」，本测试直接经 ``SqlAgentRunRepository`` 落一条 ``RUNNING`` Run，
再经 API 取消（避免与 INLINE 同步执行竞争）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from astra_common.time import utcnow
from astra_conversation import SqlAgentRunRepository
from astra_domain import RUN_STATUS_CANCELLED, RUN_STATUS_RUNNING, AgentRun


class _FakeSandboxSession:
    """最小沙箱会话（记录状态，供回收断言）。"""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.status = "RUNNING"


class _FakeSandboxRepository:
    """内存沙箱会话仓储（实现 ``SandboxSessionRepository`` 所需子集）。"""

    def __init__(self, sessions: list[_FakeSandboxSession]) -> None:
        self._sessions = sessions
        self.updates: list[_FakeSandboxSession] = []

    def list_by_run(self, run_id: str) -> list[_FakeSandboxSession]:
        return list(self._sessions)

    def update(self, session: _FakeSandboxSession) -> _FakeSandboxSession:
        self.updates.append(session)
        return session


class _FakeSandboxProvider:
    """记录 ``destroy`` 调用的最小沙箱提供方。"""

    def __init__(self) -> None:
        self.destroyed: list[str] = []

    def destroy(self, session: _FakeSandboxSession) -> None:
        self.destroyed.append(session.id)


def _seed_running_run(session_factory: Any, *, run_id: str = "run-cancel-1") -> str:
    """落一条 ``RUNNING`` Run（无挂靠 task）。"""
    repository = SqlAgentRunRepository(session_factory)
    repository.add(
        AgentRun(
            id=run_id,
            tenant_id="tenant-cancel",
            agent_id="agent-cancel",
            agent_version_id="version-cancel",
            conversation_id="conversation-cancel",
            user_id="user-cancel",
            status=RUN_STATUS_RUNNING,
            started_at=utcnow(),
        )
    )
    return run_id


def test_get_run_detail(client: Any, auth_headers: dict[str, str], session_factory: Any) -> None:
    """``GET /runs/{id}`` 返回 Run 详情。"""
    run_id = _seed_running_run(session_factory)
    response = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["id"] == run_id
    assert response.json()["data"]["status"] == RUN_STATUS_RUNNING


def test_cancel_run_sets_cancelled(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``POST /runs/{id}/cancel`` → 200 + ``CANCELLED`` + ``success=false``。"""
    run_id = _seed_running_run(session_factory)
    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == RUN_STATUS_CANCELLED
    assert data["success"] is False
    assert data["error_type"] == "CANCELLED"


def test_cancel_missing_run_returns_404(client: Any, auth_headers: dict[str, str]) -> None:
    """取消不存在的 Run → 404。"""
    response = client.post("/api/v1/runs/does-not-exist/cancel", headers=auth_headers)
    assert response.status_code == 404, response.text


def test_get_missing_run_returns_404(client: Any, auth_headers: dict[str, str]) -> None:
    """获取不存在的 Run → 404。"""
    response = client.get("/api/v1/runs/does-not-exist", headers=auth_headers)
    assert response.status_code == 404, response.text


# -- 断连即取消全链路（W6 修复回归：固化 QA 补充验证） ------------------------
#
# stream 提前关闭 → deps.cancel → AgentRunService.cancel →
#   run.status=CANCELLED + task.finish("CANCELLED") + 沙箱 destroy/STOPPED。


class _FakeRuns:
    """内存 Run 仓储（``get`` / ``update``）。"""

    def __init__(self, run: AgentRun) -> None:
        self._runs = {run.id: run}

    def get(self, run_id: str) -> AgentRun | None:
        return self._runs.get(run_id)

    def update(self, run: AgentRun) -> AgentRun:
        self._runs[run.id] = run
        return run


class _FakeAgents:
    """最小 Agent 服务（返回 stub 版本）。"""

    def get_agent(self, agent_id: str) -> Any:
        return SimpleNamespace(id=agent_id, tenant_id="t", current_version_id="v")

    def load_version(self, agent: Any, version_id: Any) -> Any:
        return SimpleNamespace(id=version_id or "v", model_config={}, runtime_config={})


class _BlockingRuntime:
    """阻塞式 Runtime：直到取消探针置位才返回 ``CANCELLED``（模拟每轮检查）。"""

    def run(self, ctx: Any) -> Any:
        import time

        from astra_runtime import RunResult

        while not (ctx.should_cancel is not None and ctx.should_cancel()):
            time.sleep(0.005)
        ctx.run.status = RUN_STATUS_CANCELLED
        return RunResult(
            run_id=ctx.run.id,
            status=RUN_STATUS_CANCELLED,
            success=False,
            error_type="CANCELLED",
            duration_ms=1,
            tool_error_count=0,
            iterations=0,
        )


class _SpyRunService:
    """记录 ``finish`` 调用的最小 ``RunService``。"""

    def __init__(self) -> None:
        self.finished: list[tuple[str, str]] = []

    def create_for_run(self, run: AgentRun, **kwargs: Any) -> Any:
        return None

    def finish(self, run: AgentRun, status: str, **kwargs: Any) -> Any:
        self.finished.append((run.id, status))
        return None

    def get_for_run(self, run: AgentRun) -> Any:
        return None


def test_stream_disconnect_cancels_run_task_and_sandbox() -> None:
    """早期关闭 SSE 生成器 → run/task=CANCELLED + 沙箱 destroy/STOPPED（I-P1-23）。"""
    from astra_api.sse.stream import StreamDeps, stream_run
    from astra_application import AgentRunService
    from astra_event import LocalEventBus

    run = AgentRun(
        id="run-disconnect",
        tenant_id="t",
        agent_id="a",
        agent_version_id="v",
        conversation_id="c",
        user_id="u",
        status=RUN_STATUS_RUNNING,
        started_at=utcnow(),
    )
    runs = _FakeRuns(run)
    sandbox_repository = _FakeSandboxRepository([_FakeSandboxSession("sbx-dc")])
    sandbox_provider = _FakeSandboxProvider()
    run_service = _SpyRunService()

    service = AgentRunService(
        agents=_FakeAgents(),
        runs=runs,
        runtime=_BlockingRuntime(),
        run_service=run_service,
        sandbox_sessions=sandbox_repository,
        sandbox_provider=sandbox_provider,
        events=None,
    )

    bus = LocalEventBus()
    deps = StreamDeps(
        event_bus=bus,
        execute=service.execute,
        list_events=lambda run_id, last: [SimpleNamespace(seq=1, type="agent.started", payload={})],
        cancel=service.cancel,
        run_status=service.status,
    )

    async def scenario() -> None:
        generator = stream_run(
            deps=deps, run_id="run-disconnect", heartbeat_seconds=5.0, start_execution=True
        )
        await generator.__anext__()  # 回放帧
        await generator.aclose()  # 提前断连 → finally → deps.cancel

    asyncio.run(scenario())

    current = runs.get("run-disconnect")
    assert current is not None
    assert current.status == RUN_STATUS_CANCELLED
    assert ("run-disconnect", RUN_STATUS_CANCELLED) in run_service.finished, "task 未同步 CANCELLED"
    assert sandbox_provider.destroyed == ["sbx-dc"], "沙箱未 destroy"
    assert [session.status for session in sandbox_repository.updates] == ["STOPPED"]
