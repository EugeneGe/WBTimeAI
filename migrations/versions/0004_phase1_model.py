"""Phase 1 · T1-06：Model 组表（``model_provider`` / ``model``）。

Revision ID: 0004_phase1_model
Revises: 0003_phase1_agent
Create Date: 2025-01-04

设计依据：设计 §2.15.1（Model 组）/ §2.15.2（凭证**复用** ``credential``）。

约定：
- **纯新增**：仅创建 2 张 Model 组表，**不改动**既有表；
- 主键 UUIDv7；``model_provider`` 带 ``tenant_id``；
- ``model_provider.credential_id → credential.id``（**复用** 0001 既有凭证表，
  **不建** ``model_credential`` 平行存储，C-07）；
- JSON 走 ``JSONType``；
- ``downgrade`` 逆序删除（C-05）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0004_phase1_model"
down_revision: str | None = "0003_phase1_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 ``model_provider`` / ``model``。"""
    # -- 1. model_provider ---------------------------------------------------
    op.create_table(
        "model_provider",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=True),
        sa.Column("credential_id", GUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("config", JSONType(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_model_provider_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_model_provider_workspace_id"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], name="fk_model_provider_credential_id"
        ),
    )
    op.create_index("ix_model_provider_tenant_id", "model_provider", ["tenant_id"])
    op.create_index("ix_model_provider_workspace_id", "model_provider", ["workspace_id"])
    op.create_index("ix_model_provider_credential_id", "model_provider", ["credential_id"])

    # -- 2. model ------------------------------------------------------------
    op.create_table(
        "model",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("provider_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("capabilities", JSONType(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["model_provider.id"], name="fk_model_provider_id"
        ),
    )
    op.create_index("ix_model_provider_id", "model", ["provider_id"])


def downgrade() -> None:
    """回滚：逆序删除 Model 组表。"""
    op.drop_index("ix_model_provider_id", table_name="model")
    op.drop_table("model")
    op.drop_index("ix_model_provider_credential_id", table_name="model_provider")
    op.drop_index("ix_model_provider_workspace_id", table_name="model_provider")
    op.drop_index("ix_model_provider_tenant_id", table_name="model_provider")
    op.drop_table("model_provider")
