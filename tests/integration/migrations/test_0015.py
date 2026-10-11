"""迁移 ``0015_phase2_workspace_task`` 集成测试（W7 / T2-37）。

覆盖（W7 开工前架构裁定 §3 / §4.1）：

- SQLite：``upgrade 0015_phase2_workspace_task``（4 表 + ``task.idempotency_key`` 齐备）→
  零漂移（**过滤 FTS5 影子对象**）→ ``downgrade 0014_phase2_memory``（4 表消失、
  ``task.idempotency_key`` 消失、既有表保留）→ ``upgrade``；
- ``project`` / ``workspace_environment`` / ``schedule`` 的 ``organization_id`` **可空**
  （R-open#2 一次到位）；
- 唯一键（冻结契约）：``uq_workspace_environment_ws_name`` /
  ``uq_task_execution_task_attempt`` / ``uq_schedule_target_name`` / ``uq_task_idempotency_key``；
- 组织索引（一次到位）：``ix_project_organization_id`` /
  ``ix_workspace_environment_organization_id`` / ``ix_schedule_organization_id``；
- 外键**单向**（无跨表环）；
- 🔴 **不 ``DROP EXTENSION vector``**（静态源码断言，本机无 PG 亦可复现）；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` 门控。

🔴 使用**显式 revision 目标**（而非 ``head``）做**对象存在性**断言——使本测试独立于是否已落地
``0016``；而**零漂移**断言统一在 **head** 口径执行（``compare_metadata`` 比对的是 head 元数据，
仅在 head 有意义）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``0015`` 引入并随 downgrade 消失的表（**4 表**）。
PHASE2_W7_TABLES: set[str] = {"project", "workspace_environment", "task_execution", "schedule"}

#: downgrade 到 ``0014_phase2_memory`` 后应保留的表。
KEEP_TABLES: set[str] = {
    "memory",
    "memory_relation",
    "knowledge_base",
    "document",
    "document_chunk",
    "embedding",
    "agent_knowledge",
    "workspace",
    "task",
}

_REV_0015 = "0015_phase2_workspace_task"
_REV_0014 = "0014_phase2_memory"

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10


def _alembic_config():
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def _assert_no_drift(engine: Engine) -> None:
    """断言 ORM 元数据与 DB schema 零漂移（**过滤 FTS5 虚表 / 影子对象**）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from astra_database.base import Base

    from ._fts_filter import without_fts_artifacts

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    residual = without_fts_artifacts(diff)
    assert not residual, f"检测到 ORM/迁移漂移：{residual}"


def _columns(engine: Engine, table: str) -> set[str]:
    """返回某表列名集合。"""
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def _nullable_column_names(engine: Engine, table: str) -> set[str]:
    """返回某表**可空**列名集合。"""
    inspector = sa.inspect(engine)
    return {column["name"] for column in inspector.get_columns(table) if column.get("nullable")}


def _unique_names(engine: Engine, table: str) -> set[str]:
    """返回某表唯一约束 / 唯一索引名集合（SQLite / PG 通用口径）。"""
    inspector = sa.inspect(engine)
    names: set[str] = set()
    for constraint in inspector.get_unique_constraints(table):
        if constraint.get("name"):
            names.add(str(constraint["name"]))
    for index in inspector.get_indexes(table):
        if bool(index.get("unique")) and index.get("name"):
            names.add(str(index["name"]))
    return names


def _index_names(engine: Engine, table: str) -> set[str]:
    """返回某表索引名集合。"""
    inspector = sa.inspect(engine)
    return {str(index["name"]) for index in inspector.get_indexes(table) if index.get("name")}


def _fresh_sqlite_url(tmp_dir: Path, filename: str) -> str:
    """构造隔离的 SQLite URL 并重置配置缓存。"""
    from astra_config.loader import reset_settings_cache

    url = f"sqlite:///{(tmp_dir / filename).as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()
    return url


