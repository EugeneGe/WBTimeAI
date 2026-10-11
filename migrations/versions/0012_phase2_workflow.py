"""Phase 2 · W4 / T2-20：Workflow 组表（``workflow`` / ``workflow_version`` /
``workflow_node`` / ``workflow_edge`` / ``workflow_run`` / ``workflow_node_run``）。

Revision ID: 0012_phase2_workflow
Revises: 0011_phase2_credential_multi
Create Date: 2026-10-10

设计依据：设计 §2.5 / §2.15.1 / §2.15.4；**W4 开工前架构裁定** §2（R2）。

约定：
- **纯新增**：仅创建 6 张 Workflow 组表；**不改动** ``0001–0011`` 任何表；
- 🔴 **严禁重复建 ``approval`` 表**：该表随迁移 ``0010_phase2_permission_plugin``（2a）
  建立；``workflow_node_run.approval_id → approval.id`` 为对既有表的**加性外键**，
  ``downgrade`` **不删** ``approval``（W4 裁定 §2.1 / 风险 WR-1）；
- 主键 UUIDv7（``GUID`` 方言适配）；核心表带 ``tenant_id``；
- 时间戳 UTC（``DateTime(timezone=True)``）；JSON 走 ``JSONType``；
- 唯一键：``workflow`` ``(tenant_id, name)``；``workflow_version`` ``(workflow_id, version)``；
  ``workflow_node`` ``(workflow_version_id, node_key)``（**验收 ② 硬性**）；
  ``workflow_edge`` ``(workflow_version_id, from_node_key, to_node_key)``；
  ``workflow_node_run`` ``(workflow_run_id, node_key, attempt)``；
- ``workflow.current_version_id → workflow_version.id`` 因**双向引用**，在建表后以
  ``ALTER TABLE`` 追加外键（SQLite 经 batch 重建，PG 直接加约束）——**本迁移唯一**
  方言分支点（仿 ``0008_phase2_skill``）；
- 方言差异**显式**按 ``op.get_bind().dialect.name`` 分支（**禁 try/except**）；
- ``downgrade`` 逆序删除，保证往返干净（C-05）；**先摘循环外键**再 drop 表。

🔴 不可逆：``downgrade`` DROP 六表 → **Workflow 定义与执行历史丢失**
   （``workflow_run`` / ``workflow_node_run`` 及其 ``agent_run`` / ``tool_call`` /
   ``approval`` 关联随之丢失）；可重建性依赖版本快照被备份。
   **``approval`` 表不随本迁移 ``downgrade`` 删除**（仍属 ``0010``）。回滚须先备份。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0012_phase2_workflow"
down_revision: str | None = "0011_phase2_credential_multi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_workflow_current_version_id"


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


def _created_at() -> sa.Column:
    """返回仅 ``created_at`` 的时间戳列（UTC）。"""
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _add_current_version_fk() -> None:
    """为 ``workflow.current_version_id → workflow_version.id`` 追加外键（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.create_foreign_key(
                _FK_NAME, "workflow_version", ["current_version_id"], ["id"]
            )
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 加约束
        op.create_foreign_key(
            _FK_NAME, "workflow", "workflow_version", ["current_version_id"], ["id"]
        )


