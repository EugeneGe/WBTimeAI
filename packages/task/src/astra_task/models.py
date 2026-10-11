"""Task 领域模型（状态机驱动；``task_id`` 默认 ``generate_id``）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode, generate_id

from .states import TaskStatus, assert_transition

__all__ = ["Task"]


@dataclass
class Task:
    """任务领域模型。

    Attributes:
        task_id: 任务唯一标识（UUIDv7，默认经 ``generate_id`` 生成）。
        tenant_id: 所属租户。
        workspace_id: 所属 Workspace（可空）。
        type: 任务类型（如 ``data.sync`` / ``agent.run``）。
        status: 当前状态（默认 ``CREATED``）。
        priority: 优先级（默认 0）。
        execution_mode: 执行模式（``INLINE`` / ``QUEUED``，默认 ``INLINE``；设计 §2.11）。
        payload: 任务载荷。
        result: 任务结果。
        created_at: 创建时间（UTC）。
        updated_at: 最近更新时间（UTC）。
        error: 失败原因（``fail`` 时写入）。
    """

    task_id: str = field(default_factory=generate_id)
    tenant_id: str | None = None
    workspace_id: str | None = None
    type: str = ""
    status: TaskStatus = TaskStatus.CREATED
    priority: int = 0
    execution_mode: str = "INLINE"
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    error: str | None = None

    # -- 状态机操作 ---------------------------------------------------------

    def start_inline(self) -> None:
        """内联执行开始：``CREATED → RUNNING``（**跳过 ``PENDING``**，设计 §2.11）。"""
        self._transition(TaskStatus.RUNNING)

    def enqueue(self) -> None:
        """入队：``CREATED → PENDING``。"""
        self._transition(TaskStatus.PENDING)

    def start(self) -> None:
        """开始执行（QUEUED 路径）：``PENDING → RUNNING``。

        语义不变：仅允许从 ``PENDING`` 起转。内联路径请用 :meth:`start_inline`。
        """
        if self.status is not TaskStatus.PENDING:
            raise DomainError(
                f"非法任务状态转移：{self.status} → {TaskStatus.RUNNING}"
                "（QUEUED 路径须从 PENDING 起转）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"from": str(self.status), "to": str(TaskStatus.RUNNING)},
            )
        self._transition(TaskStatus.RUNNING)

    def succeed(self, result: dict[str, Any] | None = None) -> None:
        """成功：``RUNNING → SUCCESS``。"""
        self._transition(TaskStatus.SUCCESS)
        self.result = result if result is not None else self.result

    def fail(self, error: str | None = None, result: dict[str, Any] | None = None) -> None:
        """失败：``RUNNING | PENDING → FAILED``。"""
        self._transition(TaskStatus.FAILED)
        self.error = error
        if result is not None:
            self.result = result

    def cancel(self) -> None:
        """取消：``CREATED | PENDING | RUNNING → CANCELLED``。"""
        self._transition(TaskStatus.CANCELLED)

    def _transition(self, target: TaskStatus) -> None:
        assert_transition(self.status, target)
        self.status = target
        self.updated_at = utcnow()

    # -- 便捷属性 -----------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """是否为终态。"""
        from .states import TERMINAL_STATUSES

        return self.status in TERMINAL_STATUSES
