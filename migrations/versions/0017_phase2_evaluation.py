"""Phase 2 · W9 / T2-45：Evaluation 组表（``evaluation_dataset`` / ``evaluation_case`` /
``evaluation_run`` / ``evaluation_result``）——（``0017_phase2_evaluation``）。

Revision ID: 0017_phase2_evaluation
Revises: 0016_phase2_organization_scope
Create Date: 2026-10-13

设计依据：设计 §2.13.2（Agent Evaluation 最小闭环：四实体）/ §2.15.4（迁移批次 + A-7 组织范围）；
**W9 开工前架构裁定** §3（四表结构 / 唯一键 / 双向步骤 / 方言）+ R3（组织范围列落点）/
R6（assertions schema）/ R12（``version`` 为 Integer）。

约定：

- **纯新增**：仅创建 4 张 Evaluation 组表；**不改动** ``0001–0016`` 任何表；
- 🔴 **单 head 线性**：``down_revision = "0016_phase2_organization_scope"``；
- 🔴 **显式方言分支** ``op.get_bind().dialect.name``（**禁 try/except 推断**）——本迁移
  **无 pgvector / 无扩展动作 / 无枚举动作**，四表 DDL 由 ``GUID`` / ``JSONType`` 的
  ``TypeDecorator`` 吸收方言差异，故两分支**同构**；
- 🔴 **组织范围落点（R3）**：``evaluation_dataset`` / ``evaluation_run`` 落**直接列**
  ``organization_id``（可空 + 索引 + FK，镜像 ``0016`` L1）+ ``workspace_id``（可空 + 索引 +
  FK）；``evaluation_case`` / ``evaluation_result`` **经父推导**（**不下**组织列，镜像
  ``memory_relation``）；
- 🔴 **唯一键**：``evaluation_case`` ``(dataset_id, case_key)``；
  ``evaluation_run`` ``(idempotency_key)``（**可空唯一**，NULL 可重复）；
  ``evaluation_result`` ``(evaluation_run_id, case_id)``；
- 🔴 每表列 + 唯一约束 + 索引**建表即含**（镜像 ``0015`` 一次到位；**无回填**——
  表为新建、无历史行）；
- 🔴 枚举列一律 ``String(50)``（app 层词表，**无 DB enum**）；主键 UUIDv7（``GUID``）；时间戳 UTC。

``downgrade``（**只 ``DROP`` 本迁移自有四表**）：逆序 ``evaluation_result`` → ``evaluation_run`` →
``evaluation_case`` → ``evaluation_dataset``（**子先父后**）；🔴 **不 ``DROP EXTENSION vector``**
（承接 QA-31）；**不动任何既有表 / 列 / 索引**。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0017_phase2_evaluation"
down_revision: str | None = "0016_phase2_organization_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 四表名（**建表顺序**：父先子后）。
_TABLE_ORDER: tuple[str, ...] = (
    "evaluation_dataset",
    "evaluation_case",
    "evaluation_run",
    "evaluation_result",
)


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
    """返回仅 ``created_at`` 的时间戳列（UTC；子资源用）。"""
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _create_dataset() -> None:
    """① ``evaluation_dataset``（L1 租户资源根；直接列 org + ws）。"""
    op.create_table(
        "evaluation_dataset",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_dataset_id", GUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("created_by", GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_evaluation_dataset_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_evaluation_dataset_organization_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_evaluation_dataset_workspace_id"
        ),
        sa.ForeignKeyConstraint(
            ["parent_dataset_id"],
            ["evaluation_dataset.id"],
            name="fk_evaluation_dataset_parent_dataset_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name="fk_evaluation_dataset_created_by"
        ),
    )
    op.create_index("ix_evaluation_dataset_tenant_id", "evaluation_dataset", ["tenant_id"])
    op.create_index(
        "ix_evaluation_dataset_organization_id", "evaluation_dataset", ["organization_id"]
    )
    op.create_index("ix_evaluation_dataset_workspace_id", "evaluation_dataset", ["workspace_id"])


def _create_case() -> None:
    """② ``evaluation_case``（子资源；唯一键 ``(dataset_id, case_key)``）。"""
    op.create_table(
        "evaluation_case",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("dataset_id", GUID(), nullable=False),
        sa.Column("case_key", sa.String(length=255), nullable=False),
        sa.Column("input", JSONType(), nullable=False),
        sa.Column("expected", JSONType(), nullable=True),
        sa.Column("assertions", JSONType(), nullable=True),
        sa.Column("tags", JSONType(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["evaluation_dataset.id"], name="fk_evaluation_case_dataset_id"
        ),
        sa.UniqueConstraint("dataset_id", "case_key", name="uq_evaluation_case_dataset_case_key"),
    )
    op.create_index("ix_evaluation_case_dataset_id", "evaluation_case", ["dataset_id"])


def _create_run() -> None:
    """③ ``evaluation_run``（L1 租户资源根；``idempotency_key`` 可空唯一）。"""
    op.create_table(
        "evaluation_run",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("dataset_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("agent_version_id", GUID(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", JSONType(), nullable=True),
        sa.Column("created_by", GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_evaluation_run_tenant_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_evaluation_run_organization_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_evaluation_run_workspace_id"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["evaluation_dataset.id"], name="fk_evaluation_run_dataset_id"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], name="fk_evaluation_run_agent_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_version.id"], name="fk_evaluation_run_agent_version_id"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_evaluation_run_created_by"),
        sa.UniqueConstraint("idempotency_key", name="uq_evaluation_run_idempotency_key"),
    )
    op.create_index("ix_evaluation_run_tenant_id", "evaluation_run", ["tenant_id"])
    op.create_index("ix_evaluation_run_organization_id", "evaluation_run", ["organization_id"])
    op.create_index("ix_evaluation_run_workspace_id", "evaluation_run", ["workspace_id"])
    op.create_index("ix_evaluation_run_dataset_id", "evaluation_run", ["dataset_id"])
    op.create_index("ix_evaluation_run_agent_id", "evaluation_run", ["agent_id"])
    op.create_index("ix_evaluation_run_agent_version_id", "evaluation_run", ["agent_version_id"])


def _create_result() -> None:
    """④ ``evaluation_result``（子资源；唯一键 ``(evaluation_run_id, case_id)``）。"""
    op.create_table(
        "evaluation_result",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("evaluation_run_id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("agent_run_id", GUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("assertion_results", JSONType(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", JSONType(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["evaluation_run.id"], name="fk_evaluation_result_run_id"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["evaluation_case.id"], name="fk_evaluation_result_case_id"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_run.id"], name="fk_evaluation_result_agent_run_id"
        ),
        sa.UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_result_run_case"),
    )
    op.create_index(
        "ix_evaluation_result_evaluation_run_id", "evaluation_result", ["evaluation_run_id"]
    )
    op.create_index("ix_evaluation_result_case_id", "evaluation_result", ["case_id"])
    op.create_index("ix_evaluation_result_agent_run_id", "evaluation_result", ["agent_run_id"])


def _create_tables() -> None:
    """建四表（父先子后；列 + 唯一约束 + 索引建表即含；无回填）。"""
    _create_dataset()
    _create_case()
    _create_run()
    _create_result()


def upgrade() -> None:
    """创建 Evaluation 组四表（父先子后；无回填）。

    🔴 **显式方言分支** ``op.get_bind().dialect.name``（**禁 try/except 推断**）：本迁移无
    pgvector / 无扩展动作 / 无枚举动作，四表 DDL 由 ``GUID`` / ``JSONType`` 吸收方言差异，
    故 ``postgresql`` / ``sqlite`` / 其它社区方言分支**同构**（分支仅显式留痕）。
    """
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _create_tables()
    elif dialect == "sqlite":
        _create_tables()
    else:
        # 社区兼容方言（如 MySQL）：DDL 同构（类型由 TypeDecorator 吸收）。
        _create_tables()


def downgrade() -> None:
    """回滚：**逆序** ``DROP`` 四表（子先父后）；**不 ``DROP EXTENSION vector``**、不动既有表。"""
    op.drop_index("ix_evaluation_result_agent_run_id", table_name="evaluation_result")
    op.drop_index("ix_evaluation_result_case_id", table_name="evaluation_result")
    op.drop_index("ix_evaluation_result_evaluation_run_id", table_name="evaluation_result")
    op.drop_table("evaluation_result")

    op.drop_index("ix_evaluation_run_agent_version_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_agent_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_dataset_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_workspace_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_organization_id", table_name="evaluation_run")
    op.drop_index("ix_evaluation_run_tenant_id", table_name="evaluation_run")
    op.drop_table("evaluation_run")

    op.drop_index("ix_evaluation_case_dataset_id", table_name="evaluation_case")
    op.drop_table("evaluation_case")

    op.drop_index("ix_evaluation_dataset_workspace_id", table_name="evaluation_dataset")
    op.drop_index("ix_evaluation_dataset_organization_id", table_name="evaluation_dataset")
    op.drop_index("ix_evaluation_dataset_tenant_id", table_name="evaluation_dataset")
    op.drop_table("evaluation_dataset")
