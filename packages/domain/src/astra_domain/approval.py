"""审批域实体与状态机（设计 §2.10 / §2.11；W4 裁定 §3.4 / §6.4 #6；T2-26，**零迁移**）。

- :class:`ApprovalStatus`：``PENDING`` / ``APPROVED`` / ``REJECTED`` / ``EXPIRED``；
- :class:`Approval`：基础审批记录实体（``tool`` / ``mcp`` / ``workflow_node`` 三类主体）；
- 合法迁移表 :data:`APPROVAL_ALLOWED_TRANSITIONS`（非法迁移抛
  :class:`astra_core.DomainError`（``VALIDATION_ERROR``），口径仿 ``astra_task.states``）。

🔴 **零迁移**：``approval`` 表随迁移 ``0010``（2a）建立；本模块仅机制侧实体，**不建表**。
🔴 **零框架依赖**（纯 dataclass）——受
   ``test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode

from .entities.base import Entity

__all__ = [
    "ApprovalStatus",
    "APPROVAL_ALLOWED_TRANSITIONS",
    "APPROVAL_TERMINAL_STATUSES",
    "can_transition",
    "assert_transition",
    "Approval",
]


class ApprovalStatus(StrEnum):
    """审批状态（``approval.status``；设计 §2.10）。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


#: 合法状态迁移表（当前状态 → 允许的下一状态集合）。
#:
#: 仅 ``PENDING`` 可转移；决议（``APPROVED`` / ``REJECTED``）与过期（``EXPIRED``）均为**终态**。
APPROVAL_ALLOWED_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED}
    ),
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.REJECTED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
}

#: 终态集合（不可再转移）。
APPROVAL_TERMINAL_STATUSES: frozenset[ApprovalStatus] = frozenset(
    {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED}
)


def can_transition(current: ApprovalStatus, target: ApprovalStatus) -> bool:
    """判断 ``current → target`` 是否为合法转移。"""
    return target in APPROVAL_ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: ApprovalStatus, target: ApprovalStatus) -> None:
    """断言状态转移合法，否则抛 :class:`DomainError`。

    Raises:
        DomainError: 非法转移（``VALIDATION_ERROR``）。
    """
    if not can_transition(current, target):
        raise DomainError(
            f"非法审批状态转移：{current} → {target}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"from": str(current), "to": str(target)},
        )


def _coerce_status(value: str | ApprovalStatus) -> ApprovalStatus:
    """把字符串 / 枚举归一为 :class:`ApprovalStatus`。

    Raises:
        DomainError: 未知状态字面值（``VALIDATION_ERROR``）。
    """
    if isinstance(value, ApprovalStatus):
        return value
    try:
        return ApprovalStatus(str(value))
    except ValueError as exc:
        raise DomainError(
            f"未知审批状态：{value}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"status": str(value)},
        ) from exc


def _as_utc(value: datetime | None) -> datetime | None:
    """把可能为 naive（SQLite 回读）的时间归一到 UTC-aware，便于比较。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class Approval(Entity):
    """基础审批记录（设计 §2.10；表 ``approval`` 随 ``0010`` 建）。

    Attributes:
        subject_type: 主体类型（``tool`` / ``mcp`` / ``workflow_node``）。
        subject_ref: 主体引用（``workflow_node`` 时为 ``workflow_run_id:node_key``）。
        requested_by: 发起人用户标识（可空）。
        status: 审批状态字面值（:class:`ApprovalStatus`）。
        decided_by: 决议人用户标识（可空）。
        decided_at: 决议 / 过期时间（UTC，可空）。
        payload: 审批载荷（JSON）。
        expires_at: 到期时间（UTC；``None`` = 不过期）。
    """

    subject_type: str = ""
    subject_ref: str = ""
    requested_by: str | None = None
    status: str = ApprovalStatus.PENDING
    decided_by: str | None = None
    decided_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        """是否仍待决议（``PENDING``）。"""
        return _coerce_status(self.status) is ApprovalStatus.PENDING

    @property
    def is_expired(self) -> bool:
        """是否已过期（``EXPIRED``）。"""
        return _coerce_status(self.status) is ApprovalStatus.EXPIRED

    def is_due(self, *, now: datetime | None = None) -> bool:
        """判断是否到达到期时间（``expires_at <= now``；无到期时间 → ``False``）。"""
        if self.expires_at is None:
            return False
        current = _as_utc(now) or utcnow()
        expires = _as_utc(self.expires_at)
        return expires is not None and expires <= current

    def decide(
        self,
        *,
        status: str | ApprovalStatus,
        decided_by: str | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """作出决议（``PENDING → APPROVED | REJECTED``）。

        Raises:
            DomainError: 非法转移（``VALIDATION_ERROR``）。
        """
        target = _coerce_status(status)
        assert_transition(_coerce_status(self.status), target)
        self.status = str(target)
        self.decided_by = decided_by
        self.decided_at = now or utcnow()
        self.touch()
        return self

    def expire(self, *, now: datetime | None = None) -> Approval:
        """置为过期（``PENDING → EXPIRED``）。

        Raises:
            DomainError: 非法转移（``VALIDATION_ERROR``）。
        """
        assert_transition(_coerce_status(self.status), ApprovalStatus.EXPIRED)
        self.status = str(ApprovalStatus.EXPIRED)
        self.decided_by = None
        self.decided_at = now or utcnow()
        self.touch()
        return self
