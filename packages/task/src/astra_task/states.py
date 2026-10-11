"""Task 状态机（设计 §2.6 / §2.11）。

两条路径（``I-P1-12``）：

- **QUEUED**：``CREATED → PENDING → RUNNING → SUCCESS | FAILED | CANCELLED``；
- **INLINE**：``CREATED → RUNNING → 终态``（**跳过 ``PENDING``**）。

非法转移抛 :class:`astra_core.DomainError`（``VALIDATION_ERROR``）。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import DomainError, ErrorCode

__all__ = [
    "TaskStatus",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "can_transition",
    "assert_transition",
]


class TaskStatus(StrEnum):
    """任务状态。"""

    CREATED = "CREATED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: 合法状态转移表（当前状态 → 允许的下一状态集合）。
#:
#: ``CREATED → RUNNING`` 为 **INLINE 路径**（跳过 ``PENDING``，设计 §2.11）。
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.SUCCESS: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

#: 终态集合（不可再转移）。
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """判断 ``current → target`` 是否为合法转移。"""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    """断言状态转移合法，否则抛 :class:`DomainError`。

    Raises:
        DomainError: 非法转移（``VALIDATION_ERROR``）。
    """
    if not can_transition(current, target):
        raise DomainError(
            f"非法任务状态转移：{current} → {target}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"from": str(current), "to": str(target)},
        )
