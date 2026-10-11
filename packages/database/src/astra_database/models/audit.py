"""审计组 ORM 表（设计 §2.15.1 审计组 / §2.18，修订 R-14）。

- :class:`AuditLog`：基础审计记录（十要素 + ``extensions`` 命名空间）。

⚠️ 仅表结构；审计服务实现属 T1-09（本波次同批落地）。

🔴 ``metadata`` 列承载**脱敏**后的入参 / 结果摘要；明文凭证 / 密钥**不得**落库。
   （Python 属性名用 ``metadata_``，避免与 SQLAlchemy 声明式 ``metadata`` 冲突。）
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import GUID, JSONType

__all__ = ["AuditLog"]


class AuditLog(Base):
    """基础审计记录（对齐需求 §47 十要素 / 设计 §2.18.1）。"""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("agent.id"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tool_call.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=6), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONType(), nullable=True)
    extensions: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
