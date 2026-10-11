"""Phase 2 · W2 / T2-10：MCP 组表（``mcp_server`` / ``mcp_tool`` / ``mcp_permission``）
+ ``tool`` 表扩展（``tool_ref`` 列）。

Revision ID: 0009_phase2_mcp
Revises: 0008_phase2_skill
Create Date: 2026-10-09

设计依据：设计 §2.4 / §2.15.1 / §2.15.4；W2 裁定 §9 / §13.2（R9/R13）。

约定：
- **三张新表** + **``tool`` 表两处变化**（W2 裁定 §9.2 / Erratum-9）：
  - ``tool`` 表**新增** ``tool_ref (JSON, nullable)`` 列（**唯一 DDL**，MCP Tool 溯源引用）；
  - ``tool.source``（``String(50)``）**无需改列**——``mcp`` 取值由应用层写入（语义扩展）；
  - ``tool_call`` **免改**（Phase 1 已含 ``tool_id`` / ``tool_type`` / ``tool_ref``）。
- 唯一键：``mcp_server`` ``(tenant_id, name)``；``mcp_tool`` ``(mcp_server_id, name)``；
  ``mcp_permission`` ``(mcp_tool_id, agent_id, action)``；
- ``mcp_server.credential_id`` 复用 Phase 0 ``credential``（**不新增平行存储**，C-07）；
- 方言差异**显式**按 ``op.get_bind().dialect.name`` 分支（**禁 try/except**）；
- ``downgrade`` 逆序删除，**并显式 ``DELETE FROM tool WHERE source='mcp'``** 清僵尸工具行
  （否则残留指向已删 ``mcp_tool`` 的 ``tool`` 行；W2 裁定 §13.3 / R6 风险）。

🔴 不可逆：``downgrade`` DROP 三表 + ``tool.tool_ref`` 列 + 删除 ``source='mcp'`` 的 ``tool``
   行 → **MCP 目录与发现记录丢失**；``credential`` 不受影响（复用既有表，F17）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0009_phase2_mcp"
down_revision: str | None = "0008_phase2_skill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """返回统一的时间戳列定义（UTC，``created_at`` + ``updated_at``）。"""
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


def _add_tool_ref() -> None:
    """为 ``tool`` 表新增 ``tool_ref`` JSON 列（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("tool") as batch_op:
            batch_op.add_column(sa.Column("tool_ref", JSONType(), nullable=True))
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 加列
        op.add_column("tool", sa.Column("tool_ref", JSONType(), nullable=True))


def _drop_tool_ref() -> None:
    """移除 ``tool`` 表的 ``tool_ref`` 列（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("tool") as batch_op:
            batch_op.drop_column("tool_ref")
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 删列
        op.drop_column("tool", "tool_ref")


def upgrade() -> None:
    """创建 MCP 三表并为 ``tool`` 表新增 ``tool_ref`` 列。"""
    # -- 1. mcp_server ------------------------------------------------------
    op.create_table(
        "mcp_server",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("endpoint", sa.String(length=1024), nullable=True),
        sa.Column("command", sa.String(length=1024), nullable=True),
        sa.Column("args", JSONType(), nullable=True),
        sa.Column("env_ref", JSONType(), nullable=True),
        sa.Column("credential_id", GUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("capabilities", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_mcp_server_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_mcp_server_workspace_id"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], name="fk_mcp_server_credential_id"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_mcp_server_tenant_name"),
    )
    op.create_index("ix_mcp_server_tenant_id", "mcp_server", ["tenant_id"])
    op.create_index("ix_mcp_server_workspace_id", "mcp_server", ["workspace_id"])
    op.create_index("ix_mcp_server_credential_id", "mcp_server", ["credential_id"])

    # -- 2. mcp_tool --------------------------------------------------------
    op.create_table(
        "mcp_tool",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("mcp_server_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema", JSONType(), nullable=True),
        sa.Column("output_schema", JSONType(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], name="fk_mcp_tool_mcp_server_id"
        ),
        sa.UniqueConstraint("mcp_server_id", "name", name="uq_mcp_tool_server_name"),
    )
    op.create_index("ix_mcp_tool_mcp_server_id", "mcp_tool", ["mcp_server_id"])

    # -- 3. mcp_permission --------------------------------------------------
    op.create_table(
        "mcp_permission",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=True),
        sa.Column("agent_version_id", GUID(), nullable=True),
        sa.Column("mcp_tool_id", GUID(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("effect", sa.String(length=20), nullable=False),
        sa.Column("scope", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_mcp_permission_tenant_id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_mcp_permission_agent_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_version.id"], name="fk_mcp_permission_agent_version_id"
        ),
        sa.ForeignKeyConstraint(
            ["mcp_tool_id"], ["mcp_tool.id"], name="fk_mcp_permission_mcp_tool_id"
        ),
        sa.UniqueConstraint(
            "mcp_tool_id", "agent_id", "action", name="uq_mcp_permission_tool_agent_action"
        ),
    )
    op.create_index("ix_mcp_permission_tenant_id", "mcp_permission", ["tenant_id"])
    op.create_index("ix_mcp_permission_agent_id", "mcp_permission", ["agent_id"])
    op.create_index("ix_mcp_permission_agent_version_id", "mcp_permission", ["agent_version_id"])
    op.create_index("ix_mcp_permission_mcp_tool_id", "mcp_permission", ["mcp_tool_id"])

    # -- 4. tool 表扩展：新增 tool_ref（唯一 DDL；source 免改，tool_call 免改）--
    _add_tool_ref()


def downgrade() -> None:
    """回滚：删 ``source='mcp'`` 工具行 → 去 ``tool.tool_ref`` → 逆序删三表。"""
    # -- 1. 显式清理 MCP 僵尸工具行（避免残留指向已删 mcp_tool 的 tool 行）------
    op.execute(sa.text("DELETE FROM tool WHERE source = 'mcp'"))

    # -- 2. 移除 tool.tool_ref 列 -------------------------------------------
    _drop_tool_ref()

    # -- 3. 逆序删除三表 ----------------------------------------------------
    op.drop_index("ix_mcp_permission_mcp_tool_id", table_name="mcp_permission")
    op.drop_index("ix_mcp_permission_agent_version_id", table_name="mcp_permission")
    op.drop_index("ix_mcp_permission_agent_id", table_name="mcp_permission")
    op.drop_index("ix_mcp_permission_tenant_id", table_name="mcp_permission")
    op.drop_table("mcp_permission")
    op.drop_index("ix_mcp_tool_mcp_server_id", table_name="mcp_tool")
    op.drop_table("mcp_tool")
    op.drop_index("ix_mcp_server_credential_id", table_name="mcp_server")
    op.drop_index("ix_mcp_server_workspace_id", table_name="mcp_server")
    op.drop_index("ix_mcp_server_tenant_id", table_name="mcp_server")
    op.drop_table("mcp_server")
