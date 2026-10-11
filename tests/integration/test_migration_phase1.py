"""Phase 1 迁移集成测试（T1-06 / §3-#15 / §3-#27）。

覆盖：

- SQLite：``upgrade head →（零漂移比对）→ downgrade 0002 →（零漂移）`` + 表清单快照；
- PostgreSQL：同链路，受 ``ASTRA_TEST_PG_URL`` / ``ASTRA_TEST_REQUIRE_PG`` 门控
  （未设则 skip；``REQUIRE_PG=1`` 时 fail-fast，防假绿）。

⚠️ 设计 §2.15.1 标题写「共 14 张」，但逐列清单实际枚举 **15 张**（13 张 + ``sandbox_session``
   + ``audit_log``）。本测试以**逐列清单为准**断言 15 张表（见施工记录「遗留/偏差」）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Phase 1 新增表（以 §2.15.1 逐列清单为准，共 15 张）。
PHASE1_TABLES: set[str] = {
    # Agent 组
    "agent",
    "agent_version",
    "agent_tool",
    # Model 组
    "model_provider",
    "model",
    # Tool 组
    "tool",
    "tool_version",
    "tool_permission",
    # Conversation 组
    "conversation",
    "message",
    "agent_run",
    "tool_call",
    "agent_event",
    # Sandbox 组
    "sandbox_session",
    # 审计组（R-14 提前）
    "audit_log",
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
    """断言 ORM 元数据与 DB schema 零漂移（等价 ``alembic check``）。

    SQLite 下迁移 ``0013`` 建的 FTS5 虚表 / 影子对象为 **DB-only**，
    不在 ORM 元数据中，故须过滤（口径与 ``tests/integration/migrations`` 一致）。
    """
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from astra_database.base import Base

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    from tests.integration.migrations._fts_filter import without_fts_artifacts

    residual = without_fts_artifacts(diff)
    assert not residual, f"检测到 ORM/迁移漂移：{residual}"


def test_migration_phase1_sqlite() -> None:
    """SQLite：upgrade head → 零漂移 → downgrade 0002 → 表消失 → 零漂移。"""
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase1.db').as_posix()}"

    from astra_config.loader import reset_settings_cache

    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    from alembic import command

    config = _alembic_config()
    try:
        # -- upgrade → 表清单 + 零漂移 --------------------------------------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE1_TABLES.issubset(tables), PHASE1_TABLES - tables
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        # -- downgrade 到 0002 → Phase 1 表消失 ----------------------------
        command.downgrade(config, "0002_feature_flag")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE1_TABLES), remaining & PHASE1_TABLES
            # 0002 的 feature_flag 仍在（仅回退 Phase 1 批次）。
            assert "feature_flag" in remaining
        finally:
            engine.dispose()

        # -- 再升级到 head → 零漂移（往返干净） ----------------------------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE1_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
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


def test_migration_phase1_postgres() -> None:  # pragma: no cover - CI 门控
    """PostgreSQL：同链路冒烟（CI ``postgres-smoke`` job 实跑）。"""
    url = _with_connect_timeout(_resolve_pg_url())

    from astra_config.loader import reset_settings_cache

    os.environ["ASTRA_MODE"] = "server"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    # 连通性探测（按门控语义 skip / fail）。
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
            assert PHASE1_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0002_feature_flag")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE1_TABLES)
        finally:
            engine.dispose()

        # 收尾：回到 base，避免污染后续用例。
        command.downgrade(config, "base")
    finally:
        reset_settings_cache()
