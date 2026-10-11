"""Phase 2 · R2 / T2-57：远程 Attempt 元数据迁移（``0018_phase2_remote_workspace``）。

Revision ID: 0018_phase2_remote_workspace
Revises: 0017_phase2_evaluation
Create Date: 2026-10-14

设计依据：设计 §2.9.1 / §2.15.4–§2.15.5（远程开发工作站 · Attempt 元数据）；施工任务划分
§8.3 T2-57；**R1–R5 开工前架构裁定** §08.1（结构）/ §08.2（关键校正）/
§09（A-15 查重中止）/ §10（D-1/D-2 预修）/ §15（分层/纪律）/ §17（提交纪律）。

约定（**加性、单 head）**：

- 🔴 **仅扩展 ``task_execution``**（``packages/database/src/astra_database/models/task_ext.py``
  的 :class:`TaskExecution` ORM 与之**严格对齐**），**加性可空列**（**不回填假值**，
  历史行保持合法）；**不改写 / 重排 ``0001–0017``**，**不新增平行业务表**；
- 🔴 **单 head 线性**：``down_revision = "0017_phase2_evaluation"``；
- **新增 8 列（全部可空）**：``project_id``（``GUID`` / FK ``project.id`` **RESTRICT**）/
  ``checkout_ref``（``String(128)``，不透明，**不存/不返宿主绝对路径**）/
  ``base_commit``（``String(64)``，Git OID）/ ``result_commit``（``String(64)``）/
  ``environment_digest``（``String(64)``，SHA-256，**不含 Secret**）/
  ``artifact_refs``（``JSONType``）/ ``heartbeat_at``（``DateTime(timezone=True)``）/
  ``lease_expires_at``（``DateTime(timezone=True)``）；
- **索引**：
  1. ``ix_task_execution_project_started``：``(project_id, started_at)``（Project 历史查询）；
  2. ``uq_task_execution_checkout_ref``：``checkout_ref`` **部分唯一索引**
     （``WHERE checkout_ref IS NOT NULL``；两方言 ``sqlite_where`` / ``postgresql_where``）——
     非空 ``checkout_ref`` 在 Attempt 内唯一，防两次执行共享同一工作副本
     （§8.1「``checkout_ref`` 唯一性」/ §8.3「非空 ``checkout_ref`` 在 Attempt 内唯一」）；
- 🔴 **关键校正（R-R1R5-08.2）**：``UNIQUE (task_id, attempt)``
  （``uq_task_execution_task_attempt``）**已由 ``0015`` 建**（L151），本迁移**不得重复创建**；
  §8.3「强制 ``UNIQUE (task_id, attempt)``」的执行口径 = **核对该约束存在**（``test_0018.py``
  断言其在 ``0015`` 已建、``0018`` 后仍在），**非**新建。``downgrade`` **不得** drop 该约束
  （属 ``0015``，不在本迁移自有对象范围）；
- 🔴 **A-15 查重中止（R-R1R5-09，硬性）**：``upgrade()`` **首部**对既有 ``task_execution``
  按 ``(task_id, attempt)`` 分组查重（``GROUP BY ... HAVING COUNT(*) > 1``），**命中即
  ``raise`` 中止迁移**（**不自动删除 / 去重 / 重编号**）；干净则继续 upgrade；
- 🔴 **显式方言分支** ``op.get_bind().dialect.name``（**禁 try/except 推断**，F16）：
  ``GUID`` / ``JSONType`` 已吸收方言差异，故两分支**同构**；分支仅用于
  ``SQLite`` 的 ``batch_alter_table``（加列 + 建 FK / 删列 + 删 FK：SQLite 不支持对既有表
  ``ALTER ADD/DROP CONSTRAINT``，Alembic 非 batch 亦抛 ``NotImplementedError``）。

``downgrade``（**只移除本迁移自有索引 / 列**，逆序）：

1. ``DROP INDEX uq_task_execution_checkout_ref`` + ``ix_task_execution_project_started``；
2. ``DROP`` 8 列（逆序）——SQLite 走 ``op.batch_alter_table``（先 ``drop_constraint`` FK 再
   ``drop_column``）；其它方言先 ``drop_constraint`` FK 再逐列 ``drop_column``；
3. 🔴 **不 DROP ``uq_task_execution_task_attempt``**（属 ``0015``）；**不 DROP EXTENSION
   vector**（承接 QA-31）；**不删除**磁盘对象（Project 根仓库 / Attempt Clone / Git 分支 /
   Storage Artifact，设计 §4 残留清单 #7）；**不动**任何既有表 / 列 / 索引。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0018_phase2_remote_workspace"
down_revision: str | None = "0017_phase2_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 目标表（**唯一**被本迁移扩展的业务表）。
_TABLE = "task_execution"

#: 本迁移新增列（**建列顺序**；``downgrade`` 逆序删）。
_ADDED_COLUMNS: tuple[str, ...] = (
    "project_id",
    "checkout_ref",
    "base_commit",
    "result_commit",
    "environment_digest",
    "artifact_refs",
    "heartbeat_at",
    "lease_expires_at",
)

#: ``project_id`` 外键名（``RESTRICT``）。
_FK_PROJECT = "fk_task_execution_project_id"

#: Project 历史查询索引名（``(project_id, started_at)``）。
_IX_PROJECT_STARTED = "ix_task_execution_project_started"

#: ``checkout_ref`` 非空部分唯一索引名。
_UQ_CHECKOUT_REF = "uq_task_execution_checkout_ref"


def _new_columns() -> list[sa.Column]:
    """返回本迁移新增的 8 个**可空**列（``GUID`` / ``JSONType`` 吸收方言差异）。"""
    return [
        sa.Column("project_id", GUID(), nullable=True),
        sa.Column("checkout_ref", sa.String(length=128), nullable=True),
        sa.Column("base_commit", sa.String(length=64), nullable=True),
        sa.Column("result_commit", sa.String(length=64), nullable=True),
        sa.Column("environment_digest", sa.String(length=64), nullable=True),
        sa.Column("artifact_refs", JSONType(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _duplicate_attempt_groups(bind: sa.Connection) -> list[tuple[object, object, object]]:
    """按 ``(task_id, attempt)`` 分组查重，返回 ``(task_id, attempt, count)`` 重复组列表。

    显式接收 ``bind``（供 ``upgrade()`` 与 ``test_0018.py`` 直测）；**纯查询、无副作用**。
    """
    return list(
        bind.execute(
            sa.text(
                f"SELECT task_id, attempt, COUNT(*) AS duplicate_count "
                f"FROM {_TABLE} GROUP BY task_id, attempt HAVING COUNT(*) > 1"
            )
        ).fetchall()
    )


def _guard_no_duplicate_attempts() -> None:
    """A-15 前置校验：按 ``(task_id, attempt)`` 查重，**命中重复组即中止迁移**（R-R1R5-09）。

    🔴 **只查不删 / 不去重 / 不重编号**：命中说明数据层已违反既有
    ``uq_task_execution_task_attempt``（``0015`` 建，正常库中恒为空），须由运维**先备份**后
    **显式处理历史数据**再重跑迁移。
    """
    rows = _duplicate_attempt_groups(op.get_bind())
    if rows:
        preview = ", ".join(
            f"(task_id={row[0]}, attempt={row[1]}, count={row[2]})" for row in rows[:20]
        )
        raise RuntimeError(
            f"0018 迁移中止：{_TABLE} 存在重复 (task_id, attempt) 分组（共 {len(rows)} 组）——"
            f"不自动删除 / 去重 / 重编号；请先备份数据库并显式处理历史数据后重跑迁移。"
            f"重复组：{preview}"
        )


def _add_columns() -> None:
    """加 8 列 + ``project_id`` 外键（显式方言分支；SQLite 走 ``batch_alter_table``）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            for column in _new_columns():
                batch_op.add_column(column)
            batch_op.create_foreign_key(
                _FK_PROJECT, "project", ["project_id"], ["id"], ondelete="RESTRICT"
            )
    else:
        for column in _new_columns():
            op.add_column(_TABLE, column)
        op.create_foreign_key(
            _FK_PROJECT, _TABLE, "project", ["project_id"], ["id"], ondelete="RESTRICT"
        )


