"""Phase 2 · W7 / T2-40：核心资源 ``organization_id`` 迁移（``0016_phase2_organization_scope``）。

Revision ID: 0016_phase2_organization_scope
Revises: 0015_phase2_workspace_task
Create Date: 2026-10-12

设计依据：设计 §2.15.4（A-7）「确保每 Tenant 存在默认 Organization；``workspace`` 增加并回填
``organization_id``；Phase 0–2 其他租户业务资源增加可空 ``organization_id``，按所属 Workspace
回填，否则回填默认 Organization；显式全局资源保持 NULL」；**W7 开工前架构裁定** §4.2（五步
S1–S5）/ §4.3（回填边界 L1/L2/L3）/ R7 / R8 / R9 / R11 / R-open#5；team-lead 拍板 R1–R14。

五步（**先加列 → 建默认组织 → 回填 → 验证 → 建约束/索引**）：

- **S1 加可空列 + 外键**：对 L1 表（有 ``tenant_id`` 的租户资源根）``ALTER TABLE ADD COLUMN
  organization_id <UUID> NULL`` + ``fk_<表>_organization_id`` 外键（**幂等**：先查
  ``information_schema``（PG）/ ``PRAGMA table_info``（SQLite）判定缺列；SQLite 经
  ``op.batch_alter_table`` copy-and-move 加列 + 建 FK，PG 直接 ``add_column`` +
  ``create_foreign_key``）；🔴 ``project`` / ``workspace_environment`` / ``schedule`` 的可空列 +
  组织索引 + **FK**（``fk_project_organization_id`` 等）**已在 ``0015`` 建表即含**（R-open#2）→
  **跳过**；``audit_log.organization_id`` **已存在且已带 FK**
  （``fk_audit_log_organization_id``，Phase 1 / ``0006_phase1_conversation.py``，F11/R7）→ 本迁移
  **只回填**（不加列、不建 FK、不 drop）；
- **S2 建默认组织**：对 ``tenant`` 中**每个** tenant，若无 ``slug='default'`` 的组织，则
  ``INSERT organization(tenant_id, name, slug='default')``（复用 ``DEFAULT_ORG_SLUG/NAME``，F15
  口径；**幂等**；**不依赖应用层 bootstrap 已执行**，R11）；
- **S3 回填**：``workspace`` → 该 tenant 默认组织；有 ``workspace_id`` 的表经 ``workspace``
  推导，**推导为空者**回填默认组织；无 ``workspace_id`` 的表（``tool`` / ``skill``）回填默认
  组织（🔴 全局内置 ``tool``（``source='builtin'``）**保持 NULL**）；``audit_log`` 经
  ``workspace_id`` / ``run_id`` 推导，无则默认组织；
- **S4 验证无遗漏**：断言每表业务资源行 ``organization_id IS NULL`` 计数为 **0**
  （**显式全局资源除外**：``source='builtin'`` 的 ``tool``）——同时落 ``test_0016.py``；
- **S5 建约束/索引**：对**新增列的 L1 表**建 ``ix_<表>_organization_id``
  （🔴 **跳过** ``project`` / ``workspace_environment`` / ``schedule``，``0015`` 已建）；
  🔴 ``workspace.organization_id`` **保持可空**（仅建索引，不设 NOT NULL，R-open#5）。

约定：

- 🔴 **单 head 线性**：``down_revision = "0015_phase2_workspace_task"``；
- 🔴 **显式方言分支** ``op.get_bind().dialect.name``（**禁 try/except 推断**，F16）；
- 🔴 **``organization_id`` 统一口径 = 可空列 + 组织索引 + 外键**（``fk_<表>_organization_id``，
  镜像 ``membership``（0001）/ ``project``（0015）先例；裁定 §14.1）。SQLite 对既有表无法
  ``ALTER ADD CONSTRAINT``（Alembic 非 batch ``add_column`` 携带 FK 亦抛 ``NotImplementedError``）
  → 必须经 ``op.batch_alter_table`` copy-and-move；``audit_log``（Phase 1 既有列 + 既有 FK
  ``fk_audit_log_organization_id``）**不在本迁移范围**（只回填），保持不动；
- 🔴 **不 ``DROP EXTENSION vector``**（承接 QA-31）；**不改变 Tenant 硬隔离**（I-1/I-2）；
  ``resource_permission`` **不加列**（R8 拍板）；``model_provider`` **纳入 L1**（R9 拍板）；
  **无枚举迁移动作**（R10）。

``downgrade``（**只移除本迁移新增的列/索引，不删数据 / 组织 / EXTENSION**）：

1. ``DROP INDEX ix_<表>_organization_id``（仅本迁移为新增列的 L1 表所建）；
2. ``ALTER TABLE <表> DROP CONSTRAINT fk_<表>_organization_id`` + ``DROP COLUMN
   organization_id``（SQLite 走 ``op.batch_alter_table``；🔴 ``audit_log`` **不得 drop**——其列非
   本迁移新增；🔴 ``project`` / ``workspace_environment`` / ``schedule`` **除外**——列/约束归
   ``0015``）；
3. **不 ``DELETE FROM organization``**；**不改回 workspace 组织**；**不 ``DROP EXTENSION``**。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_common.time import utcnow
from astra_core import generate_id
from astra_database.types import GUID
from astra_domain.constants import DEFAULT_ORG_NAME, DEFAULT_ORG_SLUG

# revision identifiers, used by Alembic.
revision: str = "0016_phase2_organization_scope"
down_revision: str | None = "0015_phase2_workspace_task"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: L1 表（**本迁移加列 + 建索引**）——据 W7 裁定 §4.3「L1 · 直接加列 + 回填」。
#: 🔴 不含已在 ``0015`` 建列（``project`` / ``workspace_environment`` / ``schedule``）与
#: 已有列（``audit_log``，Phase 1）的表。
L1_ADD_COLUMN_TABLES: tuple[str, ...] = (
    "workspace",
    "agent",
    "conversation",
    "credential",
    "knowledge_base",
    "mcp_server",
    "memory",
    "task",
    "workflow",
    "model_provider",
    "tool",
    "skill",
)

#: 有 ``workspace_id`` 的 L1 表（**经 workspace 推导**回填；含 ``0015`` 建列的 3 表）。
WORKSPACE_DERIVED_TABLES: tuple[str, ...] = (
    "agent",
    "conversation",
    "credential",
    "knowledge_base",
    "mcp_server",
    "memory",
    "task",
    "workflow",
    "model_provider",
    "project",
    "workspace_environment",
    "schedule",
)

#: 无 ``workspace_id`` 的 L1 表（**直接回填默认组织**）。
DEFAULT_ORG_TABLES: tuple[str, ...] = ("workspace", "skill")

#: S4 验证覆盖的业务资源表（🔴 显式全局资源除外：``source='builtin'`` 的 ``tool``）。
VERIFY_TABLES: tuple[str, ...] = (
    *L1_ADD_COLUMN_TABLES,
    "project",
    "workspace_environment",
    "schedule",
    "audit_log",
)


def _organization_table() -> sa.TableClause:
    """返回 ``organization`` 的最小 table 构造（供默认组织 insert）。"""
    return sa.table(
        "organization",
        sa.column("id", GUID()),
        sa.column("tenant_id", GUID()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _column_exists(bind: sa.Connection, table: str, column: str) -> bool:
    """判定 ``table.column`` 是否已存在（显式方言分支，**禁 try/except 推断**）。"""
    dialect = bind.dialect.name
    if dialect == "postgresql":
        statement = sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table_name AND column_name = :column_name LIMIT 1"
        )
        return (
            bind.execute(statement, {"table_name": table, "column_name": column}).first()
            is not None
        )
    # SQLite（及社区兼容回退口径）：PRAGMA table_info 的第 2 列为列名。
    rows = bind.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
    return any(row[1] == column for row in rows)


def _index_exists(bind: sa.Connection, table: str, index: str) -> bool:
    """判定 ``table`` 上是否已存在名为 ``index`` 的索引（显式方言分支）。"""
    dialect = bind.dialect.name
    if dialect == "postgresql":
        statement = sa.text(
            "SELECT 1 FROM pg_indexes WHERE tablename = :table_name AND indexname = :index_name "
            "LIMIT 1"
        )
        return (
            bind.execute(statement, {"table_name": table, "index_name": index}).first() is not None
        )
    rows = bind.exec_driver_sql(f'PRAGMA index_list("{table}")').fetchall()
    return any(row[1] == index for row in rows)


def _fk_exists(bind: sa.Connection, table: str, fk_name: str) -> bool:
    """判定 ``table`` 上是否已存在名为 ``fk_name`` 的外键（显式方言分支）。"""
    dialect = bind.dialect.name
    if dialect == "postgresql":
        statement = sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table_name AND constraint_name = :fk_name "
            "AND constraint_type = 'FOREIGN KEY' LIMIT 1"
        )
        return (
            bind.execute(statement, {"table_name": table, "fk_name": fk_name}).first() is not None
        )
    # SQLite：外键名随表 DDL 存于 ``sqlite_master``（``PRAGMA foreign_key_list`` 不含约束名）。
    row = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
        {"table_name": table},
    ).first()
    ddl = str(row[0]) if row and row[0] else ""
    return fk_name in ddl


def _default_org_subquery(table: str) -> str:
    """返回「该行 tenant 的默认组织 id」标量子查询 SQL（``table`` 为相关外部表名）。"""
    return (
        f"(SELECT o.id FROM organization o "
        f"WHERE o.tenant_id = {table}.tenant_id AND o.slug = :org_slug LIMIT 1)"
    )


def _create_organization_fk(table: str, fk_name: str, dialect: str) -> None:
    """补建 ``fk_<表>_organization_id``（列已存在、仅缺 FK 的幂等回补路径）。"""
    if dialect == "sqlite":
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(fk_name, "organization", ["organization_id"], ["id"])
    else:
        op.create_foreign_key(fk_name, table, "organization", ["organization_id"], ["id"])


def _add_organization_columns() -> None:
    """S1：为 L1 表加**可空** ``organization_id`` 列 + ``fk_<表>_organization_id`` 外键。

    🔴 统一口径（裁定 §14.1）= 可空列 + 组织索引（S5）+ **FK**，镜像 ``membership``（0001）/
    ``project``（0015）先例。机制**显式方言分支**（禁 try/except 推断）：SQLite 走
    ``op.batch_alter_table`` copy-and-move（SQLite 不支持对既有表 ``ALTER ADD CONSTRAINT``；
    Alembic 非 batch ``add_column`` 携带 FK 亦抛 ``NotImplementedError``）；PG 直接
    ``add_column`` + ``create_foreign_key``。**幂等**：列已存在则跳过（仅缺 FK 时补建）。
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table in L1_ADD_COLUMN_TABLES:
        fk_name = f"fk_{table}_organization_id"
        if _column_exists(bind, table, "organization_id"):
            if not _fk_exists(bind, table, fk_name):
                _create_organization_fk(table, fk_name, dialect)
            continue
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(sa.Column("organization_id", GUID(), nullable=True))
                batch_op.create_foreign_key(fk_name, "organization", ["organization_id"], ["id"])
        else:
            op.add_column(table, sa.Column("organization_id", GUID(), nullable=True))
            op.create_foreign_key(fk_name, table, "organization", ["organization_id"], ["id"])


