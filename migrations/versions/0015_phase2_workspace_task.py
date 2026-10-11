"""Phase 2 · W7 / T2-37：Workspace 增强 + Task 扩展表（``project`` / ``workspace_environment`` /
``task_execution`` / ``schedule``）+ ``task.idempotency_key``。

Revision ID: 0015_phase2_workspace_task
Revises: 0014_phase2_memory
Create Date: 2026-10-12

设计依据：设计 §2.8 / §2.9 / §2.15；**W7 开工前架构裁定** §3 / §4.1 / R-open#2
（team-lead 拍板 R1–R14 与 R-open，§13）。

约定：
- **纯新增**：仅创建 4 张表 + ``task.idempotency_key``（可空唯一索引）；**不改动**
  ``0001–0014`` 任何既有对象；
- 🔴 **单 head 线性**：``down_revision = "0014_phase2_memory"``；后续 ``0016`` 接本迁移；
- 🔴 **显式方言分支** ``dialect = op.get_bind().dialect.name``（**禁 try/except 推断**，F16）；
  ``GUID`` / ``JSONType`` 已吸收 UUID / JSON 方言差异，故两端分支一致；本迁移的方言分支
  仅用于 ``upgrade`` 的**类型选择注释**与 ``downgrade`` 的 ``drop_column`` 策略（SQLite 走
  ``batch_alter_table``）；
- 🔴 **组织维度一次到位（R-open#2）**：``project`` / ``workspace_environment`` / ``schedule``
  的 ``organization_id`` **可空列 + 组织索引在 ``0015`` 建表即含**（``0016`` 仅回填，不改结构）；
- 🔴 唯一键（冻结契约）：``workspace_environment`` ``(workspace_id, name)``
  ``uq_workspace_environment_ws_name``；``task_execution`` ``(task_id, attempt)``
  ``uq_task_execution_task_attempt``；``schedule`` ``(tenant_id, target_type, target_id, name)``
  ``uq_schedule_target_name``；``task`` ``idempotency_key`` 唯一索引 ``uq_task_idempotency_key``；
- 🔴 ``task_execution`` **仅建基础列**（§3.3）；``0018`` 预留列本波不建；
- 🔴 外键**单向**（无跨表环）：``project → tenant / organization / workspace / user``；
  ``workspace_environment → tenant / organization / workspace``；``task_execution → task``；
  ``schedule → tenant / organization / workspace``；
- 🔴 主键 UUIDv7（``GUID``）；时间戳 UTC（``project`` / ``workspace_environment`` / ``schedule``
  带 ``created_at`` / ``updated_at``；``task_execution`` **无**时间戳列，§3.3）。

``downgrade``（**只 drop 本批自有对象**）：
1. ``DROP INDEX uq_task_idempotency_key`` + ``ALTER TABLE task DROP COLUMN idempotency_key``
   （SQLite 走 ``batch_alter_table``）；
2. 反序 ``DROP TABLE schedule → task_execution → workspace_environment → project``；
3. **不 DROP 既有表 / 列**；**不 DROP EXTENSION**（承接 QA-31）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0015_phase2_workspace_task"
down_revision: str | None = "0014_phase2_memory"
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


def upgrade() -> None:
    """创建 4 张表 + ``task.idempotency_key``（显式方言分支；单 head 线性）。"""
    dialect = op.get_bind().dialect.name
    # ``GUID`` / ``JSONType`` 已吸收两方言差异（PG ↔ 其它）；此处显式读取方言（F16）。
    # 若为未知方言，仍按自适应类型执行（保社区兼容），不抛错。
    if dialect not in {"postgresql", "sqlite"}:  # pragma: no cover - 仅支持两端
        # 未知方言仍按 GUID/JSONType 自适应执行；不抛错以保持社区兼容。
        pass

    # -- 1. project --------------------------------------------------------
    op.create_table(
        "project",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("repo_url", sa.String(length=2048), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column("settings", JSONType(), nullable=True),
        sa.Column("created_by", GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_project_tenant_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_project_organization_id"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_project_workspace_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_project_created_by"),
    )
    op.create_index("ix_project_tenant_id", "project", ["tenant_id"])
    op.create_index("ix_project_organization_id", "project", ["organization_id"])
    op.create_index("ix_project_workspace_id", "project", ["workspace_id"])

    # -- 2. workspace_environment（唯一 (workspace_id, name)） --------------
    op.create_table(
        "workspace_environment",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("env_vars", JSONType(), nullable=True),
        sa.Column("runtime", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_workspace_environment_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_workspace_environment_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_workspace_environment_workspace_id"
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_workspace_environment_ws_name"),
    )
    op.create_index("ix_workspace_environment_tenant_id", "workspace_environment", ["tenant_id"])
    op.create_index(
        "ix_workspace_environment_organization_id", "workspace_environment", ["organization_id"]
    )
    op.create_index(
        "ix_workspace_environment_workspace_id", "workspace_environment", ["workspace_id"]
    )

    # -- 3. task_execution（唯一 (task_id, attempt)；无时间戳列，§3.3） ------
    op.create_table(
        "task_execution",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("task_id", GUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_task_execution_task_id"),
        sa.UniqueConstraint("task_id", "attempt", name="uq_task_execution_task_attempt"),
    )
    op.create_index("ix_task_execution_task_id", "task_execution", ["task_id"])

    # -- 4. schedule（唯一 (tenant_id, target_type, target_id, name)） ------
    op.create_table(
        "schedule",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", GUID(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("cron", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("payload", JSONType(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_schedule_tenant_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_schedule_organization_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_schedule_workspace_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_id",
            "name",
            name="uq_schedule_target_name",
        ),
    )
    op.create_index("ix_schedule_tenant_id", "schedule", ["tenant_id"])
    op.create_index("ix_schedule_organization_id", "schedule", ["organization_id"])
    op.create_index("ix_schedule_workspace_id", "schedule", ["workspace_id"])
    op.create_index("ix_schedule_next_run_at", "schedule", ["next_run_at"])

    # -- 5. task.idempotency_key（可空唯一索引；NULL 可重复） --------------
    op.add_column("task", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.create_index("uq_task_idempotency_key", "task", ["idempotency_key"], unique=True)


def downgrade() -> None:
    """回滚：**只 drop 本批自有对象**（先删 ``task.idempotency_key``，再反序删 4 表）。

    🔴 **不 DROP 既有表 / 列**；**不 DROP EXTENSION**。
    """
    dialect = op.get_bind().dialect.name

    # 1. task.idempotency_key：先删唯一索引，再删列。
    op.drop_index("uq_task_idempotency_key", table_name="task")
    if dialect == "sqlite":  # pragma: no cover - 依赖 SQLite 环境
        with op.batch_alter_table("task") as batch_op:
            batch_op.drop_column("idempotency_key")
    else:
        op.drop_column("task", "idempotency_key")

    # 2. 反序删除 4 表（先删索引非必需：随表 DROP；显式 drop 以对齐 upgrade 可读性）。
    op.drop_index("ix_schedule_next_run_at", table_name="schedule")
    op.drop_index("ix_schedule_workspace_id", table_name="schedule")
    op.drop_index("ix_schedule_organization_id", table_name="schedule")
    op.drop_index("ix_schedule_tenant_id", table_name="schedule")
    op.drop_table("schedule")

    op.drop_index("ix_task_execution_task_id", table_name="task_execution")
    op.drop_table("task_execution")

    op.drop_index("ix_workspace_environment_workspace_id", table_name="workspace_environment")
    op.drop_index("ix_workspace_environment_organization_id", table_name="workspace_environment")
    op.drop_index("ix_workspace_environment_tenant_id", table_name="workspace_environment")
    op.drop_table("workspace_environment")

    op.drop_index("ix_project_workspace_id", table_name="project")
    op.drop_index("ix_project_organization_id", table_name="project")
    op.drop_index("ix_project_tenant_id", table_name="project")
    op.drop_table("project")
