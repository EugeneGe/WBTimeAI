"""Phase 1 · W5 / T1-26：``task.execution_mode`` 列（INLINE | QUEUED）。

Revision ID: 0007_phase1_task_execution_mode
Revises: 0006_phase1_conversation
Create Date: 2026-10-08

设计依据：设计 §2.11 / §2.15.1 / §3-#12（``task`` 增 ``execution_mode(INLINE|QUEUED)`` 列；
INLINE 路径 ``CREATED → RUNNING`` 跳过 ``PENDING``）。

说明：``task`` 表建于 ``0001_phase0_baseline``（**无** ``execution_mode``）；本迁移为
Phase 0 既有表**加列**，**不改 ``0006``**。``alembic`` 已启用 ``render_as_batch=True``，
故 SQLite 下自动以 batch 模式执行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_phase1_task_execution_mode"
down_revision: str | None = "0006_phase1_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 ``task`` 表新增 ``execution_mode`` 列（``NOT NULL``，默认 ``INLINE``）。"""
    op.add_column(
        "task",
        sa.Column(
            "execution_mode",
            sa.String(length=20),
            nullable=False,
            server_default="INLINE",
        ),
    )


def downgrade() -> None:
    """删除 ``task.execution_mode`` 列。"""
    op.drop_column("task", "execution_mode")
