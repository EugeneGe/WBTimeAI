"""迁移 ``0012_phase2_workflow`` 集成测试（W4 / T2-20）。

覆盖（W4 开工前架构裁定 §2 / §5）：

- SQLite：``upgrade head``（六表齐备）→ 零漂移 → ``downgrade 0011``（六表消失、
  **``approval`` 保留**）→ ``upgrade``；
- ``workflow_node`` 唯一键 ``(workflow_version_id, node_key)``（**验收 ② 硬性**）；
- ``workflow_version`` 唯一键 ``(workflow_id, version)``；``workflow_edge`` 防重复连边；
  ``workflow_node_run`` 唯一键 ``(workflow_run_id, node_key, attempt)``；
- 循环外键 ``workflow.current_version_id → workflow_version.id`` 生效；
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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``0012`` 引入并随 downgrade 消失的表（**六表**）。
PHASE2_WORKFLOW_TABLES: set[str] = {
    "workflow",
    "workflow_version",
    "workflow_node",
    "workflow_edge",
    "workflow_run",
    "workflow_node_run",
}

#: downgrade 到 ``0011_phase2_credential_multi`` 后应保留的表
# （含 ``approval`` —— **严禁随 0012 删除**，W4 裁定 §2.1 / WR-1）。
KEEP_TABLES: set[str] = {
    "approval",
    "resource_permission",
    "plugin",
    "skill",
    "model_provider_credential",
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
    """断言 ORM 元数据与 DB schema 零漂移（等价 ``alembic check``）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from astra_database.base import Base

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    from ._fts_filter import without_fts_artifacts

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


def test_migration_0012_sqlite() -> None:
    """SQLite：upgrade → 六表齐备 + 零漂移 → downgrade 0011 → upgrade。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_workflow.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_WORKFLOW_TABLES.issubset(tables), PHASE2_WORKFLOW_TABLES - tables
            assert "definition" in _columns(engine, "workflow_version")
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0011_phase2_credential_multi")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_WORKFLOW_TABLES), remaining & PHASE2_WORKFLOW_TABLES
            # approval 表属 0010，严禁随 0012 downgrade 删除。
            assert KEEP_TABLES.issubset(remaining), KEEP_TABLES - remaining
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_WORKFLOW_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0012_unique_constraints_sqlite() -> None:
    """验收 ② 硬性：``workflow_node`` 唯一键 ``(workflow_version_id, node_key)`` 等。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_workflow_uq.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert "uq_workflow_node_version_node_key" in _unique_names(engine, "workflow_node")
            assert "uq_workflow_version_workflow_version" in _unique_names(
                engine, "workflow_version"
            )
            assert "uq_workflow_edge_version_from_to" in _unique_names(engine, "workflow_edge")
            assert "uq_workflow_node_run_run_key_attempt" in _unique_names(
                engine, "workflow_node_run"
            )
            assert "uq_workflow_tenant_name" in _unique_names(engine, "workflow")

            # 实测：同版本下重复 node_key 被唯一键拒绝。
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO workflow_version "
                        "(id, workflow_id, version, definition, status, created_by, created_at) "
                        "VALUES ('wv-1', 'wf-1', 'v1', '{}', 'PUBLISHED', 'u-1', "
                        "CURRENT_TIMESTAMP)"
                    )
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO workflow_node "
                        "(id, workflow_version_id, node_key, type, config, position, created_at) "
                        "VALUES ('wn-1', 'wv-1', 'n1', 'AGENT', '{}', '{}', CURRENT_TIMESTAMP)"
                    )
                )
            with engine.begin() as connection:
                with pytest.raises(IntegrityError):
                    connection.execute(
                        sa.text(
                            "INSERT INTO workflow_node "
                            "(id, workflow_version_id, node_key, type, config, position, "
                            "created_at) "
                            "VALUES ('wn-2', 'wv-1', 'n1', 'TOOL', '{}', '{}', "
                            "CURRENT_TIMESTAMP)"
                        )
                    )
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0012_circular_fk_sqlite() -> None:
    """循环外键 ``workflow.current_version_id → workflow_version.id`` 生效。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_workflow_fk.db")

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            foreign_keys = sa.inspect(engine).get_foreign_keys("workflow")
            names = {
                str(fk.get("name"))
                for fk in foreign_keys
                if fk.get("referred_table") == "workflow_version"
            }
            assert "fk_workflow_current_version_id" in names, names
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0012_postgres() -> None:
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
                assert PHASE2_WORKFLOW_TABLES.issubset(tables), PHASE2_WORKFLOW_TABLES - tables
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, "0011_phase2_credential_multi")
            engine = sa.create_engine(url)
            try:
                remaining = set(sa.inspect(engine).get_table_names())
                assert remaining.isdisjoint(PHASE2_WORKFLOW_TABLES)
                assert KEEP_TABLES.issubset(remaining), KEEP_TABLES - remaining
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, "0011_phase2_credential_multi")
    finally:
        reset_settings_cache()
