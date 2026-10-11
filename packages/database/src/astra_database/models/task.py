"""Task ORM 表（设计 §2.6）。

⚠️ 仅表结构；任务状态机与队列 / 调度属 T0-14，本轮不实现。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Task"]


class Task(Base, TimestampMixin):
    """统一承载普通 / AI / 后台任务的任务记录。

    状态机（两条路径，设计 §2.11 / ``I-P1-12``）：

    - QUEUED：``CREATED → PENDING → RUNNING → SUCCESS | FAILED | CANCELLED``；
    - INLINE：``CREATED → RUNNING → 终态``（跳过 ``PENDING``）。
    """

    __tablename__ = "task"
    __table_args__ = (
        # 幂等键：可空**唯一**索引（``uq_task_idempotency_key``，R6/§3.4）——NULL 可重复。
        Index("uq_task_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="CREATED", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="INLINE")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    # 幂等落点（W7 / R6）：``f"{target_type}:{target_id}:{fire_time.isoformat()}"``，可空唯一。
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
