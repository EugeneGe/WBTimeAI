"""Phase 2 · W2 / T2-07：Skill 组表（``skill`` / ``skill_version`` / ``skill_resource``
/ ``agent_skill``）。

Revision ID: 0008_phase2_skill
Revises: 0007_phase1_task_execution_mode
Create Date: 2026-10-09

设计依据：设计 §2.3 / §2.15.1 / §2.15.4；W2 裁定 §13.1（R13）。

约定：
- **纯新增**：仅创建 4 张 Skill 组表；**不改动** ``0001–0007`` 任何表；
- 主键 UUIDv7（``GUID`` 方言适配）；核心表带 ``tenant_id``；
- 时间戳 UTC（``DateTime(timezone=True)``）；JSON 走 ``JSONType``；
- 唯一键：``skill`` ``(tenant_id, name)``；``skill_version`` ``(skill_id, version)``；
  ``agent_skill`` ``(agent_version_id, skill_id)``（同构 ``agent_tool``）；
- ``skill.current_version_id → skill_version.id`` 因**双向引用**，在建表后以
  ``ALTER TABLE`` 追加外键（SQLite 经 batch 重建，PG 直接加约束）；
- 方言差异**显式**按 ``op.get_bind().dialect.name`` 分支（**禁 try/except**）；
- ``downgrade`` 逆序删除，保证往返干净（C-05）。

🔴 不可逆：``downgrade`` DROP 四表 → **Skill 数据丢失**；``skill_resource`` 的 ``Storage``
   对象（键 ``skills/{skill_id}/{version}/…``）**不随 downgrade 删除**，回滚须人工确认留痕
   （W2 裁定 §13.3 / README §9.1）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0008_phase2_skill"
down_revision: str | None = "0007_phase1_task_execution_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_skill_current_version_id"


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
    """为 ``skill.current_version_id → skill_version.id`` 追加外键（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("skill") as batch_op:
            batch_op.create_foreign_key(_FK_NAME, "skill_version", ["current_version_id"], ["id"])
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 加约束
        op.create_foreign_key(_FK_NAME, "skill", "skill_version", ["current_version_id"], ["id"])


def _drop_current_version_fk() -> None:
    """移除 ``skill.current_version_id`` 外键（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("skill") as batch_op:
            batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
    else:  # pragma: no cover - PG / 其它方言：直接 ALTER 删约束
        op.drop_constraint(_FK_NAME, "skill", type_="foreignkey")


def upgrade() -> None:
    """创建 ``skill`` / ``skill_version`` / ``skill_resource`` / ``agent_skill``。"""
    # -- 1. skill -----------------------------------------------------------
    op.create_table(
        "skill",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_version_id", GUID(), nullable=True),
        sa.Column("created_by", GUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_skill_tenant_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_skill_created_by"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_skill_tenant_name"),
    )
    op.create_index("ix_skill_tenant_id", "skill", ["tenant_id"])
    op.create_index("ix_skill_current_version_id", "skill", ["current_version_id"])
    op.create_index("ix_skill_created_by", "skill", ["created_by"])

    # -- 2. skill_version ---------------------------------------------------
    op.create_table(
        "skill_version",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("skill_id", GUID(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("manifest", JSONType(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", GUID(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], name="fk_skill_version_skill_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_skill_version_created_by"),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version_skill_version"),
    )
    op.create_index("ix_skill_version_skill_id", "skill_version", ["skill_id"])
    op.create_index("ix_skill_version_created_by", "skill_version", ["created_by"])

    # -- 3. skill_resource --------------------------------------------------
    op.create_table(
        "skill_resource",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("skill_version_id", GUID(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["skill_version_id"], ["skill_version.id"], name="fk_skill_resource_version_id"
        ),
    )
    op.create_index("ix_skill_resource_skill_version_id", "skill_resource", ["skill_version_id"])

    # -- 4. agent_skill -----------------------------------------------------
    op.create_table(
        "agent_skill",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_version_id", GUID(), nullable=False),
        sa.Column("skill_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_agent_skill_tenant_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"], ["agent_version.id"], name="fk_agent_skill_agent_version_id"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], name="fk_agent_skill_skill_id"),
        sa.UniqueConstraint("agent_version_id", "skill_id", name="uq_agent_skill_version_skill"),
    )
    op.create_index("ix_agent_skill_tenant_id", "agent_skill", ["tenant_id"])
    op.create_index("ix_agent_skill_agent_version_id", "agent_skill", ["agent_version_id"])
    op.create_index("ix_agent_skill_skill_id", "agent_skill", ["skill_id"])

    # -- 5. 双向引用：skill.current_version_id → skill_version.id -------------
    _add_current_version_fk()


def downgrade() -> None:
    """回滚：逆序删除 Skill 组表（Skill 数据丢失，见模块级不可逆说明）。"""
    _drop_current_version_fk()
    op.drop_index("ix_agent_skill_skill_id", table_name="agent_skill")
    op.drop_index("ix_agent_skill_agent_version_id", table_name="agent_skill")
    op.drop_index("ix_agent_skill_tenant_id", table_name="agent_skill")
    op.drop_table("agent_skill")
    op.drop_index("ix_skill_resource_skill_version_id", table_name="skill_resource")
    op.drop_table("skill_resource")
    op.drop_index("ix_skill_version_created_by", table_name="skill_version")
    op.drop_index("ix_skill_version_skill_id", table_name="skill_version")
    op.drop_table("skill_version")
    op.drop_index("ix_skill_created_by", table_name="skill")
    op.drop_index("ix_skill_current_version_id", table_name="skill")
    op.drop_index("ix_skill_tenant_id", table_name="skill")
    op.drop_table("skill")
