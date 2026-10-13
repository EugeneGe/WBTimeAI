"""远程执行**并发受限自动留守重派**集成测试（A-1；设计 §2.9.1 并发和限额 / N10）。

承 R5 补全轮 F8b（``concurrency_limited`` + ``skipped=True``，**不**重派）——本用例验证 **A-1**：

- 并发受限 → **自动留守 + 有界择机重派**：重派次数**有界可配**（``max_redispatch_attempts``，
  防无限循环），达上限回落既有 ``concurrency_limited``（**非静默**）；
- 并发位释放后，重投消息进入 ``RUNNING``（**自动留守**语义闭环）；
- 重派经**注入回调**（``ctx.services["redispatch"]``）完成，处理器**不**直连队列（R-23 正交）；
- **F8a/c/d 零回归**：未启用重派时行为与既有完全一致；重复投递仍 ``already_claimed``。

🔴 handler 级注入模式（仿 F8b：``lease_manager`` + runner 注入，进程内可跑；真 Docker 面归
服务器线 S5 compose 档注入）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from astra_config import RemoteExecutionSettings
from astra_config import defaults as cfg_defaults
from astra_task import ExecutionRecorder, TaskExecutionRecord, TaskStatus
from astra_worker import HandlerContext
from astra_worker.recovery import REASON_CONCURRENCY_LIMITED, LeaseManager
from astra_worker.tasks.remote_agent_run import (
    STATUS_ALREADY_CLAIMED,
    STATUS_CONCURRENCY_LIMITED,
    STATUS_STANDBY,
    handle_remote_agent_run,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

T0 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)


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
        return [row for row in self.rows.values() if row.task_id == task_id]

    def get_by_attempt(self, task_id: str, attempt: int) -> TaskExecutionRecord | None:
        for row in self.rows.values():
            if row.task_id == task_id and row.attempt == attempt:
                return row
        return None

    def get(self, entity_id: str) -> TaskExecutionRecord | None:
        return self.rows.get(entity_id)


class _Runner:
    """记录调用次数的执行体替身。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"status": "SUCCEEDED", "result_commit": "b" * 40}


def _manager(*, concurrency: int | None = 1) -> tuple[LeaseManager, _FakeExecutionRepository]:
    repository = _FakeExecutionRepository()
    return (
        LeaseManager(ExecutionRecorder(repository), max_concurrent_executions=concurrency),
        repository,
    )


def _ctx(
    manager: LeaseManager,
    runner: _Runner,
    *,
    redispatch: Any = None,
    max_redispatch_attempts: int | None = None,
) -> HandlerContext:
    services: dict[str, Any] = {"lease_manager": manager, "remote_agent_run": runner}
    if redispatch is not None:
        services["redispatch"] = redispatch
    if max_redispatch_attempts is not None:
        services["max_redispatch_attempts"] = max_redispatch_attempts
    return HandlerContext(providers=object(), services=services)


# -- A-1：留守 + 有界重派 ----------------------------------------------------


def test_standby_redispatches_with_incremented_count() -> None:
    """并发受限 → ``standby`` + ``skipped``；经注入回调重派一次，``redispatch_count`` 递增。"""
    manager, _ = _manager(concurrency=1)
    manager.claim(task_id="occupy-a1", attempt=1, now=T0)  # 占满并发位
    runner = _Runner()
    requeued: list[dict[str, Any]] = []
    ctx = _ctx(manager, runner, redispatch=requeued.append, max_redispatch_attempts=3)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "exec-standby", "task_id": "task-standby", "attempt": 1}},
        ctx,
    )

    assert result["status"] == STATUS_STANDBY
    assert result["skipped"] is True
    assert result["redispatch_count"] == 1
    assert runner.calls == 0, "留守回合不得运行执行体"
    assert len(requeued) == 1
    # 重派消息保留原执行标识并递增计数（供重投后重试 claim）。
    requeued_payload = requeued[0]["payload"]
    assert requeued_payload["redispatch_count"] == 1
    assert requeued_payload["task_id"] == "task-standby"
    assert requeued_payload["execution_id"] == "exec-standby"


def test_standby_bounded_then_concurrency_limited() -> None:
    """重派次数达上限 → 回落既有 ``concurrency_limited``（**非静默**），不再重派。"""
    manager, _ = _manager(concurrency=1)
    manager.claim(task_id="occupy-a1b", attempt=1, now=T0)
    runner = _Runner()
    requeued: list[dict[str, Any]] = []
    ctx = _ctx(manager, runner, redispatch=requeued.append, max_redispatch_attempts=2)

    # 模拟连续重投：redispatch_count 从 0 递增；达上限（2）后调用。
    first = handle_remote_agent_run(
        {"payload": {"execution_id": "e", "task_id": "t", "attempt": 1}}, ctx
    )
    assert first["status"] == STATUS_STANDBY and first["redispatch_count"] == 1

    at_limit = handle_remote_agent_run(
        {"payload": {"execution_id": "e", "task_id": "t", "attempt": 1, "redispatch_count": 2}},
        ctx,
    )
    assert at_limit["status"] == STATUS_CONCURRENCY_LIMITED
    assert at_limit["skipped"] is True
    assert at_limit["redispatch_count"] == 2
    assert len(requeued) == 1, "达上限后不得再重派"


