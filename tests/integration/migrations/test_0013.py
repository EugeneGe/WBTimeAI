"""迁移 ``0013_phase2_knowledge`` 集成测试（W5 / T2-27）。

覆盖（W5 开工前架构裁定 §1 / §2 / §3）：

- SQLite：``upgrade head``（五表齐备）→ 零漂移（**过滤 FTS5 影子对象**）→
  ``downgrade 0012``（五表 + FTS 虚表消失、``0012`` 表保留）→ ``upgrade``；
- 唯一键：``knowledge_base`` ``(tenant_id, name)``；``document_chunk`` ``(document_id, ordinal)``
  （断点续跑锚）；``embedding`` ``chunk_id``；``agent_knowledge`` ``(agent_version_id,
  knowledge_base_id)``；
- **外键环**：``embedding.chunk_id → document_chunk.id`` 生效；``document_chunk`` **无**指向
  ``embedding`` 的外键（**无双向外键**）；
- SQLite **FTS5 虚表** ``document_chunk_fts`` 存在；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` /
  ``ASTRA_TEST_REQUIRE_PG`` 门控。
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

#: ``0013`` 引入并随 downgrade 消失的表（**五表**）。
PHASE2_KNOWLEDGE_TABLES: set[str] = {
    "knowledge_base",
    "document",
    "document_chunk",
    "embedding",
    "agent_knowledge",
}

#: SQLite FTS5 虚表（随 downgrade 消失；PG 不存在）。
FTS_TABLE = "document_chunk_fts"

#: downgrade 到 ``0012_phase2_workflow`` 后应保留的表。
KEEP_TABLES: set[str] = {
    "workflow",
    "workflow_version",
    "workflow_node",
    "workflow_edge",
    "workflow_run",
    "workflow_node_run",
    "approval",
    "task",
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


def _fresh_sqlite_url(tmp_dir: Path, filename: str) -> str:
    """构造隔离的 SQLite URL 并重置配置缓存。"""
    from astra_config.loader import reset_settings_cache

    url = f"sqlite:///{(tmp_dir / filename).as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()
    return url


def test_migration_0013_sqlite() -> None:
    """SQLite：upgrade → 五表齐备 + 零漂移 → downgrade 0012 → upgrade。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_knowledge.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_KNOWLEDGE_TABLES.issubset(tables), PHASE2_KNOWLEDGE_TABLES - tables
            assert FTS_TABLE in tables, "SQLite 应创建 FTS5 虚表 document_chunk_fts"
            assert "metadata" in _columns(engine, "document_chunk")
            assert "vector" in _columns(engine, "embedding")
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0012_phase2_workflow")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_KNOWLEDGE_TABLES), (
                remaining & PHASE2_KNOWLEDGE_TABLES
            )
            assert FTS_TABLE not in remaining, "downgrade 应删除 FTS5 虚表"
            assert KEEP_TABLES.issubset(remaining), KEEP_TABLES - remaining
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_KNOWLEDGE_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0013_unique_constraints_sqlite() -> None:
    """唯一键：``document_chunk`` / ``embedding`` / ``agent_knowledge`` / ``knowledge_base``。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_knowledge_uq.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert "uq_knowledge_base_tenant_name" in _unique_names(engine, "knowledge_base")
            assert "uq_document_chunk_document_ordinal" in _unique_names(engine, "document_chunk")
            assert "uq_embedding_chunk_id" in _unique_names(engine, "embedding")
            assert "uq_agent_knowledge_version_kb" in _unique_names(engine, "agent_knowledge")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0013_no_bidirectional_fk_sqlite() -> None:
    """外键**严格单向**（无双向外键）：``embedding → document_chunk`` 生效，
    ``document_chunk`` **无**指向 ``embedding`` 的外键。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_knowledge_fk.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            embedding_fks = sa.inspect(engine).get_foreign_keys("embedding")
            assert any(
                fk.get("referred_table") == "document_chunk" for fk in embedding_fks
            ), embedding_fks

            chunk_fks = sa.inspect(engine).get_foreign_keys("document_chunk")
            referred = {fk.get("referred_table") for fk in chunk_fks}
            assert "embedding" not in referred, chunk_fks
            assert "document" in referred, chunk_fks
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0013_postgres() -> None:
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
                assert PHASE2_KNOWLEDGE_TABLES.issubset(tables), PHASE2_KNOWLEDGE_TABLES - tables
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, "0012_phase2_workflow")
            engine = sa.create_engine(url)
            try:
                remaining = set(sa.inspect(engine).get_table_names())
                assert remaining.isdisjoint(PHASE2_KNOWLEDGE_TABLES)
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, "0012_phase2_workflow")
    finally:
        reset_settings_cache()
