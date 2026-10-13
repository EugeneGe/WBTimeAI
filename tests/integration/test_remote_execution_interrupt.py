"""远程执行**中段强制打断**集成测试（A-2；设计 §2.9.1 断连规则 / N9 / N10）。

承 R5 补全轮 F8c（deadline **运行前**快速失败）——本用例验证 **A-2**：**运行中**强制打断：

- **超 ``max_duration_seconds``** 或**显式中断 / 取消** → 终态 ``WORKER_INTERRUPTED``（或
  显式取消 → ``CANCELLED``；设计 §2.9.1），**不**伪装成功、**不**落 ``FAILED``；
- 中断 / 取消**释放资源位**：记录离开 ``RUNNING`` 后不再计入活跃数（并发位可被占）；
- 执行体经 :class:`ExecutionInterrupted` **协作式**上报中断（同步执行体的可测契约）；
- **F8c 零回归**：运行前 deadline 快速失败仍落 ``deadline_exceeded``。

🔴 handler 级注入模式（进程内可跑；真容器 / 租约回收真机面归服务器线 S5）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from astra_task import (
    EXECUTION_STATUS_WORKER_INTERRUPTED,
    ExecutionRecorder,
    TaskExecutionRecord,
    TaskStatus,
)
from astra_worker import HandlerContext
from astra_worker.recovery import LeaseManager
from astra_worker.tasks.remote_agent_run import (
    STATUS_DEADLINE_EXCEEDED,
    STATUS_WORKER_INTERRUPTED,
    ExecutionInterrupted,
    handle_remote_agent_run,
)


class _FakeExecutionRepository:
    """内存 ``TaskExecutionRepository``（实现 Protocol 子集）。"""

    def __init__(self) -> None:
        self.rows: dict[str, TaskExecutionRecord] = {}

    def add(self, entity: TaskExecutionRecord) -> TaskExecutionRecord:
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
        return [row for row in self.rows.values() if row.task_id == task_id]

    def get_by_attempt(self, task_id: str, attempt: int) -> TaskExecutionRecord | None:
        for row in self.rows.values():
            if row.task_id == task_id and row.attempt == attempt:
                return row
        return None

    def get(self, entity_id: str) -> TaskExecutionRecord | None:
        return self.rows.get(entity_id)


class _Runner:
    """执行体替身：记录调用；可配置为抛出 ``ExecutionInterrupted``。"""

    def __init__(self, *, interrupt_reason: str | None = None) -> None:
        self.calls = 0
        self._interrupt_reason = interrupt_reason

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self._interrupt_reason is not None:
            raise ExecutionInterrupted(self._interrupt_reason)
        return {"status": "SUCCEEDED", "result_commit": "b" * 40}


def _manager(*, concurrency: int | None = None, clock: Any = None) -> tuple[LeaseManager, Any]:
    repository = _FakeExecutionRepository()
    kwargs: dict[str, Any] = {"max_concurrent_executions": concurrency}
    if clock is not None:
        kwargs["clock"] = clock
    return LeaseManager(ExecutionRecorder(repository), **kwargs), repository


def _ctx(manager: LeaseManager, runner: _Runner, **services: Any) -> HandlerContext:
    base: dict[str, Any] = {"lease_manager": manager, "remote_agent_run": runner}
    base.update(services)
    return HandlerContext(providers=object(), services=base)


# -- A-2：显式中断 / 取消（运行前） ------------------------------------------


def test_interrupt_signal_before_run_marks_worker_interrupted() -> None:
    """运行**前**收到中断信号 → 不运行执行体，终态 ``WORKER_INTERRUPTED``（**不**伪装成功）。"""
    manager, _ = _manager(clock=lambda: datetime(2026, 10, 14, 6, 0, 0, tzinfo=UTC))
    runner = _Runner()
    ctx = _ctx(manager, runner, interrupt_signal=lambda _payload: True)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i1", "task_id": "t-i1", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_WORKER_INTERRUPTED
    assert result["skipped"] is True
    assert result.get("interrupted") is True
    assert runner.calls == 0
    record = manager.recorder.repository.get_by_attempt("t-i1", 1)
    assert record is not None
    assert record.status == EXECUTION_STATUS_WORKER_INTERRUPTED
    assert record.status != TaskStatus.SUCCESS.value


def test_explicit_cancel_signal_marks_cancelled() -> None:
    """显式取消信号（``cancelled``）→ 终态 ``CANCELLED``（设计 §2.9.1；区别于失联中断）。"""
    manager, _ = _manager()
    runner = _Runner()
    ctx = _ctx(manager, runner, interrupt_signal=lambda _payload: "cancelled")

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i2", "task_id": "t-i2", "attempt": 1}}, ctx
    )

    assert result["status"] == "cancelled"
    assert runner.calls == 0
    record = manager.recorder.repository.get_by_attempt("t-i2", 1)
    assert record is not None
    assert record.status == TaskStatus.CANCELLED.value


# -- A-2：运行中协作式中断（执行体抛 ExecutionInterrupted） -------------------


def test_runner_interrupt_marks_worker_interrupted_not_failed() -> None:
    """执行体**运行中**抛 ``ExecutionInterrupted`` → ``WORKER_INTERRUPTED``（**不**落 FAILED）。"""
    manager, _ = _manager()
    runner = _Runner(interrupt_reason="deadline_exceeded")
    ctx = _ctx(manager, runner)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i3", "task_id": "t-i3", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_WORKER_INTERRUPTED
    assert result.get("interrupted") is True
    assert runner.calls == 1  # 已进入执行体，运行中被打断
    record = manager.recorder.repository.get_by_attempt("t-i3", 1)
    assert record is not None
    assert record.status == EXECUTION_STATUS_WORKER_INTERRUPTED
    assert record.status != TaskStatus.FAILED.value
    assert "deadline_exceeded" in (record.error or "")


# -- A-2：运行中时长上限（执行体未协作，处理器按墙钟兜底） --------------------


def test_exceeded_duration_marks_interrupted_and_discards_result() -> None:
    """运行耗时超 ``max_duration_seconds`` → ``WORKER_INTERRUPTED``（**丢弃结果、不伪造成功**）。"""
    past = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)  # 远早于真实 now → 历时判定超限
    manager, _ = _manager(clock=lambda: past)
    runner = _Runner()  # 正常返回，但历时判定超限
    ctx = _ctx(manager, runner, max_duration_seconds=0)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i4", "task_id": "t-i4", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_WORKER_INTERRUPTED
    assert result["skipped"] is True
    record = manager.recorder.repository.get_by_attempt("t-i4", 1)
    assert record is not None
    assert record.status == EXECUTION_STATUS_WORKER_INTERRUPTED
    assert record.result_commit is None, "超时结果不得落库（不伪造成功）"


def test_within_duration_runs_success_zero_regression() -> None:
    """未超时长（含未配置）→ 正常落 ``SUCCESS``（零回归）。"""
    manager, _ = _manager()
    runner = _Runner()
    ctx = _ctx(manager, runner, max_duration_seconds=10**9)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i5", "task_id": "t-i5", "attempt": 1}}, ctx
    )

    assert result["status"] == "SUCCEEDED"
    record = manager.recorder.repository.get_by_attempt("t-i5", 1)
    assert record is not None and record.status == TaskStatus.SUCCESS.value


# -- A-2：资源位回收（租约 / 并发位） ----------------------------------------


def test_interrupt_releases_active_slot() -> None:
    """中断使记录离开 ``RUNNING`` → 活跃数下降 → 并发位可被再次占用（资源回收）。"""
    manager, _ = _manager(concurrency=1)
    occupied = manager.claim(task_id="t-i6", attempt=1).record
    assert occupied is not None
    assert manager._count_active(now=manager.clock()) == 1  # noqa: SLF001 - 活跃数断言

    manager.interrupt(occupied, reason="deadline_exceeded")

    assert manager._count_active(now=manager.clock()) == 0  # noqa: SLF001
    assert manager.claim(task_id="t-i7", attempt=1).claimed is True


def test_no_signal_zero_regression() -> None:
    """未注入任何中断服务 → 正常执行（F8b/c 零回归）。"""
    manager, _ = _manager()
    runner = _Runner()
    ctx = _ctx(manager, runner)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "i8", "task_id": "t-i8", "attempt": 1}}, ctx
    )

    assert result["status"] == "SUCCEEDED"


# -- 契约：运行前 deadline 快速失败仍落 deadline_exceeded（F8c 零回归） -------


def test_pre_run_deadline_still_deadline_exceeded() -> None:
    """F8c 零回归：运行前 ``deadline_at`` 过期 → ``deadline_exceeded``（**不**改语义）。"""
    manager, _ = _manager()
    runner = _Runner()
    ctx = _ctx(manager, runner)
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()

    result = handle_remote_agent_run(
        {
            "payload": {
                "execution_id": "i9",
                "task_id": "t-i9",
                "attempt": 1,
                "deadline_at": past,
            }
        },
        ctx,
    )

    assert result["status"] == STATUS_DEADLINE_EXCEEDED
    assert runner.calls == 0