def test_standby_runs_when_slot_freed() -> None:
    """**自动留守闭环**：并发位释放后，重投消息重试 claim → 进入 ``RUNNING``（落 SUCCESS）。"""
    manager, _ = _manager(concurrency=1)
    occupied = manager.claim(task_id="occupy-a1c", attempt=1, now=T0).record
    assert occupied is not None
    runner = _Runner()
    requeued: list[dict[str, Any]] = []
    ctx = _ctx(manager, runner, redispatch=requeued.append, max_redispatch_attempts=3)

    standby = handle_remote_agent_run(
        {"payload": {"execution_id": "e2", "task_id": "task-a1c", "attempt": 1}}, ctx
    )
    assert standby["status"] == STATUS_STANDBY

    # 释放并发位（占位者落终态）。
    manager.finish(occupied, now=T0)

    # 重投消息回到处理器 → 成功领取并运行。
    resumed = handle_remote_agent_run(requeued[0], ctx)
    assert resumed["status"] == "SUCCEEDED"
    assert runner.calls == 1
    record = manager.recorder.repository.get_by_attempt("task-a1c", 1)
    assert record is not None and record.status == TaskStatus.SUCCESS.value


def test_no_redispatch_when_not_wired_is_backward_compatible() -> None:
    """未注入重派回调 → 保持既有 ``concurrency_limited``（F8b 零回归）。"""
    manager, _ = _manager(concurrency=1)
    manager.claim(task_id="occupy-a1d", attempt=1, now=T0)
    runner = _Runner()
    ctx = _ctx(manager, runner)  # 无 redispatch

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "e3", "task_id": "t3", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_CONCURRENCY_LIMITED
    assert result["skipped"] is True
    assert runner.calls == 0


def test_redispatch_failure_falls_back_non_silent() -> None:
    """重派回调抛错 → **非静默**回落 ``concurrency_limited``（不伪装已重派）。"""

    def _boom(_message: dict[str, Any]) -> None:
        raise RuntimeError("queue down")

    manager, _ = _manager(concurrency=1)
    manager.claim(task_id="occupy-a1e", attempt=1, now=T0)
    runner = _Runner()
    ctx = _ctx(manager, runner, redispatch=_boom, max_redispatch_attempts=3)

    result = handle_remote_agent_run(
        {"payload": {"execution_id": "e4", "task_id": "t4", "attempt": 1}}, ctx
    )

    assert result["status"] == STATUS_CONCURRENCY_LIMITED
    assert result["skipped"] is True


def test_duplicate_delivery_still_already_claimed_not_standby() -> None:
    """重复投递（同 ``(task_id, attempt)``）→ ``already_claimed``，**不**误入留守重派。"""
    manager, _ = _manager(concurrency=None)  # 不启用并发检查
    runner = _Runner()
    requeued: list[dict[str, Any]] = []
    ctx = _ctx(manager, runner, redispatch=requeued.append, max_redispatch_attempts=3)
    message = {"payload": {"execution_id": "e5", "task_id": "t5", "attempt": 1}}

    first = handle_remote_agent_run(message, ctx)
    second = handle_remote_agent_run(message, ctx)

    assert first["status"] == "SUCCEEDED"
    assert second["status"] == STATUS_ALREADY_CLAIMED
    assert requeued == [], "重复投递不得触发留守重派"


# -- 配置：有界次数 + 硬上限（沿用硬上限校验风格） ---------------------------


def test_redispatch_attempts_default_and_ceiling() -> None:
    """``max_redispatch_attempts`` 默认 3；超硬上限 / 非正 → 构造期 ``ValidationError``。"""
    limits = RemoteExecutionSettings()
    assert limits.max_redispatch_attempts == 3
    assert cfg_defaults.HARD_MAX_REDISPATCH_ATTEMPTS == 10

    with pytest.raises(ValidationError):
        RemoteExecutionSettings(
            max_redispatch_attempts=cfg_defaults.HARD_MAX_REDISPATCH_ATTEMPTS + 1
        )
    with pytest.raises(ValidationError):
        RemoteExecutionSettings(max_redispatch_attempts=0)
    # 硬上限本身可接受。
    assert (
        RemoteExecutionSettings(
            max_redispatch_attempts=cfg_defaults.HARD_MAX_REDISPATCH_ATTEMPTS
        ).max_redispatch_attempts
        == cfg_defaults.HARD_MAX_REDISPATCH_ATTEMPTS
    )


def test_reason_constant_matches_concurrency() -> None:
    """``REASON_CONCURRENCY_LIMITED`` 与处理器判据一致（防字符串漂移）。"""
    assert REASON_CONCURRENCY_LIMITED == "concurrency_limited"
