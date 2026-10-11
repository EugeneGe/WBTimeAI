"""迁移往返集成测试：``upgrade head`` ↔ ``downgrade base``。"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_TABLES = {
    "tenant",
    "user",
    "organization",
    "membership",
    "role",
    "permission",
    "role_permission",
    "session",
    "refresh_token",
    "login_attempt",
    "workspace",
    "task",
    "credential",
}


def test_migration_upgrade_downgrade_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "migration_test.db"
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

    # -- upgrade ------------------------------------------------------------
    command.upgrade(alembic_config, "head")

    engine = sa.create_engine(url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert _EXPECTED_TABLES.issubset(tables)

    # -- downgrade ----------------------------------------------------------
    command.downgrade(alembic_config, "base")

    engine = sa.create_engine(url)
    try:
        remaining = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert remaining.isdisjoint(_EXPECTED_TABLES)

    reset_settings_cache()