def _ensure_default_organizations() -> None:
    """S2：对每个 tenant 幂等确保存在 ``slug='default'`` 的默认组织（R11）。

    覆盖口径 = ``tenant`` 表全体 tenant ∪ **业务资源行中出现的 tenant_id**
    （承接既有库「业务行经裸 SQL 直插、绕过 ``tenant`` FK」的真实状态；保证 S3 兜底
    回填总能命中默认组织，S4 无遗漏）。
    """
    bind = op.get_bind()
    tenant_ids: set[str] = {
        str(row) for row in bind.execute(sa.text("SELECT id FROM tenant")).scalars().all()
    }
    for table in VERIFY_TABLES:
        if not _column_exists(bind, table, "tenant_id"):
            continue
        rows = (
            bind.execute(
                sa.text(f"SELECT DISTINCT tenant_id FROM {table} WHERE tenant_id IS NOT NULL")
            )
            .scalars()
            .all()
        )
        tenant_ids.update(str(row) for row in rows)

    organization = _organization_table()
    now = utcnow()
    for tenant_id in sorted(tenant_ids):
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM organization "
                "WHERE tenant_id = :tenant_id AND slug = :slug LIMIT 1"
            ),
            {"tenant_id": tenant_id, "slug": DEFAULT_ORG_SLUG},
        ).first()
        if exists is not None:
            continue
        bind.execute(
            organization.insert().values(
                id=generate_id(),
                tenant_id=tenant_id,
                name=DEFAULT_ORG_NAME,
                slug=DEFAULT_ORG_SLUG,
                created_at=now,
                updated_at=now,
            )
        )


