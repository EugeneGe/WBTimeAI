"""Phase 0 · T0-21：新增 ``feature_flag`` 覆盖表（纯新增，可 upgrade/downgrade）。

Revision ID: 0002_feature_flag
Revises: 0001_phase0_baseline
Create Date: 2025-01-02

约定：
- **纯新增**：仅创建 ``feature_flag`` 表（**不改动 0001 的任何表**）；
- **全局表**：Phase 0 不带 ``tenant_id``（平台级行为开关）；
- ``id`` 为 UUIDv7（以 ``GUID`` 方言适配类型存储为字符串）；
- 时间戳列统一 UTC（``DateTime(timezone=True)``）；
- ``name`` 建**唯一索引** ``ix_feature_flag_name``；
- ``downgrade`` 逆序删除索引与表，保证 ``upgrade`` / ``downgrade`` 往返干净。

⚠️ 本迁移仅提供**覆盖**存储：表缺失亦不影响应用启动（读取降级为空覆盖）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID

# revision identifiers, used by Alembic.
revision: str = "0002_feature_flag"
down_revision: str | None = "0001_phase0_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """返回统一的时间戳列定义（UTC）。"""
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
    """创建 ``feature_flag`` 表与唯一索引。"""
    op.create_table(
        "feature_flag",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_feature_flag_name", "feature_flag", ["name"], unique=True)


def downgrade() -> None:
    """回滚：删除索引与表。"""
    op.drop_index("ix_feature_flag_name", table_name="feature_flag")
    op.drop_table("feature_flag")
