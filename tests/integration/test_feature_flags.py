"""Feature Flag 集成测试（T0-21 / 决策 D7 / 验收 §3-#14）。

覆盖：迁移 0002 往返；``SqlFeatureFlagStore`` 读写往返；表缺失降级；
**关闭全部 flag → 应用仍可启动**；``GET /settings/features`` 只读观测。
"""

from __future__ import annotations

import json
from pathlib import Path

from astra_config import FEATURE_FLAGS
from astra_database import FeatureFlag, SqlFeatureFlagStore

REPO_ROOT = Path(__file__).resolve().parents[2]


# -- 迁移 0002 往返 ----------------------------------------------------------


def test_migration_0002_upgrade_downgrade_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """``upgrade head`` 建 ``feature_flag``；回退到 0001 删表；可再升级。

    注意：Phase 1 之后 head=``0006_phase1_conversation``，故**必须按显式 revision**
    回退到 ``0001_phase0_baseline``（``0002`` 的 ``down_revision``），否则 ``-1``
    只会回退最后一个迁移而 ``feature_flag`` 仍在。
    """
    db_file = tmp_path / "ff_migration.db"
    url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("ASTRA_MODE", "local")
    monkeypatch.setenv("ASTRA_DATABASE_URL", url)
    monkeypatch.delenv("ASTRA_CONFIG_FILE", raising=False)

    from astra_config.loader import reset_settings_cache

    reset_settings_cache()

    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    alembic_config = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(REPO_ROOT / "migrations"))

    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(url)
    try:
        assert "feature_flag" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # 回退到 0001（删除 0002 建的 feature_flag 表）。
    command.downgrade(alembic_config, "0001_phase0_baseline")
    engine = sa.create_engine(url)
    try:
        assert "feature_flag" not in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # 再次升级（验证可重复往返）。
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(url)
    try:
        assert "feature_flag" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    reset_settings_cache()


# -- SqlFeatureFlagStore -----------------------------------------------------


def test_sql_store_read_write_roundtrip(session_factory) -> None:
    """``upsert`` 写入后 ``load_overrides`` 可读回（幂等）。"""
    store = SqlFeatureFlagStore(session_factory)
    assert store.load_overrides() == {}

    store.upsert("workspace", False, description="集成测试")
    store.upsert("workspace", False)  # 幂等更新

    assert store.load_overrides() == {"workspace": False}

    store.upsert("workspace", True)
    assert store.load_overrides() == {"workspace": True}

    # 独立校验落库实体唯一。
    with session_factory() as session:
        rows = session.query(FeatureFlag).filter_by(name="workspace").all()
        assert len(rows) == 1


def test_sql_store_missing_table_returns_empty() -> None:
    """表缺失 / 无表 → ``load_overrides`` 返回 ``{}``（不抛，§3-#14）。"""
    import sqlalchemy as sa
    from astra_database import create_session_factory

    engine = sa.create_engine("sqlite://")  # 内存库，且不建任何表
    factory = create_session_factory(engine)
    try:
        store = SqlFeatureFlagStore(factory)
        assert store.load_overrides() == {}
    finally:
        engine.dispose()


# -- §3-#14：关全部 flag 应用仍可启动 ---------------------------------------


def test_all_flags_disabled_app_still_starts(isolated_settings_env, monkeypatch) -> None:
    """关闭**全部** flag → ``create_app`` lifespan 仍正常、``/health`` 200。"""
    all_off = {name: False for name in FEATURE_FLAGS}
    monkeypatch.setenv("ASTRA_FEATURE_FLAGS", json.dumps(all_off))

    from astra_config.loader import reset_settings_cache

    reset_settings_cache()

    from astra_api.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as test_client:
        assert test_client.get("/health").status_code == 200

    reset_settings_cache()


# -- GET /settings/features 只读观测 ----------------------------------------


def test_features_endpoint_default_all_true(client, auth_headers) -> None:
    """默认无覆盖 → 端点返回全部 flag 且均为 ``True``。"""
    response = client.get("/api/v1/settings/features", headers=auth_headers)
    assert response.status_code == 200, response.text
    flags = response.json()["data"]["flags"]
    assert set(flags) == set(FEATURE_FLAGS)
    assert all(flags.values())
