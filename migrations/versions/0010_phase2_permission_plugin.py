"""Phase 2 · W3 / T2-13：权限 / 插件 / 审批表（``resource_permission`` / ``plugin`` /
``approval``）+ ``tool_permission`` **归档**（保留表 + 回填 + 标注，不 drop）。

Revision ID: 0010_phase2_permission_plugin
Revises: 0009_phase2_mcp
Create Date: 2026-10-09

设计依据：设计 §2.10 / §2.10.1 / §2.15.1 / §2.15.4；W3 裁定 §1 / §3 / Erratum-E/F/G。

约定：
- **单 revision**（权威口径，W3 裁定 §3.1）：`resource_permission`（2a）+ `plugin`（2a 部分）+
  **`tool_permission` 归档（回填 + 标注，不 drop）** + **`approval` 表**（2a）同批；**禁用
  `0010b`**（已废弃）；
- 唯一键：`resource_permission` ``(tenant_id, subject_type, subject_id, resource_type,
  resource_id, action)``；
- **类型级（``resource_id IS NULL``）唯一性由应用层 upsert 保证**（SQL 唯一约束不判重 NULL）；
- 回填：把既有 `tool_permission`（`ALLOW`/`DENY`，`agent_id` 非空）转成
  `resource_permission(subject_type='agent', resource_type='TOOL', resource_id=tool_id,
  action=action, effect=effect, scope={})`；**幂等**（6 键判存）；
- `tool_permission` 表**保留**（不 drop），仅**标注**「默认策略模板 / deprecated 运行期判定源」；
- 方言差异**显式**按 ``op.get_bind().dialect.name`` 分支（**禁 try/except**）；
- ``downgrade`` 逆序删除 `approval`/`plugin`/`resource_permission`（**不 drop**
  `tool_permission`）。

🔴 不可逆：``downgrade`` DROP 三表 → **权限 / 插件 / 审批数据丢失**；`tool_permission`
   **保留**（回填到 `resource_permission` 的行随 DROP 消失，原文仍存于 `tool_permission`，可重放）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_common.time import utcnow
from astra_core import generate_id
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0010_phase2_permission_plugin"
down_revision: str | None = "0009_phase2_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `tool_permission` 归档标注（PG 表注释；SQLite 无表注释能力，跳过）。
_TOOL_PERMISSION_ARCHIVE_COMMENT = (
    "deprecated: default-policy template only; runtime permission source is "
    "resource_permission + agent_tool.permission_scope (W3 §1.2)"
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


def _create_resource_permission() -> None:
    """建 ``resource_permission``（主体级授权；设计 §2.10）。"""
    op.create_table(
        "resource_permission",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", GUID(), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False),
        sa.Column("resource_id", GUID(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("effect", sa.String(length=10), nullable=False),
        sa.Column("scope", JSONType(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_resource_permission_tenant_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_resource_permission_subject_resource_action",
        ),
    )
    op.create_index("ix_resource_permission_tenant_id", "resource_permission", ["tenant_id"])
    op.create_index(
        "ix_resource_permission_subject",
        "resource_permission",
        ["tenant_id", "subject_type", "subject_id"],
    )
    op.create_index(
        "ix_resource_permission_resource",
        "resource_permission",
        ["tenant_id", "resource_type", "resource_id"],
    )


def _drop_resource_permission() -> None:
    """删 ``resource_permission``。"""
    op.drop_index("ix_resource_permission_resource", table_name="resource_permission")
    op.drop_index("ix_resource_permission_subject", table_name="resource_permission")
    op.drop_index("ix_resource_permission_tenant_id", table_name="resource_permission")
    op.drop_table("resource_permission")


def _create_plugin() -> None:
    """建 ``plugin``（W1b T2-05 模型类；表随本迁移落地）。"""
    op.create_table(
        "plugin",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("entry_point", sa.String(length=255), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *_timestamps(),
    )
    op.create_index("ix_plugin_name", "plugin", ["name"], unique=True)


def _drop_plugin() -> None:
    """删 ``plugin``。"""
    op.drop_index("ix_plugin_name", table_name="plugin")
    op.drop_table("plugin")


def _create_approval() -> None:
    """建 ``approval``（基础审批表；机制接线归 2b T2-26，零迁移）。"""
    op.create_table(
        "approval",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_ref", sa.String(length=255), nullable=False),
        sa.Column("requested_by", GUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_by", GUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", JSONType(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_approval_tenant_id"),
        sa.ForeignKeyConstraint(["requested_by"], ["user.id"], name="fk_approval_requested_by"),
        sa.ForeignKeyConstraint(["decided_by"], ["user.id"], name="fk_approval_decided_by"),
    )
    op.create_index("ix_approval_tenant_id", "approval", ["tenant_id"])


def _drop_approval() -> None:
    """删 ``approval``。"""
    op.drop_index("ix_approval_tenant_id", table_name="approval")
    op.drop_table("approval")


def _resource_permission_table() -> sa.TableClause:
    """返回 ``resource_permission`` 的最小 table 构造（供回填 insert）。"""
    return sa.table(
        "resource_permission",
        sa.column("id", GUID()),
        sa.column("tenant_id", GUID()),
        sa.column("subject_type", sa.String()),
        sa.column("subject_id", GUID()),
        sa.column("resource_type", sa.String()),
        sa.column("resource_id", GUID()),
        sa.column("action", sa.String()),
        sa.column("effect", sa.String()),
        sa.column("scope", JSONType()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _backfill_tool_permissions() -> None:
    """把既有 ``tool_permission``（agent 绑定，``ALLOW``/``DENY``）**幂等**回填到
    ``resource_permission``（W3 裁定 §1.2）。"""
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT tenant_id, agent_id, tool_id, action, effect "
                "FROM tool_permission "
                "WHERE agent_id IS NOT NULL AND effect IN ('ALLOW', 'DENY')"
            )
        )
        .mappings()
        .all()
    )
    rp = _resource_permission_table()
    now = utcnow()
    for row in rows:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM resource_permission "
                "WHERE tenant_id = :tenant_id AND subject_type = 'agent' "
                "AND subject_id = :subject_id AND resource_type = 'TOOL' "
                "AND resource_id = :resource_id AND action = :action LIMIT 1"
            ),
            {
                "tenant_id": str(row["tenant_id"]),
                "subject_id": str(row["agent_id"]),
                "resource_id": str(row["tool_id"]),
                "action": str(row["action"]),
            },
        ).first()
        if exists is not None:
            continue
        bind.execute(
            rp.insert().values(
                id=generate_id(),
                tenant_id=str(row["tenant_id"]),
                subject_type="agent",
                subject_id=str(row["agent_id"]),
                resource_type="TOOL",
                resource_id=str(row["tool_id"]),
                action=str(row["action"]),
                effect=str(row["effect"]),
                scope={},
                created_at=now,
                updated_at=now,
            )
        )


def _annotate_tool_permission_deprecated() -> None:
    """标注 ``tool_permission`` 为「默认策略模板 / deprecated 运行期判定源」（显式方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text("COMMENT ON TABLE tool_permission IS " f"'{_TOOL_PERMISSION_ARCHIVE_COMMENT}'")
        )
    # SQLite 无表注释能力：归档语义落文档（README §8.4）+ ORM/迁移注释。


def upgrade() -> None:
    """建三表 → 回填 ``tool_permission`` → 标注归档。"""
    _create_resource_permission()
    _create_plugin()
    _create_approval()
    _backfill_tool_permissions()
    _annotate_tool_permission_deprecated()


def downgrade() -> None:
    """逆序删除三表（**不 drop** ``tool_permission``；回填行随 DROP 消失，可重放）。"""
    _drop_approval()
    _drop_plugin()
    _drop_resource_permission()
