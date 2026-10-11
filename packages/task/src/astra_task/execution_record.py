"""``task_execution`` 记录编排（**零 ORM**；W7 / T2-39；R2）。

:class:`ExecutionRecorder` 每次执行落一条 ``task_execution``（``attempt`` 从 1 起），
经**注入的** :class:`~astra_domain.TaskExecutionRepository` Protocol 使用持久化。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁）；
   ORM/SQL 落 ``astra_database.repositories.task_execution_repository``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from astra_common.time import utcnow
from astra_core import generate_id

from .states import TaskStatus

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_domain.repositories import TaskExecutionRepository

__all__ = ["TaskExecutionRecord", "ExecutionRecorder"]


@dataclass
class TaskExecutionRecord:
    """``task_execution`` 一行（零 ORM；映射 ORM ``task_execution``，§3.3 + §2.15.5）。

    Attributes:
        id: 执行记录标识（UUIDv7）。
        task_id: 归属任务标识。
        attempt: 尝试序号（**从 1 起**）。
        worker_id: 执行 worker 标识（可空）。
        status: 执行状态（``TaskStatus`` 词表）。
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
    """任务执行记录器（每次执行落一行 ``task_execution``，``attempt`` 自增）。"""

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
        attempt = self._next_attempt(task_id)
        record = TaskExecutionRecord(
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            status=TaskStatus.RUNNING.value,
            started_at=started_at if started_at is not None else utcnow(),
        )
        return self._repository.add(record)

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

    def _next_attempt(self, task_id: str) -> int:
        """计算下一次 ``attempt``（现有最大值 + 1；无则 1）。"""
        existing = self._repository.list_by_task(task_id)
        if not existing:
            return 1
        return max(record.attempt for record in existing) + 1
