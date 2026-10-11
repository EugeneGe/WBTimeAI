"""Phase 2 · W3 / T2-15：``credential`` 补 4 列（``name`` / ``status`` / ``last_used_at`` /
``metadata``）+ 新增关联表 ``model_provider_credential`` + 回填 ``model_provider.credential_id``。

Revision ID: 0011_phase2_credential_multi
Revises: 0010_phase2_permission_plugin
Create Date: 2026-10-09

设计依据：设计 §2.15.1 / §5 #16（A-10）；W3 裁定 §5 / Erratum-H。

约定：
- ``credential`` 补列：``name``（``String(150)`` nullable index）/ ``status``（``String(20)``
  NOT NULL default ``"ACTIVE"``）/ ``last_used_at``（``DateTime(tz)`` nullable）/
  ``metadata``（``JSONType`` NOT NULL default ``{}``）；
- 关联表 ``model_provider_credential``（``provider_id`` × ``credential_id`` × ``weight`` ×
  ``status``），唯一键 ``(provider_id, credential_id)``；
- **回填**：对每个 ``model_provider``（``credential_id IS NOT NULL``）插入一条
  ``(provider_id, credential_id, weight=1, status='ACTIVE')``；**幂等**（以
  ``(provider_id, credential_id)`` 判存，可重跑）；
- 旧列 ``model_provider.credential_id`` **deprecated 保留、不 drop**，回填后旧值**保留**；
- 方言差异**显式**按 ``op.get_bind().dialect.name`` 分支（**禁 try/except**）：
  SQLite 删列走 ``batch_alter_table``（兼容旧版 SQLite），PostgreSQL 走原生 ``DROP COLUMN``。

🔴 不可逆：``downgrade`` DROP 关联表 + ``credential`` 四补列 → **补列数据丢失**（须先备份，
   README §9.1 #6）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_common.time import utcnow
from astra_core import generate_id
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0011_phase2_credential_multi"
down_revision: str | None = "0010_phase2_permission_plugin"
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


def _add_credential_columns() -> None:
    """为 ``credential`` 补 4 列（``name`` / ``status`` / ``last_used_at`` / ``metadata``）。

    ``ALTER TABLE ADD COLUMN`` 在 SQLite / PostgreSQL 均受支持（NOT NULL 列带 ``server_default``）。
    ``metadata`` 的默认值按方言显式给出（PG ``'{}'::jsonb``；其它 ``'{}'``）。
    """
    dialect = op.get_bind().dialect.name
    metadata_default = sa.text("'{}'::jsonb") if dialect == "postgresql" else sa.text("'{}'")
    op.add_column("credential", sa.Column("name", sa.String(length=150), nullable=True))
    op.add_column(
        "credential",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
    )
    op.add_column(
        "credential", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "credential",
        sa.Column("metadata", JSONType(), nullable=False, server_default=metadata_default),
    )
    op.create_index("ix_credential_name", "credential", ["name"])


def _drop_credential_columns() -> None:
    """删 ``credential`` 四补列（**不可逆**；显式方言分支）。

    - PostgreSQL：原生 ``DROP COLUMN``；
    - SQLite：``batch_alter_table`` 重建表（兼容不支持 ``DROP COLUMN`` 的旧版 SQLite）。
    """
    dialect = op.get_bind().dialect.name
    op.drop_index("ix_credential_name", table_name="credential")
    if dialect == "postgresql":
        op.drop_column("credential", "metadata")
        op.drop_column("credential", "last_used_at")
        op.drop_column("credential", "status")
        op.drop_column("credential", "name")
    else:
        with op.batch_alter_table("credential") as batch_op:
            batch_op.drop_column("metadata")
            batch_op.drop_column("last_used_at")
            batch_op.drop_column("status")
            batch_op.drop_column("name")


def _create_model_provider_credential() -> None:
    """建 ``model_provider_credential``（多凭证关联；唯一键 ``(provider_id, credential_id)``）。"""
    op.create_table(
        "model_provider_credential",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("provider_id", GUID(), nullable=False),
        sa.Column("credential_id", GUID(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["model_provider.id"],
            name="fk_model_provider_credential_provider_id",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
            name="fk_model_provider_credential_credential_id",
        ),
        sa.UniqueConstraint("provider_id", "credential_id", name="uq_model_provider_credential"),
    )
    op.create_index(
        "ix_model_provider_credential_provider_id",
        "model_provider_credential",
        ["provider_id"],
    )
    op.create_index(
        "ix_model_provider_credential_credential_id",
        "model_provider_credential",
        ["credential_id"],
    )


def _drop_model_provider_credential() -> None:
    """删 ``model_provider_credential``。"""
    op.drop_index(
        "ix_model_provider_credential_credential_id",
        table_name="model_provider_credential",
    )
    op.drop_index(
        "ix_model_provider_credential_provider_id", table_name="model_provider_credential"
    )
    op.drop_table("model_provider_credential")


def _model_provider_credential_table() -> sa.TableClause:
    """返回关联表的最小 table 构造（供回填 insert）。"""
    return sa.table(
        "model_provider_credential",
        sa.column("id", GUID()),
        sa.column("provider_id", GUID()),
        sa.column("credential_id", GUID()),
        sa.column("weight", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _backfill_provider_credentials() -> None:
    """把既有 ``model_provider.credential_id`` **幂等**回填为关联记录（W3 裁定 §5.3）。"""
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text("SELECT id, credential_id FROM model_provider WHERE credential_id IS NOT NULL")
        )
        .mappings()
        .all()
    )
    table = _model_provider_credential_table()
    now = utcnow()
    for row in rows:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM model_provider_credential "
                "WHERE provider_id = :provider_id AND credential_id = :credential_id LIMIT 1"
            ),
            {"provider_id": str(row["id"]), "credential_id": str(row["credential_id"])},
        ).first()
        if exists is not None:
            continue
        bind.execute(
            table.insert().values(
                id=generate_id(),
                provider_id=str(row["id"]),
                credential_id=str(row["credential_id"]),
                weight=1,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )


def upgrade() -> None:
    """补列 → 建关联表 → 回填既有绑定。"""
    _add_credential_columns()
    _create_model_provider_credential()
    _backfill_provider_credentials()


def downgrade() -> None:
    """逆序删除关联表 + 四补列（**不可逆**，补列数据丢失）。"""
    _drop_model_provider_credential()
    _drop_credential_columns()
