"""迁移 ``0009_phase2_mcp`` 集成测试（W2 / T2-10；验收 ``I-P2-20``）。

覆盖：

- SQLite：``upgrade head →（零漂移比对）→ downgrade 0008 →（三表消失 + ``tool.tool_ref``
  列消失 + ``source='mcp'`` 行被清理）→ upgrade``；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` /
  ``ASTRA_TEST_REQUIRE_PG`` 门控（未设则 skip；``REQUIRE_PG=1`` 时 fail-fast，防假绿）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``0009_phase2_mcp`` 引入的 3 张表。
PHASE2_MCP_TABLES: set[str] = {"mcp_server", "mcp_tool", "mcp_permission"}

#: ``0008`` 及更早的表（downgrade 到 ``0008_phase2_skill`` 后应保留）。
PHASE2_SKILL_KEEP_TABLES: set[str] = {"skill", "skill_version", "skill_resource", "agent_skill"}

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


def _tool_columns(engine: Engine) -> set[str]:
    """返回 ``tool`` 表的列名集合。"""
    return {column["name"] for column in sa.inspect(engine).get_columns("tool")}


def _seed_tool_rows(engine: Engine) -> None:
    """插入一行 ``source='mcp'`` 与一行 ``source='builtin'`` 的 ``tool`` 记录。"""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO tool (id, tenant_id, name, display_name, category, source, "
                "requires_sandbox, status, tool_ref) VALUES "
                "(:id, NULL, :name, :display, :category, :source, 0, 'ACTIVE', :tool_ref)"
            ),
            [
                {
                    "id": "tool-mcp-0001",
                    "name": "mcp:github.search",
                    "display": "GitHub Search",
                    "category": "mcp",
                    "source": "mcp",
                    "tool_ref": '{"kind": "mcp"}',
                },
                {
                    "id": "tool-builtin-0001",
                    "name": "filesystem.read",
                    "display": "Filesystem Read",
                    "category": "filesystem",
                    "source": "builtin",
                    "tool_ref": None,
                },
            ],
        )


def _count_tool_rows(engine: Engine, source: str) -> int:
    """统计某 ``source`` 的 ``tool`` 行数。"""
    with engine.connect() as connection:
        return int(
            connection.execute(
                sa.text("SELECT COUNT(*) FROM tool WHERE source = :source"), {"source": source}
            ).scalar_one()
        )


def test_migration_0009_sqlite() -> None:
    """SQLite：upgrade → 三表 + ``tool_ref`` → 零漂移 → downgrade 0008（清 MCP 行）→ upgrade。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase2_mcp.db').as_posix()}"
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
            assert PHASE2_MCP_TABLES.issubset(tables), PHASE2_MCP_TABLES - tables
            assert "tool_ref" in _tool_columns(engine)
            _assert_no_drift(engine)
            _seed_tool_rows(engine)
            assert _count_tool_rows(engine, "mcp") == 1
            assert _count_tool_rows(engine, "builtin") == 1
        finally:
            engine.dispose()

        # -- downgrade 到 0008 → 三表消失 + tool_ref 列消失 + MCP 行被清理 ------
        command.downgrade(config, "0008_phase2_skill")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_MCP_TABLES), remaining & PHASE2_MCP_TABLES
            assert PHASE2_SKILL_KEEP_TABLES.issubset(remaining)
            assert "tool_ref" not in _tool_columns(engine)
            assert _count_tool_rows(engine, "mcp") == 0
            assert _count_tool_rows(engine, "builtin") == 1
        finally:
            engine.dispose()

        # -- 再 upgrade → 零漂移（往返干净） --------------------------------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_MCP_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            assert "tool_ref" in _tool_columns(engine)
            _assert_no_drift(engine)
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


def test_migration_0009_postgres() -> None:  # pragma: no cover - CI 门控
    """PostgreSQL：``0009`` 双向 + 零漂移（CI ``postgres-smoke`` job 实跑）。"""
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
            assert PHASE2_MCP_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            assert "tool_ref" in _tool_columns(engine)
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0008_phase2_skill")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_MCP_TABLES)
            assert "tool_ref" not in _tool_columns(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "base")
    finally:
        reset_settings_cache()
