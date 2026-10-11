"""重启兜底扫描集成测试（W6 / T1-31；设计 §2.9；裁定 Q7/A31）。

覆盖：

- :meth:`RunService.recover_stale_runs`：心跳超期的 ``RUNNING`` Run → ``FAILED`` +
  ``error_type="HEARTBEAT_TIMEOUT"``；未超期 Run **不受影响**；
- **lifespan 启动**：应用启动时自动执行兜底扫描（``Settings.run_timeout_ms`` 为阈值）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from astra_common.time import utcnow
from astra_conversation import SqlAgentRunRepository, build_conversation_services
from astra_database import SqlTaskRepository
from astra_domain import RUN_STATUS_FAILED, RUN_STATUS_RUNNING, AgentRun


def _run(run_id: str, *, started_at: Any) -> AgentRun:
    return AgentRun(
        id=run_id,
        tenant_id="tenant-recovery",
        agent_id="agent-recovery",
        agent_version_id="version-recovery",
        conversation_id="conversation-recovery",
        user_id="user-recovery",
        status=RUN_STATUS_RUNNING,
        started_at=started_at,
    )


def test_recover_stale_runs_marks_failed(session_factory: Any) -> None:
    """超期 ``RUNNING`` Run 被置 ``FAILED``；未超期者不受影响。"""
    repository = SqlAgentRunRepository(session_factory)
    repository.add(_run("stale", started_at=utcnow() - timedelta(days=1)))
    repository.add(_run("fresh", started_at=utcnow()))

    services = build_conversation_services(
        session_factory, task_repository=SqlTaskRepository(session_factory)
    )
    assert services.run_service is not None
    recovered = services.run_service.recover_stale_runs(threshold_ms=60_000)

    assert [run.id for run in recovered] == ["stale"]
    stale = repository.get("stale")
    assert stale is not None
    assert stale.status == RUN_STATUS_FAILED
    assert stale.error_type == "HEARTBEAT_TIMEOUT"
    assert stale.success is False

    fresh = repository.get("fresh")
    assert fresh is not None
    assert fresh.status == RUN_STATUS_RUNNING


def test_lifespan_recovers_stale_run(tmp_path: Any, monkeypatch: Any) -> None:
    """应用 lifespan 启动即执行兜底扫描（阈值取 ``ASTRA_RUN_TIMEOUT_MS``）。"""
    from astra_config.loader import reset_settings_cache

    db_file = tmp_path / "recovery.db"
    monkeypatch.setenv("ASTRA_MODE", "local")
    monkeypatch.setenv("ASTRA_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("ASTRA_SECRET_KEY", "test-secret-key-0123456789abcdef-32bytes")
    monkeypatch.setenv("ASTRA_RUN_TIMEOUT_MS", "1")  # 阈值极小 → 立即视为超期
    monkeypatch.setenv("ASTRA_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ASTRA_LOG_FORMAT", "console")
    monkeypatch.delenv("ASTRA_CONFIG_FILE", raising=False)
    reset_settings_cache()

    import astra_database.models  # noqa: F401 - 注册 ORM 表
    from astra_config import get_settings
    from astra_database import Base, create_engine_from_settings, create_session_factory
    from astra_database.models.conversation import AgentRun as OrmAgentRun

    engine = create_engine_from_settings(get_settings())
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    SqlAgentRunRepository(factory).add(
        _run("stale-lifespan", started_at=utcnow() - timedelta(days=1))
    )
    engine.dispose()

    from astra_api.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()):
        pass  # lifespan 触发兜底扫描

    from astra_database import session_scope

    verify_engine = create_engine_from_settings(get_settings())
    try:
        with session_scope(create_session_factory(verify_engine)) as session:
            row = session.get(OrmAgentRun, "stale-lifespan")
        assert row is not None
        assert str(row.status) == RUN_STATUS_FAILED
        assert row.error_type == "HEARTBEAT_TIMEOUT"
    finally:
        verify_engine.dispose()


# -- 兜底扫描须回收沙箱（W6 修复回归：固化 QA 补充验证） ----------------------


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


def test_recover_stale_runs_destroys_sandbox(session_factory: Any) -> None:
    """兜底扫描须 ``destroy`` 沙箱并置 ``sandbox_session.status=STOPPED``（QA 补齐固化）。"""
    tasks = SqlTaskRepository(session_factory)
    sandbox_repository = _FakeSandboxRepository([_FakeSandboxSession("sbx-1")])
    sandbox_provider = _FakeSandboxProvider()

    services = build_conversation_services(
        session_factory,
        task_repository=tasks,
        sandbox_repository=sandbox_repository,
        sandbox_provider=sandbox_provider,
    )
    run_service = services.run_service
    assert run_service is not None

    run = _run("stale-sbx", started_at=utcnow() - timedelta(hours=1))
    run = services.runs.add(run)
    run_service.create_for_run(run)

    recovered = run_service.recover_stale_runs(threshold_ms=60_000)

    assert [item.id for item in recovered] == ["stale-sbx"]
    assert sandbox_provider.destroyed == ["sbx-1"], "兜底扫描未销毁沙箱"
    assert [session.status for session in sandbox_repository.updates] == ["STOPPED"]

    refreshed = services.runs.get("stale-sbx")
    assert refreshed is not None
    task = run_service.get_for_run(refreshed)
    assert task is not None
    assert str(task.status) == RUN_STATUS_FAILED
