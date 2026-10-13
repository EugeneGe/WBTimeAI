"""远程 Task 租约 / 断连续读 / 恢复 / 幂等集成测试（R3 / T2-59；``E-P2-35`` / ``I-P2-40`` / N9）。

覆盖（§8.3 T2-59「fake clock / worker restart / 重投 / cancel / idempotency」）：

- **fake clock**：Claim 落 ``heartbeat_at`` / ``lease_expires_at``（30s 心跳 / 90s 租约），
  心跳 / 续租顺延租约；
- **idempotency / 重投**：同 ``(task_id, attempt)`` 二次 Claim → 冲突 → 「已领取 → 跳过」
  （**非静默**），**不**产生并发 Attempt（DB ``UNIQUE(task_id, attempt)`` 保证）；
- **worker restart**：过期 ``RUNNING`` → ``WORKER_INTERRUPTED``（**不静默重放 / 不伪装成功**），
  未过期 / 已取消记录**不受影响**；``PENDING`` 被**重新投递**；
- **cancel**：显式取消落 ``CANCELLED``（终态），不再被扫描 / 重放；
- **显式重试**：``plan_explicit_retry`` 规划下一 ``attempt``（非自动重放）；
- **真实 DB 原子性**：经 ``SqlTaskExecutionRepository``（SQLite ``UNIQUE(task_id, attempt)``）
  验证并发 Claim 只有一个执行者；
- **handler 接线**：``remote.agent_run`` 经 ``ctx.services["lease_manager"]`` 领取 / 续租 / 落终态，
  重复投递跳过；未注入 ``lease_manager`` 时退化为 T2-58 行为（向后兼容）。

🔴 契约（A-16）：``WORKER_INTERRUPTED`` 为**执行记录状态**字符串，**不**入 ``TaskStatus`` 枚举。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_database import SqlTaskExecutionRepository, SqlTaskRepository
from astra_task import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    EXECUTION_STATUS_WORKER_INTERRUPTED,
    ExecutionRecorder,
    Task,
    TaskExecutionRecord,
    TaskStatus,
)
from astra_worker import HandlerContext
from astra_worker.recovery import (
    REASON_ALREADY_CLAIMED,
    REASON_CONCURRENCY_LIMITED,
    LeaseManager,
    RecoveryReport,
)
from astra_worker.tasks.remote_agent_run import (
    STATUS_ALREADY_CLAIMED,
    STATUS_CONCURRENCY_LIMITED,
    STATUS_DEADLINE_EXCEEDED,
    handle_remote_agent_run,
)
from sqlalchemy.exc import IntegrityError

T0 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)


# -- 测试替身：内存执行记录仓储（实现 Protocol 子集；供 fake clock 用例） --------


class _FakeExecutionRepository:
    """内存 ``TaskExecutionRepository``（实现 ``add`` / ``update`` / ``list`` /
    ``list_by_task`` / ``get_by_attempt`` / ``get``）。

    ``add`` 在 ``(task_id, attempt)`` 重复时抛 ``IntegrityError``——**模拟 DB
    ``UNIQUE(task_id, attempt)``** 的原子拦截。
    """

    def __init__(self) -> None:
        self.rows: dict[str, TaskExecutionRecord] = {}

    def add(self, entity: TaskExecutionRecord) -> TaskExecutionRecord:
        if any(
            row.task_id == entity.task_id and row.attempt == entity.attempt
            for row in self.rows.values()
        ):
            raise IntegrityError("INSERT task_execution", {}, Exception("UNIQUE constraint failed"))
        self.rows[entity.id] = entity
        return entity

    def update(self, entity: TaskExecutionRecord) -> TaskExecutionRecord:
        self.rows[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[TaskExecutionRecord]:
        return [
            row
            for row in self.rows.values()
            if all(getattr(row, key) == value for key, value in filters.items())
        ]

    def list_by_task(self, task_id: str) -> list[TaskExecutionRecord]:
        return sorted(
            (row for row in self.rows.values() if row.task_id == task_id),
            key=lambda row: row.attempt,
        )

    def get_by_attempt(self, task_id: str, attempt: int) -> TaskExecutionRecord | None:
        for row in self.rows.values():
            if row.task_id == task_id and row.attempt == attempt:
                return row
        return None

    def get(self, entity_id: str) -> TaskExecutionRecord | None:
        return self.rows.get(entity_id)


def _manager(
    repo: _FakeExecutionRepository | None = None,
) -> tuple[LeaseManager, _FakeExecutionRepository]:
    repository = repo if repo is not None else _FakeExecutionRepository()
    return LeaseManager(ExecutionRecorder(repository)), repository


# -- fake clock：Claim / heartbeat / 续租 -------------------------------------


def test_claim_sets_heartbeat_and_lease() -> None:
    """Claim 落 ``heartbeat_at`` / ``lease_expires_at``（90s 租约；``started_at`` 同刻）。"""
    manager, repo = _manager()

    outcome = manager.claim(task_id="task-1", attempt=1, worker_id="w-1", now=T0)

    assert outcome.claimed is True
    record = outcome.record
    assert record is not None
    assert record.status == TaskStatus.RUNNING.value
    assert record.started_at == T0
    assert record.heartbeat_at == T0
    assert record.lease_expires_at == T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS)
    assert repo.list_by_task("task-1") == [record]


def test_heartbeat_renews_lease() -> None:
    """心跳（30s 周期）顺延租约到 ``now + 90s``。"""
    manager, _ = _manager()
    record = manager.claim(task_id="task-2", attempt=1, now=T0).record
    assert record is not None

    later = T0 + timedelta(seconds=DEFAULT_HEARTBEAT_SECONDS)
    renewed = manager.heartbeat(record, now=later)

    assert renewed.heartbeat_at == later
    assert renewed.lease_expires_at == later + timedelta(seconds=DEFAULT_LEASE_SECONDS)


def test_renew_matches_heartbeat() -> None:
    """``ExecutionRecorder.renew``（显式续租）与 ``heartbeat`` 同语义。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-3", attempt=1, now=T0)

    renewed = recorder.renew(record, now=T0 + timedelta(seconds=10))

    assert renewed.heartbeat_at == T0 + timedelta(seconds=10)
    assert renewed.lease_expires_at == T0 + timedelta(seconds=10 + DEFAULT_LEASE_SECONDS)


