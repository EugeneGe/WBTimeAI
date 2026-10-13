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
from astra_core import DomainError, ErrorCode
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
    "REASON_ALREADY_CLAIMED",
    "REASON_CLAIMED",
    "REASON_CONCURRENCY_LIMITED",
]

_logger = logging.getLogger("astra_worker.recovery")

#: 「已领取 → 跳过」原因码（重复投递；**非**执行失败）。
REASON_ALREADY_CLAIMED = "already_claimed"

#: 「已领取」原因码（首次领取成功）。
REASON_CLAIMED = "claimed"

#: 「并发受限 → 跳过」原因码（R5 补全轮 F8b：活跃执行数达 ``max_concurrent_executions``；
#: **非**执行失败，**非静默**——处理器据此返回稳定非静默状态）。
REASON_CONCURRENCY_LIMITED = "concurrency_limited"


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
        claimed: 是否**本次**成功领取（``False`` = 重复投递 / 并发受限，已由他者领取或超限）。
        record: 领取到的执行记录（``claimed=False`` 时为既有的 **既有**记录；
            并发受限 / 首次冲突无 → ``None``）。
        reason: 结果原因码（``claimed`` / ``already_claimed`` / ``concurrency_limited``）。
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
        max_concurrent_executions: 并发上限（可空；R5 补全轮 F8b——``claim`` 前统计「RUNNING 且
            租约未过期」数量，``>=`` 上限 → ``claimed=False`` / ``concurrency_limited``；
            **缺省 ``None`` = 不启用**该检查，向后兼容）。
        max_artifact_count: 单次执行 artifact 数量上限（可空；R5 补全轮 F8d）。
        max_artifact_bytes: 单次执行 artifact 累计字节上限（可空；R5 补全轮 F8d）。
        max_disk_bytes: 单次执行 workspace 磁盘占用上限（可空；A-3 磁盘强制；缺省 ``None`` =
            不启用磁盘判定）。
        disk_enforce: 是否**强制**执行磁盘上限（A-3；默认 ``True``；``False`` 时仅告警不终止）。
        disk_high_watermark_ratio: 磁盘告警水位比例（A-3；可空；``used > ratio * max_disk_bytes``
            → 告警事件，**不**终止）。
        clock: 时钟（可注入 fake clock）。
    """

    recorder: ExecutionRecorder
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    max_concurrent_executions: int | None = None
    max_artifact_count: int | None = None
    max_artifact_bytes: int | None = None
    max_disk_bytes: int | None = None
    disk_enforce: bool = True
    disk_high_watermark_ratio: float | None = None
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
            （``reason="already_claimed"``，附既有记录）或**并发受限**
            （``reason="concurrency_limited"``，无记录；R5 补全轮 F8b）。
        """
        ts = now if now is not None else self.clock()
        # F8b（防御性并发检查）：活跃（RUNNING 且租约未过期）数达上限 → 不领取（非静默）。
        if self.max_concurrent_executions is not None:
            active = self._count_active(now=ts)
            if active >= self.max_concurrent_executions:
                _logger.warning(
                    "worker.concurrency_limited",
                    extra={
                        "handler": "remote.agent_run",
                        "task_id": task_id,
                        "attempt": attempt,
                        "active": active,
                        "limit": self.max_concurrent_executions,
                    },
                )
                return ClaimOutcome(claimed=False, record=None, reason=REASON_CONCURRENCY_LIMITED)
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

    def _count_active(self, *, now: datetime) -> int:
        """统计「``RUNNING`` 且租约**未**过期」的执行数（F8b 并发上限依据）。

        🔴 复用既有 ``repository.list(status=RUNNING)`` + :meth:`ExecutionRecorder.is_lease_expired`
           过滤（**不**新增仓储 SQL 方法）——保持注入 Protocol 不变（公开签名零改）；对 fake
           repo / 真实 ``SqlTaskExecutionRepository`` 同构可用。
        """
        running = self.recorder.repository.list(status=TaskStatus.RUNNING.value)
        return sum(1 for record in running if not self.recorder.is_lease_expired(record, now=now))

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

        🔴 **artifact 上限（R5 补全轮 F8d；N10）**：落 ``artifact_refs`` **前**累加 count 与
           size（各引用 dict 的 ``size`` 字段）；超 ``max_artifact_count`` / ``max_artifact_bytes``
           → **拒绝落库**该产物引用 + **稳定失败终态**（``FAILED``，错误含
           ``RESOURCE_LIMIT_EXCEEDED``）并**抛** :class:`DomainError`（``RESOURCE_LIMIT_EXCEEDED``
           → 429，**非静默**；调用方据此感知）。

        Raises:
            DomainError: ``artifact_refs`` 数量 / 累计字节超上限（``RESOURCE_LIMIT_EXCEEDED``）。
        """
        ts = now if now is not None else self.clock()
        limit_error = self._artifact_limit_error(artifact_refs)
        if limit_error is not None:
            # 拒绝落库超限产物（artifact_refs 不写入），并以稳定失败终态收尾（非静默）。
            record.artifact_refs = None
            self.recorder.finish(
                record,
                status=TaskStatus.FAILED.value,
                error=limit_error,
                finished_at=ts,
            )
            raise DomainError(
                "远程执行产物超限（拒绝落库）",
                code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                status_code=429,
                data={
                    "scope": "artifact",
                    "count": len(artifact_refs or {}),
                    "max_artifact_count": self.max_artifact_count,
                    "max_artifact_bytes": self.max_artifact_bytes,
                },
            )
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

    def _artifact_limit_error(self, artifact_refs: dict[str, Any] | None) -> str | None:
        """artifact 上限校验（F8d）：超限返回稳定错误串（含码）；否则 ``None``。

        ``size`` 取各引用 dict 的 ``size`` 字段（缺失 / 非数值 → 按 0 计）；恰在上限内（``==``）
        **通过**（仅 ``>`` 判超）。
        """
        if not artifact_refs:
            return None
        refs = artifact_refs or {}
        if self.max_artifact_count is not None and len(refs) > self.max_artifact_count:
            return (
                f"{ErrorCode.RESOURCE_LIMIT_EXCEEDED}: artifact 数量 {len(refs)} "
                f"超过上限 {self.max_artifact_count}"
            )
        if self.max_artifact_bytes is not None:
            total = 0
            for value in refs.values():
                if isinstance(value, dict):
                    total += int(value.get("size") or 0)
            if total > self.max_artifact_bytes:
                return (
                    f"{ErrorCode.RESOURCE_LIMIT_EXCEEDED}: artifact 累计字节 {total} "
                    f"超过上限 {self.max_artifact_bytes}"
                )
        return None

    def fail(
        self,
        record: TaskExecutionRecord,
        *,
        error: str,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """把执行记录置 ``FAILED``（**非静默**：写错误信息），持久化并返回。"""
        return self.finish(record, status=TaskStatus.FAILED.value, error=error, now=now)

    # -- 执行中强制打断 / 取消（A-2） ----------------------------------------

    def interrupt(
        self,
        record: TaskExecutionRecord,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """**执行中强制打断**：把 ``RUNNING`` 记录以 ``WORKER_INTERRUPTED`` 结束（**非静默**）。

        A-2：用于「超 ``max_duration_seconds``」或「worker 侧显式中断」——终态为
        :data:`astra_task.EXECUTION_STATUS_WORKER_INTERRUPTED`（**不**伪装成功），
        写 ``reason`` 为 ``error`` 并落 ``finished_at``（据此**回收租约 / 释放资源位**：
        记录离开 ``RUNNING`` 后不再计入 :meth:`_count_active` 活跃数）。

        Args:
            record: 待中断的执行记录（须为当前 ``RUNNING``）。
            reason: 中断原因（写入 ``error``；如 ``deadline_exceeded`` / ``interrupted``）。
            now: 当前时刻（可空；测试可注入 fake clock）。

        Returns:
            以 ``WORKER_INTERRUPTED`` 结束并持久化的记录。
        """
        ts = now if now is not None else self.clock()
        updated = self.recorder.mark_interrupted(record, now=ts, error=reason)
        _logger.warning(
            "worker.interrupted",
            extra={
                "handler": "remote.agent_run",
                "task_id": record.task_id,
                "attempt": record.attempt,
                "execution_id": record.id,
                "reason": reason,
            },
        )
        return updated

    def cancel(
        self,
        record: TaskExecutionRecord,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> TaskExecutionRecord:
        """**显式取消**：把 ``RUNNING`` 记录以 ``CANCELLED`` 结束（**非静默**；设计 §2.9.1）。

        取消与「失联中断」语义区分：显式取消落 ``CANCELLED``（终态），
        ``sweep_interrupted`` **不**再扫描（已非 ``RUNNING``），**不**伪装成功。
        """
        ts = now if now is not None else self.clock()
        updated = self.recorder.mark_cancelled(record, now=ts, error=reason)
        _logger.warning(
            "worker.cancelled",
            extra={
                "handler": "remote.agent_run",
                "task_id": record.task_id,
                "attempt": record.attempt,
                "execution_id": record.id,
                "reason": reason,
            },
        )
        return updated

    # -- 磁盘占用强制 + 水位告警（A-3） --------------------------------------

    def enforce_disk(
        self,
        record: TaskExecutionRecord,
        *,
        used_bytes: int,
        now: datetime | None = None,
    ) -> int:
        """执行期**磁盘占用**强制 + 水位告警（A-3；**不伪造**）。

        - ``max_disk_bytes`` 已配置且 ``disk_enforce`` 为真、``used_bytes > max_disk_bytes`` →
          拒绝（以稳定失败终态 ``FAILED`` + ``RESOURCE_LIMIT_EXCEEDED`` 收尾）并**抛**
          :class:`DomainError`（``RESOURCE_LIMIT_EXCEEDED`` → 429，**非静默**）；
        - 否则若配置了 ``disk_high_watermark_ratio`` 且 ``used_bytes > ratio * max_disk_bytes``
          → 记 WARNING **告警事件**（``worker.disk_high_watermark``），**不**终止。

        恰在上限内（``== max_disk_bytes``）**通过**（仅 ``>`` 判超；零误杀）。

        Args:
            record: 当前执行记录（超限时以其落失败终态）。
            used_bytes: 本次统计到的 workspace 占用字节数。
            now: 当前时刻（可空）。

        Returns:
            ``used_bytes``（透传，便于调用方记录）。

        Raises:
            DomainError: ``used_bytes > max_disk_bytes`` 且强制启用（``RESOURCE_LIMIT_EXCEEDED``）。
        """
        ts = now if now is not None else self.clock()
        limit = self.max_disk_bytes
        if limit is not None and limit > 0:
            if self.disk_enforce and used_bytes > limit:
                self.recorder.finish(
                    record,
                    status=TaskStatus.FAILED.value,
                    error=(
                        f"{ErrorCode.RESOURCE_LIMIT_EXCEEDED}: workspace 磁盘占用 {used_bytes} "
                        f"超过上限 {limit}"
                    ),
                    finished_at=ts,
                )
                _logger.warning(
                    "worker.disk_limit_exceeded",
                    extra={
                        "handler": "remote.agent_run",
                        "task_id": record.task_id,
                        "attempt": record.attempt,
                        "execution_id": record.id,
                        "used_bytes": used_bytes,
                        "limit": limit,
                    },
                )
                raise DomainError(
                    "远程执行 workspace 磁盘占用超限（终止执行）",
                    code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                    status_code=429,
                    data={"scope": "disk", "used_bytes": used_bytes, "max_disk_bytes": limit},
                )
            ratio = self.disk_high_watermark_ratio
            if ratio is not None and used_bytes > ratio * limit:
                _logger.warning(
                    "worker.disk_high_watermark",
                    extra={
                        "handler": "remote.agent_run",
                        "task_id": record.task_id,
                        "attempt": record.attempt,
                        "execution_id": record.id,
                        "used_bytes": used_bytes,
                        "watermark_bytes": int(ratio * limit),
                        "ratio": ratio,
                    },
                )
        return used_bytes

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
