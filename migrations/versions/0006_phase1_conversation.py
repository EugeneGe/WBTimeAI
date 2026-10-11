"""Phase 1 · T1-06：Conversation 组 + Sandbox + Audit 表。

Revision ID: 0006_phase1_conversation
Revises: 0005_phase1_tool
Create Date: 2025-01-06

设计依据：设计 §2.15.1（Conversation / Sandbox / 审计组；
修订 R-04/R-07/R-09/R-10/R-14/R-22）。

本批次建表（共 7 张）：
``conversation`` / ``agent_run`` / ``message`` / ``sandbox_session`` /
``tool_call`` / ``agent_event`` / ``audit_log``。

约定：
- 主键 UUIDv7；核心表带 ``tenant_id``；时间戳 UTC；JSON 走 ``JSONType``；
- ``agent_run`` 唯一索引 ``(tenant_id, idempotency_key)``（R-10）；
- ``tool_call`` 含 ``tool_type`` / ``tool_ref`` / ``attempt`` / ``trace_id`` / ``span_id`` /
  ``sandbox_session_id``（R-07 / R-09 / R-22）；
- ``audit_log`` **提前至 Phase 1**（R-14）；
- ``downgrade`` 逆序删除（C-05）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0006_phase1_conversation"
down_revision: str | None = "0005_phase1_tool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """返回统一的时间戳列定义（UTC，created_at + updated_at）。"""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def _created_at() -> sa.Column:
    """返回仅 ``created_at`` 的时间戳列（UTC）。"""
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    """创建 Conversation 组 + Sandbox + Audit 表。"""
    # -- 1. conversation -----------------------------------------------------
    op.create_table(
        "conversation",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_conversation_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_conversation_workspace_id"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_conversation_agent_id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_conversation_user_id"),
    )
    op.create_index("ix_conversation_tenant_id", "conversation", ["tenant_id"])
    op.create_index("ix_conversation_workspace_id", "conversation", ["workspace_id"])
    op.create_index("ix_conversation_agent_id", "conversation", ["agent_id"])
    op.create_index("ix_conversation_user_id", "conversation", ["user_id"])

    # -- 2. agent_run --------------------------------------------------------
    op.create_table(
        "agent_run",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("agent_version_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=True),
        sa.Column("task_id", GUID(), nullable=True),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column("run_mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", JSONType(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("tool_error_count", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("cost_currency", sa.String(length=10), nullable=True),
        sa.Column("cost_price_version", sa.String(length=50), nullable=True),
        sa.Column("cost_estimated", sa.Boolean(), nullable=False),
        sa.Column("cost_breakdown", JSONType(), nullable=True),
        sa.Column("cost_status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_agent_run_tenant_id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_agent_run_agent_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_version.id"], name="fk_agent_run_agent_version_id"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversation.id"], name="fk_agent_run_conversation_id"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_agent_run_user_id"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_agent_run_task_id"),
    )
    op.create_index("ix_agent_run_tenant_id", "agent_run", ["tenant_id"])
    op.create_index("ix_agent_run_agent_id", "agent_run", ["agent_id"])
    op.create_index("ix_agent_run_agent_version_id", "agent_run", ["agent_version_id"])
    op.create_index("ix_agent_run_conversation_id", "agent_run", ["conversation_id"])
    op.create_index("ix_agent_run_user_id", "agent_run", ["user_id"])
    op.create_index("ix_agent_run_task_id", "agent_run", ["task_id"])
    op.create_index("ix_agent_run_status", "agent_run", ["status"])
    op.create_index("ix_agent_run_trace_id", "agent_run", ["trace_id"])
    op.create_index(
        "uq_agent_run_tenant_idempotency_key",
        "agent_run",
        ["tenant_id", "idempotency_key"],
        unique=True,
    )

    # -- 3. message ----------------------------------------------------------
    op.create_table(
        "message",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("run_id", GUID(), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_parts", JSONType(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversation.id"], name="fk_message_conversation_id"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], name="fk_message_run_id"),
    )
    op.create_index("ix_message_conversation_id", "message", ["conversation_id"])
    op.create_index("ix_message_run_id", "message", ["run_id"])

    # -- 4. sandbox_session --------------------------------------------------
    op.create_table(
        "sandbox_session",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("run_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("container_ref", sa.String(length=255), nullable=True),
        sa.Column("workdir", sa.String(length=512), nullable=False),
        _created_at(),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_sandbox_session_tenant_id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], name="fk_sandbox_session_run_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_sandbox_session_workspace_id"
        ),
    )
    op.create_index("ix_sandbox_session_tenant_id", "sandbox_session", ["tenant_id"])
    op.create_index("ix_sandbox_session_run_id", "sandbox_session", ["run_id"])
    op.create_index("ix_sandbox_session_workspace_id", "sandbox_session", ["workspace_id"])

    # -- 5. tool_call --------------------------------------------------------
    op.create_table(
        "tool_call",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("run_id", GUID(), nullable=False),
        sa.Column("tool_id", GUID(), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_type", sa.String(length=30), nullable=False),
        sa.Column("tool_ref", JSONType(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("input", JSONType(), nullable=True),
        sa.Column("output", JSONType(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("sandbox_session_id", GUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], name="fk_tool_call_run_id"),
        sa.ForeignKeyConstraint(["tool_id"], ["tool.id"], name="fk_tool_call_tool_id"),
        sa.ForeignKeyConstraint(
            ["sandbox_session_id"],
            ["sandbox_session.id"],
            name="fk_tool_call_sandbox_session_id",
        ),
    )
    op.create_index("ix_tool_call_run_id", "tool_call", ["run_id"])
    op.create_index("ix_tool_call_tool_id", "tool_call", ["tool_id"])
    op.create_index("ix_tool_call_status", "tool_call", ["status"])
    op.create_index("ix_tool_call_sandbox_session_id", "tool_call", ["sandbox_session_id"])

    # -- 6. agent_event ------------------------------------------------------
    op.create_table(
        "agent_event",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("run_id", GUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("payload", JSONType(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], name="fk_agent_event_run_id"),
    )
    op.create_index("ix_agent_event_run_id", "agent_event", ["run_id"])
    op.create_index("ix_agent_event_seq", "agent_event", ["seq"])

    # -- 7. audit_log（R-14 提前至 Phase 1） ---------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("user_id", GUID(), nullable=True),
        sa.Column("agent_id", GUID(), nullable=True),
        sa.Column("run_id", GUID(), nullable=True),
        sa.Column("tool_call_id", GUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", JSONType(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("metadata", JSONType(), nullable=True),
        sa.Column("extensions", JSONType(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_audit_log_tenant_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_audit_log_organization_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_audit_log_workspace_id"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_audit_log_user_id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_audit_log_agent_id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], name="fk_audit_log_run_id"),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_call.id"], name="fk_audit_log_tool_call_id"
        ),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])
    op.create_index("ix_audit_log_run_id", "audit_log", ["run_id"])


def downgrade() -> None:
    """回滚：逆序删除本批次全部表。"""
    op.drop_index("ix_audit_log_run_id", table_name="audit_log")
    op.drop_index("ix_audit_log_request_id", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_tenant_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_agent_event_seq", table_name="agent_event")
    op.drop_index("ix_agent_event_run_id", table_name="agent_event")
    op.drop_table("agent_event")
    op.drop_index("ix_tool_call_sandbox_session_id", table_name="tool_call")
    op.drop_index("ix_tool_call_status", table_name="tool_call")
    op.drop_index("ix_tool_call_tool_id", table_name="tool_call")
    op.drop_index("ix_tool_call_run_id", table_name="tool_call")
    op.drop_table("tool_call")
    op.drop_index("ix_sandbox_session_workspace_id", table_name="sandbox_session")
    op.drop_index("ix_sandbox_session_run_id", table_name="sandbox_session")
    op.drop_index("ix_sandbox_session_tenant_id", table_name="sandbox_session")
    op.drop_table("sandbox_session")
    op.drop_index("ix_message_run_id", table_name="message")
    op.drop_index("ix_message_conversation_id", table_name="message")
    op.drop_table("message")
    op.drop_index("uq_agent_run_tenant_idempotency_key", table_name="agent_run")
    op.drop_index("ix_agent_run_trace_id", table_name="agent_run")
    op.drop_index("ix_agent_run_status", table_name="agent_run")
    op.drop_index("ix_agent_run_task_id", table_name="agent_run")
    op.drop_index("ix_agent_run_user_id", table_name="agent_run")
    op.drop_index("ix_agent_run_conversation_id", table_name="agent_run")
    op.drop_index("ix_agent_run_agent_version_id", table_name="agent_run")
    op.drop_index("ix_agent_run_agent_id", table_name="agent_run")
    op.drop_index("ix_agent_run_tenant_id", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_index("ix_conversation_user_id", table_name="conversation")
    op.drop_index("ix_conversation_agent_id", table_name="conversation")
    op.drop_index("ix_conversation_workspace_id", table_name="conversation")
    op.drop_index("ix_conversation_tenant_id", table_name="conversation")
    op.drop_table("conversation")