# -- idempotency / 重投 ------------------------------------------------------


def test_claim_is_idempotent_on_redelivery() -> None:
    """同 ``(task_id, attempt)`` 二次 Claim → 「已领取 → 跳过」；不产生并发 Attempt。"""
    manager, repo = _manager()

    first = manager.claim(task_id="task-4", attempt=1, worker_id="w-1", now=T0)
    second = manager.claim(task_id="task-4", attempt=1, worker_id="w-2", now=T0)

    assert first.claimed is True
    assert second.claimed is False
    assert second.reason == REASON_ALREADY_CLAIMED
    assert second.record is not None and second.record.id == first.record.id  # type: ignore[union-attr]
    assert len(repo.list_by_task("task-4")) == 1, "重投产生了并发 Attempt（违反幂等）"


def test_plan_explicit_retry_advances_attempt() -> None:
    """显式重试规划下一 ``attempt``（现有最大值 + 1；非自动重放）。"""
    manager, _ = _manager()
    manager.claim(task_id="task-5", attempt=1, now=T0)

    assert manager.plan_explicit_retry(task_id="task-5") == 2


# -- worker restart：过期 RUNNING → WORKER_INTERRUPTED -----------------------


def test_sweep_interrupted_marks_expired_running() -> None:
    """过期 ``RUNNING`` → ``WORKER_INTERRUPTED``（**不**伪装成功 / **不**静默重放）。"""
    manager, repo = _manager()
    expired = manager.claim(task_id="task-6", attempt=1, now=T0).record
    fresh = manager.claim(task_id="task-7", attempt=1, now=T0).record
    manager.heartbeat(fresh, now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS * 2))  # type: ignore[arg-type]

    after_expiry = T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
    interrupted = manager.sweep_interrupted(now=after_expiry)

    assert [record.id for record in interrupted] == [expired.id]  # type: ignore[union-attr]
    swept = repo.get(expired.id)  # type: ignore[union-attr]
    assert swept is not None
    assert swept.status == EXECUTION_STATUS_WORKER_INTERRUPTED
    assert swept.error
    assert swept.finished_at is not None
    # 未过期记录不受影响（仍在跑）。
    still_running = repo.get(fresh.id)  # type: ignore[union-attr]
    assert still_running is not None
    assert still_running.status == TaskStatus.RUNNING.value