def _backfill_organizations() -> None:
    """S3：回填 ``organization_id``。

    ``workspace`` → 默认组织；子资源经 ``workspace`` 推导，否则回填默认组织。
    """
    bind = op.get_bind()
    params = {"org_slug": DEFAULT_ORG_SLUG}

    # ① workspace：直接回填该 tenant 的默认组织。
    bind.execute(
        sa.text(
            f"UPDATE workspace SET organization_id = {_default_org_subquery('workspace')} "
            f"WHERE organization_id IS NULL"
        ),
        params,
    )

    # ② 有 workspace_id 的表：先经 workspace 推导，推导为空者再回填默认组织。
    for table in WORKSPACE_DERIVED_TABLES:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = "
                f"(SELECT w.organization_id FROM workspace w WHERE w.id = {table}.workspace_id) "
                f"WHERE organization_id IS NULL AND workspace_id IS NOT NULL"
            )
        )
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = {_default_org_subquery(table)} "
                f"WHERE organization_id IS NULL"
            ),
            params,
        )

    # ③ 无 workspace_id 的表（workspace / skill）：直接回填默认组织。
    for table in DEFAULT_ORG_TABLES:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = {_default_org_subquery(table)} "
                f"WHERE organization_id IS NULL"
            ),
            params,
        )

    # ③' tool：默认组织；🔴 全局内置 Tool（source='builtin'）保持 NULL。
    bind.execute(
        sa.text(
            f"UPDATE tool SET organization_id = {_default_org_subquery('tool')} "
            f"WHERE organization_id IS NULL AND source <> 'builtin' AND tenant_id IS NOT NULL"
        ),
        params,
    )

    # ④ audit_log（列已存在，仅回填）：经 workspace_id 推导。
    bind.execute(
        sa.text(
            "UPDATE audit_log SET organization_id = "
            "(SELECT w.organization_id FROM workspace w WHERE w.id = audit_log.workspace_id) "
            "WHERE organization_id IS NULL AND workspace_id IS NOT NULL"
        )
    )
    # ④' audit_log：经 run_id → agent_run → conversation → workspace 推导。
    bind.execute(
        sa.text(
            "UPDATE audit_log SET organization_id = "
            "(SELECT w.organization_id FROM workspace w "
            "JOIN conversation c ON c.workspace_id = w.id "
            "JOIN agent_run ar ON ar.conversation_id = c.id "
            "WHERE ar.id = audit_log.run_id LIMIT 1) "
            "WHERE organization_id IS NULL AND run_id IS NOT NULL"
        )
    )
    # ④'' audit_log：兜底默认组织。
    bind.execute(
        sa.text(
            f"UPDATE audit_log SET organization_id = {_default_org_subquery('audit_log')} "
            f"WHERE organization_id IS NULL"
        ),
        params,
    )


