"""迁移 ``0014_phase2_memory`` 集成测试（W6 / T2-32）。

覆盖（W6 开工前架构裁定 §1 / §5 / B1 / B9 / B10）：

- SQLite：``upgrade head``（两表齐备）→ 零漂移（**过滤 FTS5 影子对象**）→
  ``downgrade 0013``（两表消失、``0013`` 表保留）→ ``upgrade``；
- ``memory``：``vector`` 可空、``expires_at`` 可空、``(tenant_id, scope_type, scope_id, kind)``
  + ``expires_at`` 索引存在；
- ``memory_relation``：唯一键 ``(from_memory_id, to_memory_id, relation)``；
- 外键**单向**（无跨表环）：``memory → tenant / workspace / agent_run``；
  ``memory_relation → memory``（仅自表）；
- 🔴 **不 ``DROP EXTENSION vector``**（静态源码断言，本机无 PG 亦可复现，QA-31）；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` 门控。
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

#: ``0014`` 引入并随 downgrade 消失的表（**两表**）。
PHASE2_MEMORY_TABLES: set[str] = {"memory", "memory_relation"}

#: downgrade 到 ``0013_phase2_knowledge`` 后应保留的表。
KEEP_TABLES: set[str] = {
    "knowledge_base",
    "document",
    "document_chunk",
    "embedding",
    "agent_knowledge",
    "workflow",
    "workflow_run",
}

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
    """返回某表唯一约束名集合（SQLite / PG 通用口径）。"""
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


def test_migration_0014_sqlite() -> None:
    """SQLite：upgrade → 两表齐备 + 零漂移 → downgrade 0013 → upgrade。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_memory.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_MEMORY_TABLES.issubset(tables), PHASE2_MEMORY_TABLES - tables
            assert "vector" in _columns(engine, "memory")
            assert "expires_at" in _columns(engine, "memory")
            assert "embedding_id" not in _columns(engine, "memory"), "B1：不得含 embedding_id"
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0013_phase2_knowledge")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_MEMORY_TABLES), remaining & PHASE2_MEMORY_TABLES
            assert KEEP_TABLES.issubset(remaining), KEEP_TABLES - remaining
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_MEMORY_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0014_nullable_vector_and_expires_sqlite() -> None:
    """``memory.vector`` / ``memory.expires_at`` **可空**（B1 / §5.1）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_memory_null.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            nullable = _nullable_column_names(engine, "memory")
            assert "vector" in nullable, "memory.vector 应可空（B1）"
            assert "expires_at" in nullable, "memory.expires_at 应可空"
            # 隔离强制：tenant_id 非空。
            assert "tenant_id" not in nullable, "memory.tenant_id 应非空（I-2）"
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0014_unique_and_indexes_sqlite() -> None:
    """唯一键 + 召回 / TTL 索引（B10）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_memory_uq.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            unique = _unique_names(engine, "memory_relation")
            assert "uq_memory_relation_from_to_relation" in unique, unique
            indexes = _index_names(engine, "memory")
            assert "ix_memory_tenant_scope_kind" in indexes, indexes
            assert "ix_memory_expires_at" in indexes, indexes
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0014_fk_topology_sqlite() -> None:
    """外键**单向**（无跨表环）：``memory → tenant / workspace / agent_run``；
    ``memory_relation → memory``（仅自表）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_memory_fk.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            memory_refs = {
                fk.get("referred_table") for fk in sa.inspect(engine).get_foreign_keys("memory")
            }
            assert {"tenant", "workspace", "agent_run"}.issubset(memory_refs), memory_refs
            relation_refs = {
                fk.get("referred_table")
                for fk in sa.inspect(engine).get_foreign_keys("memory_relation")
            }
            assert relation_refs == {"memory"}, relation_refs
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0014_no_drop_extension_vector() -> None:
    """🔴 ``0014`` 的**可执行 SQL** 中**不得** ``DROP EXTENSION vector``（QA-31 / B9）。

    经 ``ast`` 静态解析，仅取 ``op.execute(...)`` / ``...exec_driver_sql(...)`` 的**字符串实参**
    （docstring 中的说明文字不计入）——断言其中无 ``DROP EXTENSION``。
    """
    import ast

    source = (REPO_ROOT / "migrations" / "versions" / "0014_phase2_memory.py").read_text(
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
    assert sql_texts, "未能从 0014 迁移中解析出任何可执行 SQL（断言无效）"
    dropped = [text for text in sql_texts if "drop extension" in text.lower()]
    assert not dropped, f"0014 迁移可执行 SQL 含 DROP EXTENSION：{dropped}"


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0014_postgres() -> None:
    """PostgreSQL（权威方言）：upgrade → 零漂移 → downgrade → upgrade。"""
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
            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                tables = set(sa.inspect(engine).get_table_names())
                assert PHASE2_MEMORY_TABLES.issubset(tables), PHASE2_MEMORY_TABLES - tables
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, "0013_phase2_knowledge")
            engine = sa.create_engine(url)
            try:
                remaining = set(sa.inspect(engine).get_table_names())
                assert remaining.isdisjoint(PHASE2_MEMORY_TABLES)
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, "0013_phase2_knowledge")
    finally:
        reset_settings_cache()