def test_sweep_interrupted_ignores_non_expired() -> None:
    """未过期 ``RUNNING`` 不被标记（心跳仍新鲜）。"""
    manager, _ = _manager()
    manager.claim(task_id="task-8", attempt=1, now=T0)

    interrupted = manager.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS - 1))

    assert interrupted == []


def test_sweep_interrupted_ignores_cancelled() -> None:
    """已取消（终态）记录不被扫描 / 重放（只有 ``RUNNING`` 被扫描）。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-9", attempt=1, now=T0)
    recorder.mark_cancelled(record, now=T0 + timedelta(seconds=1))

    interrupted = recorder.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS * 5))

    assert interrupted == []
    assert record.status == TaskStatus.CANCELLED.value
    assert recorder.is_active(record) is False


# -- 启动恢复：PENDING 重投 --------------------------------------------------


class _FakeTaskRepository:
    """最小 ``TaskRepository``（``list_by_status``；供 PENDING 重投用例）。"""

    def __init__(self, pending: list[Task]) -> None:
        self._pending = pending

    def list_by_status(self, status: str) -> list[Task]:
        return [task for task in self._pending if str(task.status) == status]


def test_recover_on_startup_redelivers_pending_and_sweeps() -> None:
    """启动恢复：先标记过期 ``RUNNING``，再把 ``PENDING`` 重新投递（经注入 ``dispatch``）。"""
    manager, _ = _manager()
    manager.claim(task_id="task-10", attempt=1, now=T0)
    pending = [
        Task(task_id="task-11", type="remote.agent_run", status=TaskStatus.PENDING),
        Task(task_id="task-12", type="project.clone", status=TaskStatus.PENDING),
    ]
    delivered: list[str] = []

    report = manager.recover_on_startup(
        task_repository=_FakeTaskRepository(pending),
        dispatch=lambda task: delivered.append(task.task_id),
        now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1),
    )

    assert isinstance(report, RecoveryReport)
    assert report.redelivered == ("task-11", "task-12")
    assert delivered == ["task-11", "task-12"]
    assert len(report.interrupted) == 1  # 过期 RUNNING 被中断（**非静默重放**）


def test_recover_on_startup_empty_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """无过期执行、无 ``PENDING`` → 空报告（无副作用）。"""
    manager, _ = _manager()
    report = manager.recover_on_startup(
        task_repository=_FakeTaskRepository([]),
        dispatch=lambda task: None,
        now=T0,
    )
    assert report == RecoveryReport()


# -- 真实 DB：原子 Claim（SQLite UNIQUE） ------------------------------------


def test_real_db_atomic_claim_conflict(session_factory: Any) -> None:
    """经真实 ``SqlTaskExecutionRepository``：并发 Claim 只有一个执行者（DB ``UNIQUE`` 保证）。"""
    SqlTaskRepository(session_factory).add(Task(tenant_id="tenant-t59", type="remote.agent_run"))
    task = SqlTaskRepository(session_factory).list_by_type("remote.agent_run")[0]

    recorder = ExecutionRecorder(SqlTaskExecutionRepository(session_factory))
    manager = LeaseManager(recorder)

    first = manager.claim(task_id=task.task_id, attempt=1, worker_id="w-1", now=T0)
    second = manager.claim(task_id=task.task_id, attempt=1, worker_id="w-2", now=T0)

    assert first.claimed is True
    assert second.claimed is False
    assert second.reason == REASON_ALREADY_CLAIMED
    assert len(SqlTaskExecutionRepository(session_factory).list_by_task(task.task_id)) == 1


def test_real_db_sweep_persists_interrupted(session_factory: Any) -> None:
    """真实 DB：过期 ``RUNNING`` 经扫描落 ``WORKER_INTERRUPTED``（持久化留证）。"""
    SqlTaskRepository(session_factory).add(Task(tenant_id="tenant-t59b", type="remote.agent_run"))
    task = SqlTaskRepository(session_factory).list_by_type("remote.agent_run")[0]
    repository = SqlTaskExecutionRepository(session_factory)
    manager = LeaseManager(ExecutionRecorder(repository))

    record = manager.claim(task_id=task.task_id, attempt=1, now=T0).record
    assert record is not None
    interrupted = manager.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1))

    assert [row.id for row in interrupted] == [record.id]
    persisted = repository.get_by_attempt(task.task_id, 1)
    assert persisted is not None
    assert persisted.status == EXECUTION_STATUS_WORKER_INTERRUPTED


# -- handler 接线（remote.agent_run 经 lease_manager） -----------------------


class _Runner:
    """记录调用次数的执行体替身。"""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self._result = result or {
            "status": "SUCCEEDED",
            "result_commit": "b" * 40,
            "environment_digest": "c" * 64,
            "artifact_refs": {"report": "storage://r1"},
        }

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self._result


def test_handler_claims_heartbeats_and_finishes() -> None:
    """``remote.agent_run`` 经 ``lease_manager`` 领取 → 运行 → 落终态 / 结果引用。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    manager = LeaseManager(recorder)
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": runner}
    )

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "exec-1", "task_id": "task-h1", "attempt": 1}}, ctx
    )

    assert result["status"] == "SUCCEEDED"
    assert result["result_commit"] == "b" * 40
    assert runner.calls == 1
    record = manager.recorder.repository.get_by_attempt("task-h1", 1)
    assert record is not None
    assert record.status == TaskStatus.SUCCESS.value
    assert record.result_commit == "b" * 40
    assert record.environment_digest == "c" * 64
    assert record.artifact_refs == {"report": "storage://r1"}


