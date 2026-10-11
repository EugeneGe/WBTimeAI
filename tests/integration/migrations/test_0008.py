"""迁移 ``0008_phase2_skill`` 集成测试（W2 / T2-07；验收 ``I-P2-20``）。

覆盖：

- SQLite：``upgrade head →（零漂移比对）→ downgrade 0007 →（表消失 + 零漂移）→ upgrade``；
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

#: ``0008_phase2_skill`` 引入的 4 张表。
PHASE2_SKILL_TABLES: set[str] = {"skill", "skill_version", "skill_resource", "agent_skill"}

#: 0007 及更早的表（downgrade 到 ``0007_phase1_task_execution_mode`` 后应保留）。
PHASE1_KEEP_TABLES: set[str] = {"task", "agent", "agent_version", "agent_tool", "tool"}

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


def test_migration_0008_sqlite() -> None:
    """SQLite：upgrade head → 零漂移 → downgrade 0007 → 四表消失 → 再 upgrade 零漂移。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase2_skill.db').as_posix()}"
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
            assert PHASE2_SKILL_TABLES.issubset(tables), PHASE2_SKILL_TABLES - tables
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        # -- downgrade 到 0007 → 四表消失，Phase 1 表保留 -------------------
        command.downgrade(config, "0007_phase1_task_execution_mode")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_SKILL_TABLES), remaining & PHASE2_SKILL_TABLES
            assert PHASE1_KEEP_TABLES.issubset(remaining)
        finally:
            engine.dispose()

        # -- 再 upgrade → 零漂移（往返干净） --------------------------------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_SKILL_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
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


def test_migration_0008_postgres() -> None:  # pragma: no cover - CI 门控
    """PostgreSQL：``0008`` 双向 + 零漂移（CI ``postgres-smoke`` job 实跑）。"""
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
            assert PHASE2_SKILL_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0007_phase1_task_execution_mode")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_SKILL_TABLES)
        finally:
            engine.dispose()

        command.downgrade(config, "base")
    finally:
        reset_settings_cache()
