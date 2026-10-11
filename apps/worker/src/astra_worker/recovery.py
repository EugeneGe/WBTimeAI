"""远程 Attempt 租约 / 启动恢复 / 显式重试接线（R3 / T2-59；设计 §2.9.1）。

:class:`LeaseManager` 是 worker 侧对 :class:`astra_task.ExecutionRecorder` 的**接线层**：

- :meth:`LeaseManager.claim` —— 远程 Attempt 的**原子领取**（DB ``UNIQUE(task_id, attempt)``）。
  **重复投递**（Redis 重投）命中唯一约束时捕获 ``IntegrityError`` 并转「已领取 → 跳过」，
  **非静默**（记 WARNING）；由此保证「重投**不**产生并发 Attempt」。
- :meth:`LeaseManager.heartbeat` / :meth:`LeaseManager.finish` —— 续租（30s 心跳 / 90s 租约）与
  终态落库（含 ``result_commit`` / ``environment_digest`` / ``artifact_refs``）。
- :meth:`LeaseManager.sweep_interrupted` —— **启动扫描**：``RUNNING`` 且租约过期 →
  ``WORKER_INTERRUPTED``（**不静默重放 / 不伪装成功**）。
- :meth:`LeaseManager.recover_on_startup` —— 启动恢复编排：先标记过期 ``RUNNING``，再把持久化
  ``PENDING`` **重新投递**（重投经注入的 ``dispatch``，非本模块直连队列）。
- :meth:`LeaseManager.plan_explicit_retry` —— **显式重试**：为中断 / 失败 Attempt 规划下一
  ``attempt``（**显式**，非自动重放）。

🔴 **执行体 / 队列正交（R-23）**：本模块**不 import** 具体队列 / ORM 实现；仓储经**注入**使用。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astra_common.time import utcnow
from astra_task import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    ExecutionRecorder,
    TaskExecutionRecord,
    TaskStatus,
)
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_task import Task

__all__ = [
    "ClaimOutcome",
    "RecoveryReport",
    "LeaseManager",
    "TaskStatusReader",
]

_logger = logging.getLogger("astra_worker.recovery")

#: 「已领取 → 跳过」原因码（重复投递；**非**执行失败）。
REASON_ALREADY_CLAIMED = "already_claimed"

#: 「已领取」原因码（首次领取成功）。
REASON_CLAIMED = "claimed"


@runtime_checkable
class TaskStatusReader(Protocol):
    """按状态读取任务的最小契约（供启动恢复取 ``PENDING``；由组合根注入）。"""

    def list_by_status(self, status: str) -> list[Task]:
        """列出某状态的全部任务。"""
        ...


@dataclass(frozen=True)
class ClaimOutcome:
    """一次 Claim 的结果（**非静默**：区分「新领取」与「已领取 → 跳过」）。

    Attributes:
        claimed: 是否**本次**成功领取（``False`` = 重复投递，已由他者领取）。
        record: 领取到的执行记录（``claimed=False`` 时为既有的 **既有**记录，可空）。
        reason: 结果原因码（``claimed`` / ``already_claimed``）。
    """

    claimed: bool
    record: TaskExecutionRecord | None
    reason: str = REASON_CLAIMED


@dataclass(frozen=True)
class RecoveryReport:
    """启动恢复结果（**留证**：哪些执行被中断、哪些任务被重投）。

    Attributes:
        interrupted: 被标记 ``WORKER_INTERRUPTED`` 的执行记录 id（保序）。
        redelivered: 被重新投递的 ``PENDING`` 任务 id（保序）。
    """

    interrupted: tuple[str, ...] = ()
    redelivered: tuple[str, ...] = ()


@dataclass
class LeaseManager:
    """远程 Attempt 租约 / 恢复 / 显式重试接线（worker 侧）。

    Attributes:
        recorder: 注入的执行记录器（:class:`astra_task.ExecutionRecorder`）。
        heartbeat_seconds: 心跳周期（秒；默认 30）。
        lease_seconds: 租约时长（秒；默认 90）。
    """

    recorder: ExecutionRecorder
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    clock: Callable[[], datetime] = field(default=utcnow)

    # -- Claim --------------------------------------------------------------

    def claim(
        self,
        *,
        task_id: str,
        attempt: int,
        worker_id: str | None = None,
        project_id: str | None = None,
        checkout_ref: str | None = None,
        base_commit: str | None = None,
        environment_digest: str | None = None,
        artifact_refs: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ClaimOutcome:
        """原子领取一次远程 Attempt；重复投递 → 「已领取 → 跳过」（**非静默**）。

        Args:
            task_id: 归属任务标识。
            attempt: 尝试序号（**显式**给定，保证幂等）。
            worker_id: 执行 worker 标识（可空）。
            project_id: 归属 Project（可空）。
            checkout_ref: 不透明 checkout 句柄（可空）。
            base_commit: Attempt 起始提交（可空）。
            environment_digest: 环境摘要（可空；**不含 Secret**）。
            artifact_refs: 产物引用（可空）。
            now: 当前时刻（可空；测试可注入 fake clock）。

        Returns:
            :class:`ClaimOutcome`——``claimed=True`` 为新领取；``claimed=False`` 为重复投递
            （``reason="already_claimed"``，附既有记录）。
        """
        ts = now if now is not None else self.clock()
        try:
            record = self.recorder.claim(
                task_id=task_id,
                attempt=attempt,
                worker_id=worker_id,
                started_at=ts,
                lease_seconds=self.lease_seconds,
                project_id=project_id,
                checkout_ref=checkout_ref,
                base_commit=base_commit,
                environment_digest=environment_digest,
                artifact_refs=artifact_refs,
                now=ts,
            )
        except IntegrityError:
            existing = self.recorder.repository.get_by_attempt(task_id, attempt)
            _logger.warning(
                "worker.claim_conflict",
                extra={
                    "handler": "remote.agent_run",
                    "task_id": task_id,
                    "attempt": attempt,
                    "execution_id": getattr(existing, "id", None),
                },
            )
            return ClaimOutcome(claimed=False, record=existing, reason=REASON_ALREADY_CLAIMED)
        return ClaimOutcome(claimed=True, record=record, reason=REASON_CLAIMED)

    # -- 租约续期 / 终态 -----------------------------------------------------

    def heartbeat(
        self, record: TaskExecutionRecord, *, now: datetime | None = None
    ) -> TaskExecutionRecord:
        """续租（写 ``heartbeat_at`` + 顺延 ``lease_expires_at``），持久化并返回。"""
        ts = now if now is not None else self.clock()
        return self.recorder.heartbeat(record, now=ts, lease_seconds=self.lease_seconds)

    def finish(
        self,
        record: TaskExecutionRecord,
        *,
        status: str | None = None,
        result_commit: str | None = None,
        environment_digest: str | None = None,
        artifact_refs: dict[str, Any] | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """写终态并落结果引用（``result_commit`` / ``environment_digest`` / ``artifact_refs``）。

        ``status`` 为空时取 ``SUCCESS``。落库前先把结果字段写到记录上，再由
        :meth:`astra_task.ExecutionRecorder.finish` 一并持久化。
        """
        ts = now if now is not None else self.clock()
        if result_commit is not None:
            record.result_commit = result_commit
        if environment_digest is not None:
            record.environment_digest = environment_digest
        if artifact_refs is not None:
            record.artifact_refs = artifact_refs
        return self.recorder.finish(
            record,
            status=status if status is not None else TaskStatus.SUCCESS.value,
            error=error,
            finished_at=ts,
        )

    def fail(
        self,
        record: TaskExecutionRecord,
        *,
        error: str,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """把执行记录置 ``FAILED``（**非静默**：写错误信息），持久化并返回。"""
        return self.finish(record, status=TaskStatus.FAILED.value, error=error, now=now)

    # -- 启动扫描 / 恢复 -----------------------------------------------------

    def sweep_interrupted(self, *, now: datetime | None = None) -> list[TaskExecutionRecord]:
        """启动扫描：``RUNNING`` 且租约过期的 Attempt → ``WORKER_INTERRUPTED``（**非静默**）。

        每条被中断的记录记 WARNING（留证）；**不**自动重放、**不**伪装成功。
        """
        ts = now if now is not None else self.clock()
        interrupted = self.recorder.sweep_interrupted(now=ts)
        for record in interrupted:
            _logger.warning(
                "worker.lease_expired_interrupted",
                extra={
                    "handler": "remote.agent_run",
                    "task_id": record.task_id,
                    "attempt": record.attempt,
                    "execution_id": record.id,
                },
            )
        return interrupted

    def recover_on_startup(
        self,
        *,
        task_repository: TaskStatusReader,
        dispatch: Callable[[Task], Any],
        now: datetime | None = None,
    ) -> RecoveryReport:
        """启动恢复：① 过期 ``RUNNING`` → ``WORKER_INTERRUPTED``；② 持久化 ``PENDING`` 重投。

        **顺序**：先标记过期执行（避免被误当作在跑），再重投 ``PENDING``。重投经**注入**的
        ``dispatch``（**不**直连队列），每条重投任务记 INFO（留证）。

        Args:
            task_repository: 按状态读取任务的仓储（``list_by_status``；组合根注入）。
            dispatch: 重投回调（如 ``lambda task: queue.enqueue(make_message(...))``）。
            now: 当前时刻（可空；测试可注入 fake clock）。

        Returns:
            :class:`RecoveryReport`（哪些执行被中断、哪些任务被重投）。
        """
        ts = now if now is not None else self.clock()
        interrupted = self.sweep_interrupted(now=ts)
        redelivered: list[str] = []
        for task in task_repository.list_by_status(TaskStatus.PENDING.value):
            dispatch(task)
            redelivered.append(task.task_id)
            _logger.info(
                "worker.pending_redelivered",
                extra={"task_id": task.task_id, "type": task.type},
            )
        return RecoveryReport(
            interrupted=tuple(record.id for record in interrupted),
            redelivered=tuple(redelivered),
        )

    # -- 显式重试 -----------------------------------------------------------

    def plan_explicit_retry(self, *, task_id: str) -> int:
        """为中断 / 失败 Attempt 规划下一 ``attempt``（**显式重试**，非自动重放）。

        Returns:
            下一个 ``attempt`` 编号（现有最大值 + 1）。调用方据此构造重投消息
            （``tasks.make_message(...)``）并显式入队——一切重试均**显式**、可审计。
        """
        return self.recorder.next_attempt(task_id)