def test_handler_skips_duplicate_delivery() -> None:
    """重复投递：第二次返回 ``already_claimed`` + ``skipped``；执行体**只**跑一次（**非静默**）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": runner}
    )
    message = {"payload": {"execution_id": "exec-2", "task_id": "task-h2", "attempt": 1}}

    first = handle_remote_agent_run(message, ctx)
    second = handle_remote_agent_run(message, ctx)

    assert first["status"] == "SUCCEEDED"
    assert second["status"] == STATUS_ALREADY_CLAIMED
    assert second["skipped"] is True
    assert runner.calls == 1


def test_handler_marks_failed_on_exception() -> None:
    """执行体抛错 → 执行记录落 ``FAILED``（**非静默**）并原样抛出。"""

    class _Boom:
        def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": _Boom()}
    )

    with pytest.raises(RuntimeError):
        handle_remote_agent_run(
            {"payload": {"execution_id": "exec-3", "task_id": "task-h3", "attempt": 1}}, ctx
        )

    record = manager.recorder.repository.get_by_attempt("task-h3", 1)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert "boom" in (record.error or "")


def test_handler_without_lease_manager_is_backward_compatible() -> None:
    """未注入 ``lease_manager`` → 退化为 T2-58 行为（直接运行执行体，不落租约）。"""
    runner = _Runner()
    ctx = HandlerContext(providers=object(), services={"remote_agent_run": runner})

    result = handle_remote_agent_run({"payload": {"execution_id": "exec-4"}}, ctx)

    assert result["status"] == "SUCCEEDED"
    assert runner.calls == 1


def test_handler_requires_task_id_when_leasing() -> None:
    """接租约但缺 ``task_id`` → ``VALIDATION_ERROR``（原子 Claim 需要它）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": _Runner()}
    )

    with pytest.raises(DomainError) as excinfo:
        handle_remote_agent_run({"payload": {"execution_id": "exec-5"}}, ctx)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# -- R5 补全轮 F8b：并发上限（claim 面；fake clock） --------------------------


