"""远程执行 **``max_disk_bytes`` 统计强制 + 磁盘水位告警**集成测试（A-3；设计 §2.9.1 / N10）。

承 R5 补全轮 F8d（artifact 上限）——本用例验证 **A-3**：``max_disk_bytes`` 由配置项升级为
**强制执行**：

- 执行期统计 workspace 占用，**超限** → 终止（稳定失败终态 + ``RESOURCE_LIMIT_EXCEEDED``
  错误码，**非静默**）；
- 新增**水位阈值** ``disk_high_watermark_ratio`` → **告警事件**（``worker.disk_high_watermark``），
  **不**终止；
- **不超限零误杀**（``== max_disk_bytes`` 通过；未启用 → 零回归）。

🔴 handler 级注入模式（进程内可跑；真实 workspace 统计经 ``ctx.services["workspace_disk_usage"]``
注入，组合根实现）。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from astra_config import RemoteExecutionSettings
from astra_core import DomainError, ErrorCode
from astra_task import ExecutionRecorder, TaskExecutionRecord, TaskStatus
from astra_worker import HandlerContext
from astra_worker.recovery import LeaseManager
from astra_worker.tasks.remote_agent_run import handle_remote_agent_run
from pydantic import ValidationError


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
    """正常返回的执行体替身。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"status": "SUCCEEDED", "result_commit": "b" * 40}


def _manager(
    *,
    max_disk_bytes: int | None = None,
    disk_enforce: bool = True,
    watermark: float | None = None,
) -> LeaseManager:
    return LeaseManager(
        ExecutionRecorder(_FakeExecutionRepository()),
        max_disk_bytes=max_disk_bytes,
        disk_enforce=disk_enforce,
        disk_high_watermark_ratio=watermark,
    )


def _ctx(manager: LeaseManager, runner: _Runner, usage: Any) -> HandlerContext:
    services: dict[str, Any] = {"lease_manager": manager, "remote_agent_run": runner}
    if usage is not None:
        services["workspace_disk_usage"] = lambda _payload: usage
    return HandlerContext(providers=object(), services=services)


def _msg(task_id: str) -> dict[str, Any]:
    return {"payload": {"execution_id": f"e-{task_id}", "task_id": task_id, "attempt": 1}}


# -- A-3：超限终止（稳定失败 + RESOURCE_LIMIT_EXCEEDED） ---------------------


def test_disk_over_limit_terminates_resource_limit_exceeded() -> None:
    """占用 **超** ``max_disk_bytes`` → 终止：抛 ``RESOURCE_LIMIT_EXCEEDED`` + 稳定失败终态。"""
    manager = _manager(max_disk_bytes=100)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=101)

    with pytest.raises(DomainError) as excinfo:
        handle_remote_agent_run(_msg("t-disk1"), ctx)

    assert excinfo.value.code is ErrorCode.RESOURCE_LIMIT_EXCEEDED
    assert excinfo.value.status_code == 429
    record = manager.recorder.repository.get_by_attempt("t-disk1", 1)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert record.status != TaskStatus.SUCCESS.value
    assert "RESOURCE_LIMIT_EXCEEDED" in (record.error or "")


def test_disk_exactly_at_limit_passes_no_false_kill() -> None:
    """恰在上限（``==``）→ 通过并落 ``SUCCESS``（仅 ``>`` 判超；**不**误杀）。"""
    manager = _manager(max_disk_bytes=100)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=100)

    result = handle_remote_agent_run(_msg("t-disk2"), ctx)

    assert result["status"] == "SUCCEEDED"
    record = manager.recorder.repository.get_by_attempt("t-disk2", 1)
    assert record is not None and record.status == TaskStatus.SUCCESS.value


def test_disk_within_limit_passes() -> None:
    """显著低于上限 → 通过（零误杀）。"""
    manager = _manager(max_disk_bytes=100)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=10)
    assert handle_remote_agent_run(_msg("t-disk3"), ctx)["status"] == "SUCCEEDED"


# -- A-3：水位告警（不终止） -------------------------------------------------


def test_disk_watermark_emits_alert_but_does_not_terminate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``used > ratio * max`` 但未超上限 → **告警事件**且**不**终止（落 SUCCESS）。"""
    manager = _manager(max_disk_bytes=100, watermark=0.8)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=85)  # 85 > 0.8*100=80，但 <= 100

    with caplog.at_level(logging.WARNING):
        result = handle_remote_agent_run(_msg("t-disk4"), ctx)

    assert result["status"] == "SUCCEEDED"
    assert any(
        record.getMessage() == "worker.disk_high_watermark" for record in caplog.records
    ), "超水位应产生可见告警事件"


def test_disk_below_watermark_no_alert(caplog: pytest.LogCaptureFixture) -> None:
    """占用低于水位 → **无**告警（零噪声）。"""
    manager = _manager(max_disk_bytes=100, watermark=0.8)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=50)

    with caplog.at_level(logging.WARNING):
        result = handle_remote_agent_run(_msg("t-disk5"), ctx)

    assert result["status"] == "SUCCEEDED"
    assert not any(record.getMessage() == "worker.disk_high_watermark" for record in caplog.records)


# -- A-3：未启用 / 向后兼容 --------------------------------------------------


def test_disk_enforce_disabled_does_not_terminate() -> None:
    """``disk_enforce=False`` → 即使超上限也**不**终止（仅可告警）。"""
    manager = _manager(max_disk_bytes=100, disk_enforce=False)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=1000)

    result = handle_remote_agent_run(_msg("t-disk6"), ctx)

    assert result["status"] == "SUCCEEDED"
    record = manager.recorder.repository.get_by_attempt("t-disk6", 1)
    assert record is not None and record.status == TaskStatus.SUCCESS.value


def test_disk_not_wired_zero_regression() -> None:
    """未注入统计回调 → 不做磁盘判定（F8d / 既有行为零回归）。"""
    manager = _manager(max_disk_bytes=100)
    runner = _Runner()
    ctx = _ctx(manager, runner, usage=None)

    assert handle_remote_agent_run(_msg("t-disk7"), ctx)["status"] == "SUCCEEDED"


def test_disk_probe_error_is_non_silent() -> None:
    """统计回调抛错 → **向上传播**（非静默，H-7；不静默吞成「不超限」）。"""

    def _boom(_payload: dict[str, Any]) -> int:
        raise RuntimeError("stat failed")

    manager = _manager(max_disk_bytes=100)
    runner = _Runner()
    ctx = HandlerContext(
        providers=object(),
        services={
            "lease_manager": manager,
            "remote_agent_run": runner,
            "workspace_disk_usage": _boom,
        },
    )

    with pytest.raises(RuntimeError):
        handle_remote_agent_run(_msg("t-disk8"), ctx)


# -- 配置：disk_enforce / 水位阈值（沿用硬上限校验风格） ---------------------


def test_disk_settings_defaults() -> None:
    """默认 ``disk_enforce=True`` / 水位 ``0.8``（A-3）。"""
    limits = RemoteExecutionSettings()
    assert limits.disk_enforce is True
    assert limits.disk_high_watermark_ratio == 0.8


def test_disk_watermark_ratio_validation() -> None:
    """水位比例必须在 ``(0, 1]``，否则构造期 ``ValidationError``（**显式**，不静默）。"""
    RemoteExecutionSettings(disk_high_watermark_ratio=1.0)  # 合法上界
    RemoteExecutionSettings(disk_high_watermark_ratio=0.01)  # 合法小值
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValidationError):
            RemoteExecutionSettings(disk_high_watermark_ratio=bad)
