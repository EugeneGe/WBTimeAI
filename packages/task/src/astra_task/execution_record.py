"""``task_execution`` 记录编排（**零 ORM**；W7 / T2-39；R2；R3 / T2-59）。

:class:`ExecutionRecorder` 每次执行落一条 ``task_execution``（``attempt`` 从 1 起），
经**注入的** :class:`~astra_domain.TaskExecutionRepository` Protocol 使用持久化。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁）；
   ORM/SQL 落 ``astra_database.repositories.task_execution_repository``。

🔴 **R3 / T2-59（C-5）Claim / heartbeat / lease / interrupted 语义**：

- **Claim**（:meth:`ExecutionRecorder.claim`）：远程 Attempt 以 ``(task_id, attempt)`` **原子领取**
  （DB ``UNIQUE(task_id, attempt)`` = ``uq_task_execution_task_attempt``，已由 ``0015`` 建）；
  ``attempt`` 由调用方（派发侧）**显式给定**以获得**幂等**语义（重投同 ``attempt`` 冲突）。
  **重复投递**由数据库唯一约束拦截——``repository.add`` 抛冲突，本模块**不**吞异常
  （冲突转「已领取→跳过」由 worker 接线层
  :class:`astra_worker.recovery.LeaseManager` 完成，**非静默**）。
- **heartbeat / lease**（:meth:`ExecutionRecorder.heartbeat` / :meth:`ExecutionRecorder.renew`）：
  Worker 每 :data:`DEFAULT_HEARTBEAT_SECONDS`（30s）写 ``heartbeat_at``，并把 ``lease_expires_at``
  续到 ``now + DEFAULT_LEASE_SECONDS``（90s）。租约过期表示 Worker **失联**，
  **不**表示执行未发生。
- **interrupted**（:meth:`ExecutionRecorder.sweep_interrupted` / :meth:`mark_interrupted`）：
  启动扫描时，``RUNNING`` 且租约过期的 Attempt 以
  :data:`EXECUTION_STATUS_WORKER_INTERRUPTED` 结束（**可显式重试**，**不**静默伪装成功 /
  自动重放）。该常量是**执行记录状态**（字符串），**不**入 ``TaskStatus`` 枚举（A-16 零新枚举）。
- **cancel**（:meth:`ExecutionRecorder.mark_cancelled`）：显式取消把执行记录置 ``CANCELLED``
  （终态）——``sweep_interrupted`` 仅扫描 ``RUNNING``，故已取消记录**不会**被误标 / 重放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from astra_common.time import ensure_utc, utcnow
from astra_core import generate_id

from .states import TaskStatus

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_domain.repositories import TaskExecutionRepository

__all__ = [
    "TaskExecutionRecord",
    "ExecutionRecorder",
    "EXECUTION_STATUS_WORKER_INTERRUPTED",
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_LEASE_SECONDS",
]

#: 执行记录状态：Worker 失联导致的中断（**执行态字符串**，非 ``TaskStatus`` 枚举；A-16 零新枚举）。
EXECUTION_STATUS_WORKER_INTERRUPTED = "WORKER_INTERRUPTED"

#: Worker 心跳周期（秒）：每周期更新 ``heartbeat_at`` 并续租（设计 §2.9.1）。
DEFAULT_HEARTBEAT_SECONDS = 30

#: Claim 租约时长（秒）：``lease_expires_at = now + DEFAULT_LEASE_SECONDS``（设计 §2.9.1）。
DEFAULT_LEASE_SECONDS = 90

#: Worker 失联中断的默认错误信息（``mark_interrupted`` 未显式给定 ``error`` 时使用）。
DEFAULT_INTERRUPTED_ERROR = "Worker 失联：Claim 租约过期（WORKER_INTERRUPTED）"


def _lease_delta(lease_seconds: int) -> int:
    """租约时长归一化（至少 1 秒，避免非法 / 零值）。"""
    return max(int(lease_seconds), 1)


@dataclass
class TaskExecutionRecord:
    """``task_execution`` 一行（零 ORM；映射 ORM ``task_execution``，§3.3 + §2.15.5）。

    Attributes:
        id: 执行记录标识（UUIDv7）。
        task_id: 归属任务标识。
        attempt: 尝试序号（**从 1 起**）。
        worker_id: 执行 worker 标识（可空）。
        status: 执行状态（``TaskStatus`` 词表；中断态额外用
            :data:`EXECUTION_STATUS_WORKER_INTERRUPTED`，**非**枚举成员）。
        started_at: 开始时间（可空）。
        finished_at: 结束时间（可空）。
        duration_ms: 持续毫秒（可空）。
        error: 错误信息（可空）。
        project_id: 归属 Project（可空；仅 Project 代码任务有值；``0018`` 加性列）。
        checkout_ref: 不透明 Attempt checkout 句柄（可空；**不含宿主绝对路径**；``0018``）。
        base_commit: Attempt 起始提交（Git OID，可空；``0018``）。
        result_commit: Attempt 结果提交（Git OID，可空；``0018``）。
        environment_digest: 环境摘要（SHA-256，可空；**不含 Secret**；``0018``）。
        artifact_refs: 产物 / Diff / 报告 / 日志的 Storage 引用（JSON，可空；``0018``）。
        heartbeat_at: Worker 心跳时刻（可空；``0018``）。
        lease_expires_at: Worker Claim 租约截止时刻（可空；``0018``）。

    🔴 **加性（R2 / T2-57，C-5）**：8 个远端执行字段默认 ``None``（历史记录合法）；
       行为语义（Claim / heartbeat / lease / interrupted）由 **T2-59** 在本模块追加，
       本任务**只**落字段映射（零 ORM，硬门禁保持）。
    """

    task_id: str = ""
    attempt: int = 1
    worker_id: str | None = None
    status: str = TaskStatus.RUNNING.value
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    id: str = field(default_factory=generate_id)
    # -- 0018 远端执行加性字段（默认 None；历史记录合法） ------------------------
    project_id: str | None = None
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None
    artifact_refs: dict[str, Any] | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None


class ExecutionRecorder:
    """任务执行记录器（每次执行落一行 ``task_execution``，``attempt`` 自增）。

    🔴 **零 ORM**：仅经注入的 ``TaskExecutionRepository`` Protocol 使用持久化。
    """

    def __init__(self, repository: TaskExecutionRepository) -> None:
        """构造。

        Args:
            repository: 注入的 ``TaskExecutionRepository`` Protocol。
        """
        self._repository = repository

    @property
    def repository(self) -> TaskExecutionRepository:
        """返回注入的仓储（供测试 / 组合根检视）。"""
        return self._repository

    def begin(
        self, *, task_id: str, worker_id: str | None = None, started_at: datetime | None = None
    ) -> TaskExecutionRecord:
        """开始一次执行（``attempt`` 取该 task 现有记录最大值 + 1，**首次为 1**）。

        Returns:
            已持久化的 :class:`TaskExecutionRecord`。
        """
        attempt = self.next_attempt(task_id)
        record = TaskExecutionRecord(
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            status=TaskStatus.RUNNING.value,
            started_at=started_at if started_at is not None else utcnow(),
        )
        return self._repository.add(record)

    # -- T2-59：Claim / heartbeat / lease / interrupted -----------------------

    def claim(
        self,
        *,
        task_id: str,
        attempt: int,
        worker_id: str | None = None,
        started_at: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        project_id: str | None = None,
        checkout_ref: str | None = None,
        base_commit: str | None = None,
        environment_digest: str | None = None,
        artifact_refs: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """**原子领取**一次远程 Attempt 执行（DB ``UNIQUE(task_id, attempt)`` 保证单执行者）。

        ``attempt`` **由调用方显式给定**（派发侧决定，非本方法自增），以获**幂等**语义：重复
        投递同 ``(task_id, attempt)`` 由数据库唯一约束拦截，``repository.add`` 抛冲突
        （``IntegrityError``），本方法**不吞异常**（由 worker 接线层转「已领取→跳过」，非静默）。

        Args:
            task_id: 归属任务标识。
            attempt: 尝试序号（**从 1 起**；显式给定，保证幂等）。
            worker_id: 执行 worker 标识（可空）。
            started_at: 开始时刻（可空；缺省取 ``now``）。
            lease_seconds: 租约时长（秒；默认 :data:`DEFAULT_LEASE_SECONDS`）。
            project_id: 归属 Project（可空）。
            checkout_ref: 不透明 Attempt checkout 句柄（可空）。
            base_commit: Attempt 起始提交（可空）。
            environment_digest: 环境摘要（可空；**不含 Secret**）。
            artifact_refs: 产物引用（可空）。
            now: 当前时刻（可空；测试可注入 fake clock）。

        Returns:
            已持久化（``RUNNING``、含心跳 / 租约）的 :class:`TaskExecutionRecord`。

        Raises:
            IntegrityError: ``(task_id, attempt)`` 已存在（重复投递；由 DB 唯一约束抛出）。
        """
        lease_seconds = _lease_delta(lease_seconds)
        started = started_at if started_at is not None else (now if now is not None else utcnow())
        heartbeat_at = started
        record = TaskExecutionRecord(
            task_id=task_id,
            attempt=int(attempt),
            worker_id=worker_id,
            status=TaskStatus.RUNNING.value,
            started_at=started,
            project_id=project_id,
            checkout_ref=checkout_ref,
            base_commit=base_commit,
            environment_digest=environment_digest,
            artifact_refs=artifact_refs,
            heartbeat_at=heartbeat_at,
            lease_expires_at=heartbeat_at + timedelta(seconds=lease_seconds),
        )
        return self._repository.add(record)

    def heartbeat(
        self,
        record: TaskExecutionRecord,
        *,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> TaskExecutionRecord:
        """写心跳并续租（``heartbeat_at = now``；``lease_expires_at = now + lease``）。

        持久化并返回。
        """
        ts = now if now is not None else utcnow()
        record.heartbeat_at = ts
        record.lease_expires_at = ts + timedelta(seconds=_lease_delta(lease_seconds))
        return self._repository.update(record)

    def renew(
        self,
        record: TaskExecutionRecord,
        *,
        now: datetime | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> TaskExecutionRecord:
        """**显式续租**（等价于一次心跳：刷新 ``heartbeat_at`` 并顺延 ``lease_expires_at``）。

        供 worker 的续租接线使用；语义与 :meth:`heartbeat` 完全一致（同一实现，仅语义命名）。
        """
        return self.heartbeat(record, now=now, lease_seconds=lease_seconds)

    def mark_interrupted(
        self,
        record: TaskExecutionRecord,
        *,
        now: datetime | None = None,
        error: str | None = None,
    ) -> TaskExecutionRecord:
        """把单条执行记录以 :data:`EXECUTION_STATUS_WORKER_INTERRUPTED` 结束（**非静默**）。

        用于启动扫描（:meth:`sweep_interrupted`）与显式中断；**不**伪装成功，**不**自动重放。
        """
        return self.finish(
            record,
            status=EXECUTION_STATUS_WORKER_INTERRUPTED,
            error=error if error is not None else DEFAULT_INTERRUPTED_ERROR,
            finished_at=now,
        )

    def mark_cancelled(
        self,
        record: TaskExecutionRecord,
        *,
        now: datetime | None = None,
        error: str | None = None,
    ) -> TaskExecutionRecord:
        """把执行记录置 ``CANCELLED``（终态；显式取消落库，供「断连≠取消」的取消传播断言）。"""
        return self.finish(record, status=TaskStatus.CANCELLED.value, error=error, finished_at=now)

    def is_active(self, record: TaskExecutionRecord) -> bool:
        """执行记录是否仍在执行（``status == RUNNING``）。"""
        return record.status == TaskStatus.RUNNING.value

    def is_lease_expired(self, record: TaskExecutionRecord, *, now: datetime | None = None) -> bool:
        """该记录的 Claim 租约是否已过期（``now >= lease_expires_at``）。

        ``lease_expires_at`` 为空（历史 / 非远程记录）→ **不**判定过期（返回 ``False``）。
        """
        if record.lease_expires_at is None:
            return False
        ts = ensure_utc(now) if now is not None else utcnow()
        return ensure_utc(record.lease_expires_at) <= ts

    def sweep_interrupted(self, *, now: datetime | None = None) -> list[TaskExecutionRecord]:
        """启动扫描：``RUNNING`` 且租约过期的 Attempt → ``WORKER_INTERRUPTED``。

        Returns:
            本次被标记为中断的执行记录列表（**保序**，按仓储返回顺序）。
        """
        ts = now if now is not None else utcnow()
        running = self._repository.list(status=TaskStatus.RUNNING.value)
        return [
            self.mark_interrupted(record, now=ts)
            for record in running
            if self.is_lease_expired(record, now=ts)
        ]

    def finish(
        self,
        record: TaskExecutionRecord,
        *,
        status: str = TaskStatus.SUCCESS.value,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> TaskExecutionRecord:
        """结束一次执行（写终态 / 耗时 / 错误），持久化并返回。"""
        record.status = status
        record.error = error
        record.finished_at = finished_at if finished_at is not None else utcnow()
        if record.started_at is not None:
            delta = record.finished_at - record.started_at
            record.duration_ms = max(int(delta.total_seconds() * 1000), 0)
        return self._repository.update(record)

    def next_attempt(self, task_id: str) -> int:
        """计算下一次 ``attempt``（现有最大值 + 1；无则 1）。"""
        existing = self._repository.list_by_task(task_id)
        if not existing:
            return 1
        return max(record.attempt for record in existing) + 1
