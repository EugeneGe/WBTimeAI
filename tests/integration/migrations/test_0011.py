"""迁移 ``0011_phase2_credential_multi`` 集成测试（W3 / T2-15）。

覆盖：

- SQLite：``upgrade head``（``model_provider_credential`` + ``credential`` 四补列）→ 零漂移 →
  ``downgrade 0010``（关联表 + 四补列消失）→ ``upgrade``；
- SQLite：既有 ``model_provider.credential_id`` → ``model_provider_credential`` **回填**
  （升级前埋入 provider 行）；
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

#: ``0011`` 引入并随 downgrade 消失的表。
PHASE2_CREDENTIAL_TABLES: set[str] = {"model_provider_credential"}

#: ``0011`` 为 ``credential`` 补的 4 列。
CREDENTIAL_NEW_COLUMNS: set[str] = {"name", "status", "last_used_at", "metadata"}

#: downgrade 到 ``0010_phase2_permission_plugin`` 后应保留的表。
KEEP_TABLES: set[str] = {
    "credential",
    "model_provider",
    "resource_permission",
    "plugin",
    "approval",
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


def _count(engine: Engine, table: str) -> int:
    """统计某表行数。"""
    with engine.connect() as connection:
        return int(connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _seed_model_provider(engine: Engine) -> None:
    """在（已 upgrade 到 ``0010`` 的）库中埋入一条凭证 + 一条引用它的 provider。"""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO credential "
                "(id, tenant_id, workspace_id, provider, key_type, encrypted_value, "
                "created_at, updated_at) "
                "VALUES (:cid, :tenant, NULL, 'openai', 'api_key', 'enc:seed-blob', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"cid": "cred-bf-0001", "tenant": "tenant-t15"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_provider "
                "(id, tenant_id, workspace_id, name, type, endpoint, credential_id, "
                "status, config) "
                "VALUES (:pid, :tenant, NULL, 'openai', 'openai', NULL, :cid, 'ACTIVE', NULL)"
            ),
            {"pid": "prov-bf-0001", "tenant": "tenant-t15", "cid": "cred-bf-0001"},
        )


def _fresh_sqlite_url(tmp_dir: Path, filename: str) -> str:
    """构造隔离的 SQLite URL 并重置配置缓存。"""
    from astra_config.loader import reset_settings_cache

    url = f"sqlite:///{(tmp_dir / filename).as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()
    return url


def test_migration_0011_sqlite() -> None:
    """SQLite：upgrade → 关联表 + 四补列 → 零漂移 → downgrade → upgrade。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_credential.db")

    from alembic import command

    config = _alembic_config()
    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert PHASE2_CREDENTIAL_TABLES.issubset(tables), PHASE2_CREDENTIAL_TABLES - tables
            assert CREDENTIAL_NEW_COLUMNS.issubset(_columns(engine, "credential"))
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0010_phase2_permission_plugin")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_CREDENTIAL_TABLES)
            assert KEEP_TABLES.issubset(remaining)
            assert _columns(engine, "credential").isdisjoint(CREDENTIAL_NEW_COLUMNS)
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert PHASE2_CREDENTIAL_TABLES.issubset(set(sa.inspect(engine).get_table_names()))
            assert CREDENTIAL_NEW_COLUMNS.issubset(_columns(engine, "credential"))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0011_backfill_sqlite() -> None:
    """既有 ``model_provider.credential_id`` → ``model_provider_credential`` 回填（幂等）。"""
    import tempfile

    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_credential_backfill.db")

    from alembic import command

    config = _alembic_config()
    try:
        command.upgrade(config, "0010_phase2_permission_plugin")
        engine = sa.create_engine(url)
        try:
            _seed_model_provider(engine)
            assert _count(engine, "credential") == 1
            assert _count(engine, "model_provider") == 1
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert _count(engine, "model_provider_credential") == 1
            row = (
                engine.connect()
                .execute(
                    sa.text(
                        "SELECT provider_id, credential_id, weight, status "
                        "FROM model_provider_credential"
                    )
                )
                .one()
            )
            assert row.provider_id == "prov-bf-0001"
            assert row.credential_id == "cred-bf-0001"
            assert row.weight == 1
            assert row.status == "ACTIVE"
            # 旧列保留（不置 NULL）。
            legacy = (
                engine.connect()
                .execute(
                    sa.text("SELECT credential_id FROM model_provider WHERE id = 'prov-bf-0001'")
                )
                .scalar_one()
            )
            assert legacy == "cred-bf-0001"
        finally:
            engine.dispose()

        # 幂等：重复 upgrade（no-op）+ 再跑回填不产生重复行。
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert _count(engine, "model_provider_credential") == 1
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


def test_migration_0011_postgres() -> None:  # pragma: no cover - CI 门控
    """PostgreSQL：``0011`` 双向 + 零漂移（CI ``postgres-smoke`` job 实跑）。"""
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
            assert PHASE2_CREDENTIAL_TABLES.issubset(tables)
            assert CREDENTIAL_NEW_COLUMNS.issubset(_columns(engine, "credential"))
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        command.downgrade(config, "0010_phase2_permission_plugin")
        engine = sa.create_engine(url)
        try:
            remaining = set(sa.inspect(engine).get_table_names())
            assert remaining.isdisjoint(PHASE2_CREDENTIAL_TABLES)
            assert _columns(engine, "credential").isdisjoint(CREDENTIAL_NEW_COLUMNS)
        finally:
            engine.dispose()

        command.downgrade(config, "base")
    finally:
        reset_settings_cache()
