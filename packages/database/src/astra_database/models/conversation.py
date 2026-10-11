"""Conversation 组 ORM 表（设计 §2.15.1 Conversation 组 / §2.6）。

- :class:`Conversation`：会话容器。
- :class:`AgentRun`：一次执行（含 R-04/R-07/R-09/R-10 修订列）。
- :class:`Message`：消息（文本 + ``content_parts``）。
- :class:`ToolCall`：工具调用明细（含 R-07/R-09/R-22 修订列）。
- :class:`AgentEvent`：生命周期事件序列（``seq`` 递增，可回放）。

⚠️ 仅表结构；Runtime / SSE 属 W5/W6，本轮不实现。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Conversation", "AgentRun", "Message", "ToolCall", "AgentEvent"]


class Conversation(Base, TimestampMixin):
    """Conversation：用户 ↔ Agent 会话容器（设计 §2.6）。"""

    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("user.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class AgentRun(Base):
    """AgentRun：一次执行的状态与用量（含修订列 R-04/R-07/R-10）。"""

    __tablename__ = "agent_run"
    __table_args__ = (
        Index(
            "uq_agent_run_tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=False, index=True
    )
    agent_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("conversation.id"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("task.id"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    run_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_error_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=6), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cost_price_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_estimated: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    cost_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    cost_status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class Message(Base):
    """Message：对话消息（文本 + ``content_parts``）。"""

    __tablename__ = "message"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    conversation_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("conversation.id"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    content_parts: Mapped[list[Any] | None] = mapped_column(JSONType(), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ToolCall(Base):
    """ToolCall：每次工具调用的明细（含修订列 R-07/R-09/R-22）。"""

    __tablename__ = "tool_call"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    run_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=False, index=True
    )
    tool_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tool.id"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_type: Mapped[str] = mapped_column(String(30), nullable=False)
    tool_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    sandbox_session_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("sandbox_session.id"), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AgentEvent(Base):
    """AgentEvent：生命周期事件序列（``seq`` 递增，可回放）。"""

    __tablename__ = "agent_event"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    run_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer(), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
