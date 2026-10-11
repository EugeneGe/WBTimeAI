"""迁移 ``0010_phase2_permission_plugin`` 集成测试（W3 / T2-13；验收 ``I-P2-20``）。

覆盖：

- SQLite：``upgrade head``（三表 + ``tool_permission`` 保留）→ 零漂移 → ``downgrade 0009``
  （三表消失，``tool_permission`` **仍在**）→ ``upgrade``；
- SQLite：``tool_permission`` → ``resource_permission`` 回填（升级前埋入 ``tool_permission`` 行）；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` /
  ``ASTRA_TEST_REQUIRE_PG`` 门控。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``0010`` 引入并随 downgrade 消失的 3 张表。
PHASE2_PERMISSION_TABLES: set[str] = {"resource_permission", "plugin", "approval"}

#: downgrade 到 ``0009_phase2_mcp`` 后应保留（不 drop）的表。
KEEP_TABLES: set[str] = {"tool_permission", "mcp_server", "mcp_tool", "mcp_permission"}

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


def _seed_tool_permission(engine: Engine) -> None:
    """在（已 upgrade 到 ``0009`` 的）库中插入两行 ``tool_permission``。"""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO tool_permission "
                "(id, tenant_id, agent_id, agent_version_id, tool_id, action, effect, scope) "
                "VALUES "
                "(:id1, :tenant, :agent, NULL, :tool, 'EXECUTE', 'ALLOW', NULL), "
                "(:id2, :tenant, :agent, NULL, :tool2, 'EXECUTE', 'DENY', NULL)"
            ),
            {
                "id1": "tp-allow-0001",
                "id2": "tp-deny-0001",
                "tenant": "tenant-t13",
                "agent": "agent-t13",
                "tool": "tool-t13",
                "tool2": "tool-t13b",
            },
        )


def _count(engine: Engine, table: str) -> int:
    """统计某表行数。"""
    with engine.connect() as connection:
        return int(connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def test_migration_0010_sqlite() -> None:
    """SQLite：upgrade → 三表 + ``tool_permission`` 保留 → 零漂移 → downgrade → upgrade。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase2_permission.db').as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    from alembic import command

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_PERMISSION_TABLES.issubset(tables), PHASE2_PERMISSION_TABLES - tables
            assert "tool_permission" in tables, "tool_permission 应保留（不 drop）"
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0009_phase2_mcp")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_PERMISSION_TABLES), (
                remaining & PHASE2_PERMISSION_TABLES
            )
            assert KEEP_TABLES.issubset(remaining)
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_PERMISSION_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0010_backfill_sqlite() -> None:
    """``tool_permission``（agent 绑定）→ ``resource_permission`` 回填（幂等）。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase2_backfill.db').as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    from alembic import command

    config = _alembic_config()
    try:
        command.upgrade(config, "0009_phase2_mcp")
        engine = sa.create_engine(url)
        try:
            _seed_tool_permission(engine)
            assert _count(engine, "tool_permission") == 2
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert _count(engine, "resource_permission") == 2
            rows = (
                engine.connect()
                .execute(
                    sa.text(
                        "SELECT subject_type, resource_type, action, effect "
                        "FROM resource_permission ORDER BY effect"
                    )
                )
                .all()
            )
            assert {row.subject_type for row in rows} == {"agent"}
            assert {row.resource_type for row in rows} == {"TOOL"}
            assert {row.action for row in rows} == {"EXECUTE"}
            assert {row.effect for row in rows} == {"ALLOW", "DENY"}
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def _resolve_pg_url() -> str:
    if not _PG_URL:
        if _REQUIRE_PG:
            pytest.fail("ASTRA_TEST_REQUIRE_PG=1 但未设置 ASTRA_TEST_PG_URL —— PG 冒烟不得跳过。")
        pytest.skip("未设置 ASTRA_TEST_PG_URL，跳过 PostgreSQL 迁移冒烟。")
    return _PG_URL


def _with_connect_timeout(url: str) -> str:
    if not url.startswith(("postgresql", "postgres")):
        return url
    if "connect_timeout" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}connect_timeout={_CONNECT_TIMEOUT_SECONDS}"


def test_migration_0010_postgres() -> None:  # pragma: no cover - CI 门控
    """PostgreSQL：``0010`` 双向 + 零漂移（CI ``postgres-smoke`` job 实跑）。"""
    url = _with_connect_timeout(_resolve_pg_url())

    from astra_config.loader import reset_settings_cache

    os.environ["ASTRA_MODE"] = "server"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    try:
        probe = sa.create_engine(url)
        with probe.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        probe.dispose()
    except SQLAlchemyError as exc:
        if _REQUIRE_PG:
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
        pytest.skip(f"无法连接 PostgreSQL：{exc}")

    from alembic import command

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_PERMISSION_TABLES.issubset(tables)
            assert "tool_permission" in tables
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0009_phase2_mcp")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_PERMISSION_TABLES)
            assert "tool_permission" in remaining
        finally:
            engine.dispose()

        command.downgrade(config, "base")
    finally:
        reset_settings_cache()
