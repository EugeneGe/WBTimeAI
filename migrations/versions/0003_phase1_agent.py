"""Phase 1 · T1-06：Agent 组表（``agent`` / ``agent_version`` / ``agent_tool``）。

Revision ID: 0003_phase1_agent
Revises: 0002_feature_flag
Create Date: 2025-01-03

设计依据：设计 §2.15.1（Agent 组）/ §2.4 / §2.15.4。

约定：
- **纯新增**：仅创建 3 张 Agent 组表，**不改动** 0001 / 0002 的任何表；
- 主键 UUIDv7（``GUID`` 方言适配）；核心表带 ``tenant_id``；
- 时间戳 UTC（``DateTime(timezone=True)``）；JSON 走 ``JSONType``；
- ``agent_tool`` 唯一键 ``(agent_version_id, tool_id)``；
- ``agent.current_version_id → agent_version.id`` 因**双向引用**，在建表后以
  ``ALTER TABLE`` 追加外键（SQLite 经批量模式重建，PG 直接加约束）；
- ``downgrade`` 逆序删除，保证往返干净（C-05）。

🔴 ``agent.current_version_id`` 与 ``agent_version.agent_id`` 的**一致性**由应用层校验，
   迁移不加跨表一致性约束（设计 §2.15.4）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0003_phase1_agent"
down_revision: str | None = "0002_feature_flag"
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
    """创建 ``agent`` / ``agent_version`` / ``agent_tool``。"""
    # -- 1. agent ------------------------------------------------------------
    op.create_table(
        "agent",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_version_id", GUID(), nullable=True),
        sa.Column("created_by", GUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_agent_tenant_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_agent_workspace_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_agent_created_by"),
    )
    op.create_index("ix_agent_tenant_id", "agent", ["tenant_id"])
    op.create_index("ix_agent_workspace_id", "agent", ["workspace_id"])
    op.create_index("ix_agent_created_by", "agent", ["created_by"])
    op.create_index("ix_agent_current_version_id", "agent", ["current_version_id"])

    # -- 2. agent_version ----------------------------------------------------
    op.create_table(
        "agent_version",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("model_config", JSONType(), nullable=False),
        sa.Column("runtime_config", JSONType(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", GUID(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_agent_version_agent_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_agent_version_created_by"),
    )
    op.create_index("ix_agent_version_agent_id", "agent_version", ["agent_id"])
    op.create_index("ix_agent_version_created_by", "agent_version", ["created_by"])

    # -- 3. agent_tool -------------------------------------------------------
    op.create_table(
        "agent_tool",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_version_id", GUID(), nullable=False),
        sa.Column("tool_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("permission_scope", JSONType(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_agent_tool_tenant_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_version.id"], name="fk_agent_tool_agent_version_id"
        ),
        # 注意：``tool_id → tool.id`` 为**前向引用**（``tool`` 表在 0005 批次建立），
        # 故此处仅建列 / 索引，外键约束在 0005 建表后追加（见 0005 ``upgrade``）。
        sa.UniqueConstraint("agent_version_id", "tool_id", name="uq_agent_tool_version_tool"),
    )
    op.create_index("ix_agent_tool_tenant_id", "agent_tool", ["tenant_id"])
    op.create_index("ix_agent_tool_agent_version_id", "agent_tool", ["agent_version_id"])
    op.create_index("ix_agent_tool_tool_id", "agent_tool", ["tool_id"])

    # -- 4. 双向引用：agent.current_version_id → agent_version.id -------------
    with op.batch_alter_table("agent") as batch_op:
        batch_op.create_foreign_key(
            "fk_agent_current_version_id",
            "agent_version",
            ["current_version_id"],
            ["id"],
        )


def downgrade() -> None:
    """回滚：逆序删除 Agent 组表。"""
    with op.batch_alter_table("agent") as batch_op:
        batch_op.drop_constraint("fk_agent_current_version_id", type_="foreignkey")
    op.drop_index("ix_agent_tool_tool_id", table_name="agent_tool")
    op.drop_index("ix_agent_tool_agent_version_id", table_name="agent_tool")
    op.drop_index("ix_agent_tool_tenant_id", table_name="agent_tool")
    op.drop_table("agent_tool")
    op.drop_index("ix_agent_version_created_by", table_name="agent_version")
    op.drop_index("ix_agent_version_agent_id", table_name="agent_version")
    op.drop_table("agent_version")
    op.drop_index("ix_agent_current_version_id", table_name="agent")
    op.drop_index("ix_agent_created_by", table_name="agent")
    op.drop_index("ix_agent_workspace_id", table_name="agent")
    op.drop_index("ix_agent_tenant_id", table_name="agent")
    op.drop_table("agent")