def test_claim_concurrency_limit_blocks_when_active() -> None:
    """F8b：活跃（RUNNING 且租约未过期）数达 ``max_concurrent_executions`` → 拒领（非静默）。"""
    manager = LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()), max_concurrent_executions=2
    )

    first = manager.claim(task_id="task-c1", attempt=1, now=T0)
    second = manager.claim(task_id="task-c2", attempt=1, now=T0)
    third = manager.claim(task_id="task-c3", attempt=1, now=T0)

    assert first.claimed is True and second.claimed is True
    assert third.claimed is False
    assert third.reason == REASON_CONCURRENCY_LIMITED
    assert third.record is None
    # 被拒的 Attempt **未**落库（无并发残留）。
    assert manager.recorder.repository.get_by_attempt("task-c3", 1) is None


def test_claim_concurrency_frees_after_finish() -> None:
    """F8b：终态（SUCCESS）后活跃数下降 → 恢复放行（限额非永久阻塞）。"""
    manager = LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()), max_concurrent_executions=1
    )
    first = manager.claim(task_id="task-c4", attempt=1, now=T0)
    assert first.record is not None
    blocked = manager.claim(task_id="task-c5", attempt=1, now=T0)
    assert blocked.reason == REASON_CONCURRENCY_LIMITED

    manager.finish(first.record, now=T0)

    assert manager.claim(task_id="task-c5", attempt=1, now=T0).claimed is True


def test_claim_concurrency_ignores_expired_lease() -> None:
    """F8b：租约**已过期**的 RUNNING 不计入活跃数（失联 ≠ 占位）。"""
    manager = LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()), max_concurrent_executions=1
    )
    manager.claim(task_id="task-c6", attempt=1, now=T0)

    later = T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
    outcome = manager.claim(task_id="task-c7", attempt=1, now=later)

    assert outcome.claimed is True


def test_claim_without_concurrency_cap_is_unlimited() -> None:
    """F8b：未注入 cap（缺省）→ 不启用并发检查（零回归；无限领取）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))

    assert all(
        manager.claim(task_id=f"task-u{index}", attempt=1, now=T0).claimed for index in range(5)
    )


# -- R5 补全轮 F8c：deadline 快速失败（handler 面；fake clock） --------------


def test_handler_deadline_exceeded_skips_runner() -> None:
    """F8c：``payload.deadline_at`` 已过期 → **不运行**执行体，落稳定失败终态（非静默）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": runner}
    )
    past = (utcnow() - timedelta(seconds=5)).isoformat()

    result = handle_remote_agent_run(
        {
            "payload": {
                "execution_id": "exec-d1",
                "task_id": "task-d1",
                "attempt": 1,
                "deadline_at": past,
            }
        },
        ctx,
    )

    assert result["status"] == STATUS_DEADLINE_EXCEEDED
    assert result["skipped"] is True
    assert runner.calls == 0, "deadline 过期仍运行了执行体"
    record = manager.recorder.repository.get_by_attempt("task-d1", 1)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert "deadline_exceeded" in (record.error or "")