def _drop_current_version_fk() -> None:
    """移除 ``workflow.current_version_id`` 外键（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 删约束
        op.drop_constraint(_FK_NAME, "workflow", type_="foreignkey")


def upgrade() -> None:
    """创建 Workflow 组六表（**不含 ``approval``**，该表属 ``0010``）。"""
    # -- 1. workflow --------------------------------------------------------
    op.create_table(
        "workflow",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_version_id", GUID(), nullable=True),
        sa.Column("created_by", GUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_workflow_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_workflow_workspace_id"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_workflow_created_by"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_workflow_tenant_name"),
    )
    op.create_index("ix_workflow_tenant_id", "workflow", ["tenant_id"])
    op.create_index("ix_workflow_current_version_id", "workflow", ["current_version_id"])
    op.create_index("ix_workflow_created_by", "workflow", ["created_by"])

    # -- 2. workflow_version（不可变快照） -----------------------------------
    op.create_table(
        "workflow_version",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("workflow_id", GUID(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("definition", JSONType(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", GUID(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow.id"], name="fk_workflow_version_workflow_id"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_workflow_version_created_by"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_version_workflow_version"),
    )
    op.create_index("ix_workflow_version_workflow_id", "workflow_version", ["workflow_id"])
    op.create_index("ix_workflow_version_created_by", "workflow_version", ["created_by"])

    # -- 3. workflow_node ---------------------------------------------------
    op.create_table(
        "workflow_node",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("workflow_version_id", GUID(), nullable=False),
        sa.Column("node_key", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("config", JSONType(), nullable=False),
        sa.Column("position", JSONType(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_version.id"],
            name="fk_workflow_node_workflow_version_id",
        ),
        sa.UniqueConstraint(
            "workflow_version_id", "node_key", name="uq_workflow_node_version_node_key"
        ),
    )
    op.create_index(
        "ix_workflow_node_workflow_version_id", "workflow_node", ["workflow_version_id"]
    )

    # -- 4. workflow_edge ---------------------------------------------------
    op.create_table(
        "workflow_edge",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("workflow_version_id", GUID(), nullable=False),
        sa.Column("from_node_key", sa.String(length=255), nullable=False),
        sa.Column("to_node_key", sa.String(length=255), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_version.id"],
            name="fk_workflow_edge_workflow_version_id",
        ),
        sa.UniqueConstraint(
            "workflow_version_id",
            "from_node_key",
            "to_node_key",
            name="uq_workflow_edge_version_from_to",
        ),
    )
    op.create_index(
        "ix_workflow_edge_workflow_version_id", "workflow_edge", ["workflow_version_id"]
    )

    # -- 5. workflow_run（固定引用不可变版本，可重建） ------------------------
    op.create_table(
        "workflow_run",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workflow_version_id", GUID(), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("task_id", GUID(), nullable=True),
        sa.Column("input", JSONType(), nullable=True),
        sa.Column("output", JSONType(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_workflow_run_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_version.id"],
            name="fk_workflow_run_workflow_version_id",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_workflow_run_task_id"),
    )
    op.create_index("ix_workflow_run_tenant_id", "workflow_run", ["tenant_id"])
    op.create_index("ix_workflow_run_workflow_version_id", "workflow_run", ["workflow_version_id"])
    op.create_index("ix_workflow_run_status", "workflow_run", ["status"])
    op.create_index("ix_workflow_run_task_id", "workflow_run", ["task_id"])

    # -- 6. workflow_node_run（重放数据源；approval_id 为加性外键） ------------
    op.create_table(
        "workflow_node_run",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("workflow_run_id", GUID(), nullable=False),
        sa.Column("node_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", GUID(), nullable=True),
        sa.Column("tool_call_id", GUID(), nullable=True),
        sa.Column("approval_id", GUID(), nullable=True),
        sa.Column("input", JSONType(), nullable=True),
        sa.Column("output", JSONType(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_run.id"], name="fk_workflow_node_run_run_id"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_run.id"], name="fk_workflow_node_run_agent_run_id"
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_call.id"], name="fk_workflow_node_run_tool_call_id"
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["approval.id"], name="fk_workflow_node_run_approval_id"
        ),
        sa.UniqueConstraint(
            "workflow_run_id",
            "node_key",
            "attempt",
            name="uq_workflow_node_run_run_key_attempt",
        ),
    )
    op.create_index(
        "ix_workflow_node_run_workflow_run_id", "workflow_node_run", ["workflow_run_id"]
    )
    op.create_index("ix_workflow_node_run_agent_run_id", "workflow_node_run", ["agent_run_id"])
    op.create_index("ix_workflow_node_run_approval_id", "workflow_node_run", ["approval_id"])

    # -- 7. 双向引用：workflow.current_version_id → workflow_version.id --------
    _add_current_version_fk()


def downgrade() -> None:
    """回滚：逆序删除 Workflow 组六表（**执行历史与版本快照丢失**，见模块级不可逆说明）。

    🔴 ``approval`` 表**不在**本 ``downgrade`` 删除范围（属 ``0010``）。
    """
    _drop_current_version_fk()
    op.drop_index("ix_workflow_node_run_approval_id", table_name="workflow_node_run")
    op.drop_index("ix_workflow_node_run_agent_run_id", table_name="workflow_node_run")
    op.drop_index("ix_workflow_node_run_workflow_run_id", table_name="workflow_node_run")
    op.drop_table("workflow_node_run")
    op.drop_index("ix_workflow_run_task_id", table_name="workflow_run")
    op.drop_index("ix_workflow_run_status", table_name="workflow_run")
    op.drop_index("ix_workflow_run_workflow_version_id", table_name="workflow_run")
    op.drop_index("ix_workflow_run_tenant_id", table_name="workflow_run")
    op.drop_table("workflow_run")
    op.drop_index("ix_workflow_edge_workflow_version_id", table_name="workflow_edge")
    op.drop_table("workflow_edge")
    op.drop_index("ix_workflow_node_workflow_version_id", table_name="workflow_node")
    op.drop_table("workflow_node")
    op.drop_index("ix_workflow_version_created_by", table_name="workflow_version")
    op.drop_index("ix_workflow_version_workflow_id", table_name="workflow_version")
    op.drop_table("workflow_version")
    op.drop_index("ix_workflow_created_by", table_name="workflow")
    op.drop_index("ix_workflow_current_version_id", table_name="workflow")
    op.drop_index("ix_workflow_tenant_id", table_name="workflow")
    op.drop_table("workflow")