def _create_indexes() -> None:
    """建 ``(project_id, started_at)`` 组合索引 + ``checkout_ref`` 部分唯一索引。"""
    op.create_index(_IX_PROJECT_STARTED, _TABLE, ["project_id", "started_at"])
    op.create_index(
        _UQ_CHECKOUT_REF,
        _TABLE,
        ["checkout_ref"],
        unique=True,
        sqlite_where=sa.text("checkout_ref IS NOT NULL"),
        postgresql_where=sa.text("checkout_ref IS NOT NULL"),
    )


def upgrade() -> None:
    """A-15 查重 → 加 8 列 + FK → 建 2 索引（加性；不回填；单 head 顺接 ``0017``）。"""
    # A-15：迁移前查重（首部，硬性）。
    _guard_no_duplicate_attempts()
    _add_columns()
    _create_indexes()


def _drop_indexes() -> None:
    """逆序删除本迁移自有索引（先部分唯一，再组合）。"""
    op.drop_index(_UQ_CHECKOUT_REF, table_name=_TABLE)
    op.drop_index(_IX_PROJECT_STARTED, table_name=_TABLE)


def _drop_columns() -> None:
    """逆序删列 + 先删 ``project_id`` FK（SQLite 走 ``batch_alter_table``）。"""
    dialect = op.get_bind().dialect.name
    reversed_columns = tuple(reversed(_ADDED_COLUMNS))
    if dialect == "sqlite":  # pragma: no cover - 依赖 SQLite 环境
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_FK_PROJECT, type_="foreignkey")
            for name in reversed_columns:
                batch_op.drop_column(name)
    else:
        op.drop_constraint(_FK_PROJECT, _TABLE, type_="foreignkey")
        for name in reversed_columns:
            op.drop_column(_TABLE, name)


def downgrade() -> None:
    """回滚：**只删本迁移自有索引 / 列**（逆序）。

    🔴 **不 DROP ``uq_task_execution_task_attempt``**（属 ``0015``）；**不 ``DROP EXTENSION
    vector``**（承接 QA-31）；**不删除**磁盘对象；**不动**任何既有表 / 列 / 索引。
    """
    _drop_indexes()
    _drop_columns()