def _verify_no_unassigned() -> None:
    """S4：断言每张业务资源表的 ``organization_id IS NULL`` 计数为 0（**显式全局资源除外**）。"""
    bind = op.get_bind()
    unassigned: dict[str, int] = {}
    for table in VERIFY_TABLES:
        if table == "tool":
            condition = "organization_id IS NULL AND source <> 'builtin'"
        else:
            condition = "organization_id IS NULL"
        count = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {condition}")
        ).scalar_one()
        if count:
            unassigned[table] = int(count)
    if unassigned:
        raise RuntimeError(
            "0016 回填后仍有未分配 organization_id 的业务资源行（显式全局资源除外）："
            f"{unassigned}"
        )


def _create_organization_indexes() -> None:
    """S5：为**新增列的 L1 表**建 ``ix_<表>_organization_id``（幂等；跳过 ``0015`` 已建者）。"""
    bind = op.get_bind()
    for table in L1_ADD_COLUMN_TABLES:
        index_name = f"ix_{table}_organization_id"
        if _index_exists(bind, table, index_name):
            continue
        op.create_index(index_name, table, ["organization_id"])


def upgrade() -> None:
    """五步迁移：加列 → 建默认组织 → 回填 → 验证无遗漏 → 建索引。"""
    _add_organization_columns()
    _ensure_default_organizations()
    _backfill_organizations()
    _verify_no_unassigned()
    _create_organization_indexes()


def downgrade() -> None:
    """回滚：**只移除本迁移新增的列 / 索引**（不删数据 / 组织 / EXTENSION）。

    🔴 ``audit_log`` 的 ``organization_id``（Phase 1 落地）**不得 drop**；
    🔴 ``project`` / ``workspace_environment`` / ``schedule`` 的列归 ``0015``，**不由本迁移 drop**。
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. 删本迁移为新增列的 L1 表所建的索引。
    for table in reversed(L1_ADD_COLUMN_TABLES):
        index_name = f"ix_{table}_organization_id"
        if _index_exists(bind, table, index_name):
            op.drop_index(index_name, table_name=table)

    # 2. 删本迁移新增的列 + 外键（显式方言分支；``audit_log`` / ``project`` /
    #    ``workspace_environment`` / ``schedule`` 除外）。
    for table in reversed(L1_ADD_COLUMN_TABLES):
        if not _column_exists(bind, table, "organization_id"):
            continue
        fk_name = f"fk_{table}_organization_id"
        drop_fk = _fk_exists(bind, table, fk_name)
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                if drop_fk:
                    batch_op.drop_constraint(fk_name, type_="foreignkey")
                batch_op.drop_column("organization_id")
        else:
            if drop_fk:
                op.drop_constraint(fk_name, table, type_="foreignkey")
            op.drop_column(table, "organization_id")

    # 3. 不 DELETE organization；不改回 workspace 组织；不 DROP EXTENSION。
