"""Approval 审批事件（Phase 2 · W3 / T2-16；设计 §2.11；裁定 §6.1）。

2 类事件，**继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02）：

- ``ApprovalRequested``：``approval.requested`` —— 审批发起；
- ``ApprovalDecided``：``approval.decided`` —— 审批结论。

🔴 2a **先定义类型**，2b 消费触发（审批机制接线归 2b T2-26，零迁移）；
   本模块**只定义事件类型**，``EventBus`` Protocol 不变（C-02）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["ApprovalRequested", "ApprovalDecided"]


@dataclass
class ApprovalRequested(DomainEvent):
    """审批发起事件（``approval.requested``）。"""

    type: ClassVar[str] = "approval.requested"

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        subject_type: str,
        subject_ref: str,
        requested_by: str | None = None,
    ) -> ApprovalRequested:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "approval_id": approval_id,
            "subject_type": subject_type,
            "subject_ref": subject_ref,
        }
        if requested_by is not None:
            payload["requested_by"] = requested_by
        return cls(payload=payload)


@dataclass
class ApprovalDecided(DomainEvent):
    """审批结论事件（``approval.decided``）。"""

    type: ClassVar[str] = "approval.decided"

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        status: str,
        decided_by: str | None = None,
    ) -> ApprovalDecided:
        """便捷构造。"""
        payload: dict[str, Any] = {"approval_id": approval_id, "status": status}
        if decided_by is not None:
            payload["decided_by"] = decided_by
        return cls(payload=payload)
