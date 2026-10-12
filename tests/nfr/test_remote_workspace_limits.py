"""远程 Workspace 资源边界 NFR（R3 / T2-59 创建；R5 / T2-63 扩展；设计 §2.9.1 / §2.18；N9 / N10）。

覆盖：

- **并发 / 待处理 / 时长 / 磁盘 / Artifact 限额**：默认值（并发 2 / 待处理 4 / 单次 8h）
  + **硬上限**；
- **硬上限显式校验**：超硬上限 / 非正值 → 构造期报错（部署**只可收紧**，不可越过硬上限）；
- **执行 deadline 依据**：Claim 租约（90s）与心跳（30s）常量 + 执行耗时（``duration_ms``）计算；
- **N9 连续性**：心跳续租使在执行中的 Attempt **不**被判为失联（仅过期才中断）；
- **N9 连续性（T2-63 扩展）**：心跳续租使在执行中的 Attempt **不**被判为失联；**租约过期**
  → Attempt 以 ``WORKER_INTERRUPTED`` 结束（**不**静默伪装成功）；
- **N10 远程工作区资源边界（T2-63 扩展）**：Community 档**应用层**边界（并发 / 时长 /
  产物大小 / 磁盘）限额在位（**不**宣称 OS 级隔离）；Docker / Compose **硬配额**（CPU / 内存 /
  PID / 磁盘 / 网络）生效**仅**在 Docker 档 —— **挂账待服务器**；
- **Sandbox 资源限额**：Docker 沙箱默认 CPU / 内存 / PID 限额 + ``network=none``（进程级能力边界）。

🔴 本 NFR 不含真实 Docker / PG 依赖（本机无 Docker）；真实隔离验收归 R5 / T2-63
（``#42`` / D19 / N10）。
"""

from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from astra_config import RemoteExecutionSettings, Settings
from astra_config import defaults as cfg_defaults
from astra_sandbox import DockerSandboxProvider
from astra_task import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    EXECUTION_STATUS_WORKER_INTERRUPTED,
    ExecutionRecorder,
    TaskExecutionRecord,
    TaskStatus,
)
from pydantic import ValidationError

T0 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)


class _FakeExecutionRepository:
    """最小内存执行记录仓储（供租约 / 时长断言）。"""

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


# -- 默认限额 ----------------------------------------------------------------


def test_remote_execution_default_limits() -> None:
    """默认：并发 2 / 用户待处理 4 / 单次 8h / 磁盘 8 GiB / Artifact 4 GiB / 200 件。"""
    limits = RemoteExecutionSettings()

    assert limits.max_concurrent_executions == 2
    assert limits.max_pending_per_user == 4
    assert limits.max_duration_seconds == 8 * 3600
    assert limits.max_disk_bytes == 8 * 1024**3
    assert limits.max_artifact_bytes == 4 * 1024**3
    assert limits.max_artifact_count == 200


def test_settings_exposes_remote_execution_limits() -> None:
    """``Settings`` 暴露 ``remote_execution`` 限额（组合根 / 服务端读取）。"""
    settings = Settings(remote_execution=RemoteExecutionSettings(max_concurrent_executions=3))

    assert settings.remote_execution.max_concurrent_executions == 3
    assert settings.remote_execution.max_duration_seconds == 8 * 3600


# -- 硬上限（部署只可收紧） --------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "ceiling"),
    [
        ("max_concurrent_executions", cfg_defaults.HARD_MAX_CONCURRENT_EXECUTIONS + 1, 32),
        ("max_pending_per_user", cfg_defaults.HARD_MAX_PENDING_PER_USER + 1, 64),
        ("max_duration_seconds", cfg_defaults.HARD_MAX_DURATION_SECONDS + 1, 24 * 3600),
        ("max_disk_bytes", cfg_defaults.HARD_MAX_DISK_BYTES + 1, 64 * 1024**3),
        ("max_artifact_bytes", cfg_defaults.HARD_MAX_ARTIFACT_BYTES + 1, 16 * 1024**3),
        ("max_artifact_count", cfg_defaults.HARD_MAX_ARTIFACT_COUNT + 1, 1000),
    ],
)
def test_hard_ceiling_rejects_over_limit(field: str, value: int, ceiling: int) -> None:
    """超过硬上限 → 构造期 ``ValidationError``（**显式**，不静默放宽）。"""
    with pytest.raises(ValidationError):
        RemoteExecutionSettings(**{field: value})
    # 硬上限值本身**可接受**（合法上界）。
    assert getattr(RemoteExecutionSettings(**{field: ceiling}), field) == ceiling


def test_hard_ceiling_rejects_non_positive() -> None:
    """非正值（0 / 负）→ 构造期报错。"""
    for field in ("max_concurrent_executions", "max_duration_seconds", "max_artifact_count"):
        with pytest.raises(ValidationError):
            RemoteExecutionSettings(**{field: 0})


def test_deploy_can_tighten_below_default() -> None:
    """部署可**收紧**（低于默认），且不报错。"""
    limits = RemoteExecutionSettings(
        max_concurrent_executions=1,
        max_pending_per_user=1,
        max_duration_seconds=60,
        max_disk_bytes=1024,
        max_artifact_bytes=1024,
        max_artifact_count=1,
    )

    assert limits.max_concurrent_executions == 1
    assert limits.max_duration_seconds == 60