def test_handler_with_future_deadline_runs() -> None:
    """F8c：deadline **未**过期 → 正常运行执行体（零回归）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()))
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": runner}
    )
    future = (utcnow() + timedelta(seconds=3600)).isoformat()

    result = handle_remote_agent_run(
        {
            "payload": {
                "execution_id": "exec-d2",
                "task_id": "task-d2",
                "attempt": 1,
                "deadline_at": future,
            }
        },
        ctx,
    )

    assert result["status"] == "SUCCEEDED"
    assert runner.calls == 1


def test_handler_returns_concurrency_limited_status() -> None:
    """F8b：并发受限 → handler 返回 ``concurrency_limited`` + ``skipped``（**非静默**）。"""
    manager = LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()), max_concurrent_executions=1
    )
    manager.claim(task_id="task-occupied", attempt=1, now=utcnow())
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(), services={"lease_manager": manager, "remote_agent_run": runner}
    )

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "exec-cl", "task_id": "task-cl", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_CONCURRENCY_LIMITED
    assert result["skipped"] is True
    assert runner.calls == 0


def test_artifact_limit_rejects_and_fails_terminal() -> None:
    """F8d：artifact 数量超上限 → 拒绝落库 + 稳定失败终态 + 抛 ``RESOURCE_LIMIT_EXCEEDED``。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()), max_artifact_count=1)
    record = manager.claim(task_id="task-a1", attempt=1, now=T0).record
    assert record is not None

    too_many = {"log": {"ref": "s://1", "size": 1}, "report": {"ref": "s://2", "size": 1}}
    with pytest.raises(DomainError) as excinfo:
        manager.finish(record, artifact_refs=too_many, now=T0 + timedelta(seconds=1))

    assert excinfo.value.code is ErrorCode.RESOURCE_LIMIT_EXCEEDED
    persisted = manager.recorder.repository.get_by_attempt("task-a1", 1)
    assert persisted is not None
    assert persisted.status == TaskStatus.FAILED.value
    assert persisted.artifact_refs is None  # 超限产物**拒绝落库**
    assert "RESOURCE_LIMIT_EXCEEDED" in (persisted.error or "")


def test_artifact_size_limit_rejects() -> None:
    """F8d：artifact 累计字节超上限 → 拒绝落库（稳定失败）。"""
    manager = LeaseManager(ExecutionRecorder(_FakeExecutionRepository()), max_artifact_bytes=10)
    record = manager.claim(task_id="task-a2", attempt=1, now=T0).record
    assert record is not None

    with pytest.raises(DomainError) as excinfo:
        manager.finish(
            record,
            artifact_refs={"big": {"ref": "s://big", "size": 11}},
            now=T0 + timedelta(seconds=1),
        )
    assert excinfo.value.code is ErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_artifact_within_limit_passes() -> None:
    """F8d：恰在上限内（``==``）→ 通过并落库（仅 ``>`` 判超）。"""
    manager = LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()),
        max_artifact_count=2,
        max_artifact_bytes=100,
    )
    record = manager.claim(task_id="task-a3", attempt=1, now=T0).record
    assert record is not None

    finished = manager.finish(
        record,
        artifact_refs={"a": {"ref": "s://a", "size": 50}, "b": {"ref": "s://b", "size": 50}},
        now=T0 + timedelta(seconds=1),
    )

    assert finished.status == TaskStatus.SUCCESS.value
    assert finished.artifact_refs == {
        "a": {"ref": "s://a", "size": 50},
        "b": {"ref": "s://b", "size": 50},
    }


# -- 契约：零新 Task 状态枚举（A-16） ----------------------------------------


def test_worker_interrupted_is_not_task_status_member() -> None:
    """``WORKER_INTERRUPTED`` 为**执行记录状态**字符串，**不**入 ``TaskStatus`` 枚举（A-16）。"""
    assert EXECUTION_STATUS_WORKER_INTERRUPTED == "WORKER_INTERRUPTED"
    assert EXECUTION_STATUS_WORKER_INTERRUPTED not in {member.value for member in TaskStatus}
    assert not hasattr(TaskStatus, EXECUTION_STATUS_WORKER_INTERRUPTED)


def test_heartbeat_and_lease_constants() -> None:
    """心跳 30s / 租约 90s（设计 §2.9.1 冻结口径）。"""
    assert DEFAULT_HEARTBEAT_SECONDS == 30
    assert DEFAULT_LEASE_SECONDS == 90


def test_lease_expiry_boundary() -> None:
    """租约边界：``now >= lease_expires_at`` 即过期（``utcnow`` 归一化后比较）。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-b", attempt=1, now=utcnow())
    assert record.lease_expires_at is not None

    assert recorder.is_lease_expired(record, now=record.lease_expires_at) is True
    assert (
        recorder.is_lease_expired(record, now=record.lease_expires_at - timedelta(seconds=1))
        is False
    )
