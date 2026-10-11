"""Phase 1 · T1-06：Tool 组表（``tool`` / ``tool_version`` / ``tool_permission``）。

Revision ID: 0005_phase1_tool
Revises: 0004_phase1_model
Create Date: 2025-01-05

设计依据：设计 §2.15.1（Tool 组）/ §2.5。

约定：
- **纯新增**：仅创建 3 张 Tool 组表，**不改动**既有表；
- ``tool.tenant_id`` **可空**（内置工具为全局 = NULL）；
- ``tool_permission`` 唯一键 ``(agent_id, tool_id, action)``；
  ``effect`` 预留 ``APPROVAL``（本期恒 ``ALLOW``/``DENY``）；
- 建 ``tool`` 表后**补建** ``agent_tool.tool_id → tool.id`` 外键（前向引用回填，见 0003 说明）；
- ``downgrade`` 逆序删除（C-05）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0005_phase1_tool"
down_revision: str | None = "0004_phase1_model"
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


def upgrade() -> None:
    """创建 ``tool`` / ``tool_version`` / ``tool_permission``。"""
    # -- 1. tool -------------------------------------------------------------
    op.create_table(
        "tool",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("input_schema", JSONType(), nullable=True),
        sa.Column("output_schema", JSONType(), nullable=True),
        sa.Column("requires_sandbox", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_tool_tenant_id"),
    )
    op.create_index("ix_tool_tenant_id", "tool", ["tenant_id"])
    op.create_index("ix_tool_name", "tool", ["name"])

    # -- 2. tool_version -----------------------------------------------------
    op.create_table(
        "tool_version",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tool_id", GUID(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("spec", JSONType(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tool_id"], ["tool.id"], name="fk_tool_version_tool_id"),
    )
    op.create_index("ix_tool_version_tool_id", "tool_version", ["tool_id"])

    # -- 3. tool_permission --------------------------------------------------
    op.create_table(
        "tool_permission",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=True),
        sa.Column("agent_version_id", GUID(), nullable=True),
        sa.Column("tool_id", GUID(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("effect", sa.String(length=20), nullable=False),
        sa.Column("scope", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_tool_permission_tenant_id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_tool_permission_agent_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_version.id"],
            name="fk_tool_permission_agent_version_id",
        ),
        sa.ForeignKeyConstraint(["tool_id"], ["tool.id"], name="fk_tool_permission_tool_id"),
        sa.UniqueConstraint(
            "agent_id", "tool_id", "action", name="uq_tool_permission_agent_tool_action"
        ),
    )
    op.create_index("ix_tool_permission_tenant_id", "tool_permission", ["tenant_id"])
    op.create_index("ix_tool_permission_agent_id", "tool_permission", ["agent_id"])
    op.create_index("ix_tool_permission_agent_version_id", "tool_permission", ["agent_version_id"])
    op.create_index("ix_tool_permission_tool_id", "tool_permission", ["tool_id"])

    # -- 4. 前向引用回填：agent_tool.tool_id → tool.id ------------------------
    with op.batch_alter_table("agent_tool") as batch_op:
        batch_op.create_foreign_key(
            "fk_agent_tool_tool_id",
            "tool",
            ["tool_id"],
            ["id"],
        )


def downgrade() -> None:
    """回滚：逆序删除 Tool 组表（先断开前向引用外键）。"""
    with op.batch_alter_table("agent_tool") as batch_op:
        batch_op.drop_constraint("fk_agent_tool_tool_id", type_="foreignkey")
    op.drop_index("ix_tool_permission_tool_id", table_name="tool_permission")
    op.drop_index("ix_tool_permission_agent_version_id", table_name="tool_permission")
    op.drop_index("ix_tool_permission_agent_id", table_name="tool_permission")
    op.drop_index("ix_tool_permission_tenant_id", table_name="tool_permission")
    op.drop_table("tool_permission")
    op.drop_index("ix_tool_version_tool_id", table_name="tool_version")
    op.drop_table("tool_version")
    op.drop_index("ix_tool_name", table_name="tool")
    op.drop_index("ix_tool_tenant_id", table_name="tool")
    op.drop_table("tool")