def test_migration_0015_sqlite() -> None:
    """SQLite：upgrade 0015 → 4 表 + ``task.idempotency_key`` 齐备 →
    downgrade 0014 → 4 表与列消失 → upgrade **head**（零漂移口径）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_w7.db")

    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_W7_TABLES.issubset(tables), PHASE2_W7_TABLES - tables
            assert "idempotency_key" in _columns(engine, "task"), "task.idempotency_key 缺失"
            # 🔴 零漂移断言口径只在 **head** 有效（``compare_metadata`` 比对的是 head 元数据）；
            #    中间版本（0015）比 head 元数据会出现后续迁移（如 0016）新增列的差异 →
            #    漂移断言统一下移至下方 head 阶段（仅新增/收紧口径，不放宽既有断言）。
        finally:
            engine.dispose()

        command.downgrade(config, _REV_0014)
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_W7_TABLES), remaining & PHASE2_W7_TABLES
            assert KEEP_TABLES.issubset(remaining), KEEP_TABLES - remaining
            assert "idempotency_key" not in _columns(engine, "task"), "task.idempotency_key 未回滚"
        finally:
            engine.dispose()

        # 升到 **head**（0016 起 head ≠ 0015）再断言零漂移 + 0015 对象仍在。
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_W7_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            assert "idempotency_key" in _columns(engine, "task"), "task.idempotency_key 缺失"
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0015_nullable_org_sqlite() -> None:
    """``project`` / ``workspace_environment`` / ``schedule`` 的 ``organization_id``
    **可空**（R-open#2 一次到位）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_w7_null.db")

    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            for table in ("project", "workspace_environment", "schedule"):
                nullable = _nullable_column_names(engine, table)
                assert "organization_id" in nullable, f"{table}.organization_id 应可空"
            # 硬归属：tenant_id 非空；project.workspace_id 非空。
            assert "tenant_id" not in _nullable_column_names(engine, "project")
            assert "workspace_id" not in _nullable_column_names(engine, "project")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0015_unique_and_indexes_sqlite() -> None:
    """唯一键 + 组织 / 归属 / 轮询索引（冻结契约）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_w7_uq.db")

    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            assert "uq_workspace_environment_ws_name" in _unique_names(
                engine, "workspace_environment"
            )
            assert "uq_task_execution_task_attempt" in _unique_names(engine, "task_execution")
            assert "uq_schedule_target_name" in _unique_names(engine, "schedule")
            assert "uq_task_idempotency_key" in _unique_names(engine, "task")

            assert "ix_project_organization_id" in _index_names(engine, "project")
            assert "ix_workspace_environment_organization_id" in _index_names(
                engine, "workspace_environment"
            )
            assert "ix_schedule_organization_id" in _index_names(engine, "schedule")
            assert "ix_schedule_next_run_at" in _index_names(engine, "schedule")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0015_fk_topology_sqlite() -> None:
    """外键**单向**（无跨表环）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_w7_fk.db")

    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            project_refs = {
                fk.get("referred_table") for fk in sa.inspect(engine).get_foreign_keys("project")
            }
            assert {"tenant", "organization", "workspace", "user"}.issubset(
                project_refs
            ), project_refs
            env_refs = {
                fk.get("referred_table")
                for fk in sa.inspect(engine).get_foreign_keys("workspace_environment")
            }
            assert {"tenant", "organization", "workspace"}.issubset(env_refs), env_refs
            exec_refs = {
                fk.get("referred_table")
                for fk in sa.inspect(engine).get_foreign_keys("task_execution")
            }
            assert exec_refs == {"task"}, exec_refs
            schedule_refs = {
                fk.get("referred_table") for fk in sa.inspect(engine).get_foreign_keys("schedule")
            }
            assert {"tenant", "organization", "workspace"}.issubset(schedule_refs), schedule_refs
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0015_no_drop_extension_vector() -> None:
    """🔴 ``0015`` 的**可执行 SQL** 中**不得** ``DROP EXTENSION vector``（承接 QA-31）。"""
    import ast

    source = (REPO_ROOT / "migrations" / "versions" / "0015_phase2_workspace_task.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    sql_texts: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"execute", "exec_driver_sql"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                sql_texts.append(arg.value)
    dropped = [text for text in sql_texts if "drop extension" in text.lower()]
    assert not dropped, f"0015 迁移可执行 SQL 含 DROP EXTENSION：{dropped}"


def test_migration_0015_downgrade_no_drop_existing_tables_static() -> None:
    """🔴 ``0015`` downgrade **只 drop 本批自有对象**（静态断言：不 drop 既有表）。"""
    import ast

    source = (REPO_ROOT / "migrations" / "versions" / "0015_phase2_workspace_task.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    dropped_tables: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "drop_table":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                dropped_tables.append(arg.value)
    assert set(dropped_tables) == PHASE2_W7_TABLES, dropped_tables


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0015_postgres() -> None:
    """PostgreSQL（权威方言）：upgrade 0015（对象存在性）→ downgrade 0014 → upgrade **head**
    （零漂移口径，与 SQLite 分支同构）。"""
    assert _PG_URL is not None
    url = _PG_URL
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)

    from alembic import command
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()
    config = _alembic_config()
    try:
        engine = sa.create_engine(url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS})
        try:
            with engine.connect():
                pass
        except SQLAlchemyError:  # pragma: no cover - 环境不可达
            pytest.skip(f"PostgreSQL 不可达：{url}")
        finally:
            engine.dispose()

        try:
            command.upgrade(config, _REV_0015)
            engine = sa.create_engine(url)
            try:
                tables = set(sa.inspect(engine).get_table_names())
                assert PHASE2_W7_TABLES.issubset(tables), PHASE2_W7_TABLES - tables
            finally:
                engine.dispose()

            command.downgrade(config, _REV_0014)
            engine = sa.create_engine(url)
            try:
                remaining = set(sa.inspect(engine).get_table_names())
                assert remaining.isdisjoint(PHASE2_W7_TABLES)
            finally:
                engine.dispose()

            # 升到 **head**（0016 起 head ≠ 0015）再断言零漂移 + 0015 对象仍在——
            # 与 SQLite 分支同口径（``compare_metadata`` 比对 head 元数据，中间版本无效）。
            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                assert PHASE2_W7_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, _REV_0014)
    finally:
        reset_settings_cache()