# -- 执行 deadline / N9 连续性 ----------------------------------------------


def test_lease_and_heartbeat_constants() -> None:
    """心跳 30s / 租约 90s（设计 §2.9.1 冻结口径；deadline 依据）。"""
    assert DEFAULT_HEARTBEAT_SECONDS == 30
    assert DEFAULT_LEASE_SECONDS == 90


def test_heartbeat_keeps_attempt_alive_beyond_lease() -> None:
    """N9：心跳续租使在执行中的 Attempt 在超过单段租约后**仍不被**判为失联。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-nfr", attempt=1, now=T0)

    # 每 30s 心跳一次：跨越 90s 租约后仍活跃。
    for step in range(1, 6):
        recorder.heartbeat(record, now=T0 + timedelta(seconds=DEFAULT_HEARTBEAT_SECONDS * step))

    alive_at = T0 + timedelta(seconds=DEFAULT_HEARTBEAT_SECONDS * 5 - 1)
    assert recorder.is_lease_expired(record, now=alive_at) is False
    assert recorder.sweep_interrupted(now=alive_at) == []


def test_duration_recorded_on_finish() -> None:
    """执行时长（``duration_ms``）落库——deadline / 8h 上限的比较依据。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-nfr-2", attempt=1, now=T0)

    finished = recorder.finish(
        record, status=TaskStatus.SUCCESS.value, finished_at=T0 + timedelta(seconds=42)
    )

    assert finished.duration_ms == 42_000


# -- Sandbox 资源限额（进程级能力边界；真实隔离归 R5） ---------------------


def test_docker_sandbox_default_resource_limits() -> None:
    """Docker 沙箱默认 CPU / 内存 / PID 限额 + ``network=none``（默认强度）。"""
    params = inspect.signature(DockerSandboxProvider.__init__).parameters

    assert params["mem_limit"].default == "512m"
    assert params["nano_cpus"].default == 1_000_000_000  # == 1 CPU
    assert params["pids_limit"].default == 256
    assert params["read_only"].default is True

    provider = DockerSandboxProvider()
    assert provider.network == "none"
    assert provider.network_profile == "offline"


# -- N9 远程任务连续性（T2-63 扩展：中断有确定终态，不静默成功） --------------


def test_n9_expired_lease_interrupts_attempt() -> None:
    """租约过期 → Attempt 以 ``WORKER_INTERRUPTED`` 结束（**不**伪装成功）；未过期不中断。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-n9", attempt=1, now=T0)
    assert record.status == TaskStatus.RUNNING.value

    # 租约内 → 不中断（确定性）。
    assert recorder.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS - 1)) == []
    # 过期 → 标记中断（终态明确，可审计；非 SUCCESS）。
    swept = recorder.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1))
    assert [item.id for item in swept] == [record.id]
    assert swept[0].status == EXECUTION_STATUS_WORKER_INTERRUPTED
    assert swept[0].status != TaskStatus.SUCCESS.value


def test_n9_heartbeat_prevents_interrupt() -> None:
    """N9：心跳续租后，扫描窗口内 Attempt **不**被中断（断连 ≠ 取消/失败）。"""
    recorder = ExecutionRecorder(_FakeExecutionRepository())
    record = recorder.claim(task_id="task-n9b", attempt=1, now=T0)
    # 距离起点已远超单段租约，但心跳持续续租。
    recorder.heartbeat(record, now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 5))

    assert recorder.sweep_interrupted(now=T0 + timedelta(seconds=DEFAULT_LEASE_SECONDS + 6)) == []


# -- N10 远程工作区资源边界（T2-63 扩展） -----------------------------------


def test_n10_community_app_layer_caps_present() -> None:
    """Community 档：**应用层**边界限额在位（并发 / 时长 / 产物大小 / 磁盘）。

    Community 为**进程级 best-effort**（仅单用户 / 可信代码），**不**宣称 OS 级隔离（A-13）。
    """
    limits = RemoteExecutionSettings()

    for field in (
        "max_concurrent_executions",
        "max_duration_seconds",
        "max_artifact_bytes",
        "max_artifact_count",
        "max_disk_bytes",
    ):
        assert getattr(limits, field) >= 1, f"{field} 应用层边界缺失"


@pytest.mark.docker
def test_n10_docker_hard_quota_requires_docker_profile() -> None:
    """**N10 / #42 挂账**：Docker / Compose **硬配额**（CPU / 内存 / PID / 磁盘 / 网络）生效
    **仅**在 Docker 档验证；本机无 Docker → 缺运行时 ``skip``；``ASTRA_TEST_REQUIRE_DOCKER=1``
    （服务器 / CI）**必须**实跑（Manual 非豁免）。
    """
    if os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1":
        pytest.fail("Docker 运行时下必须实跑硬配额断言（T2-63 服务器验收）")
    pytest.skip("挂账待服务器：Docker / Compose 硬配额生效（N10 / #42）")
