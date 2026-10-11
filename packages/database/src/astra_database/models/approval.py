"""Approval ORM 表（设计 §2.10；W3 裁定 §3 / Erratum-E）。

- :class:`Approval`：基础审批记录（``tool`` / ``mcp`` / ``workflow_node`` 三类主体）。

🔴 **表随迁移 ``0010_phase2_permission_plugin``（2a）落地**（承接 W1 §1.4）；**审批「机制接线
   （挂起 / 决议 / 续跑）」归 2b（T2-26，零迁移）** —— **建表在 2a、消费在 2b**。故本 ORM
   模型随 0010 同批交付（保证 ``alembic check`` 零漂移），**不含**业务方法。

🔴 ``effect`` 无关：审批状态 ``PENDING`` / ``APPROVED`` / ``REJECTED`` / ``EXPIRED``
   （``approval.status``）；``resource_permission.effect`` 与之无关（仅 ``ALLOW`` / ``DENY``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Approval"]


class Approval(Base, TimestampMixin):
    """基础审批记录（表随 ``0010`` 建于 2a；机制接线归 2b）。"""

    __tablename__ = "approval"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    decided_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
