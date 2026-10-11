"""Provider 自动装配「双模式非静默」单元测试（返修 2）。"""

from __future__ import annotations

import pytest
from astra_config.providers import build_providers
from astra_config.settings import Settings
from astra_core import DomainError, ErrorCode


def test_local_sqlite_builds_database() -> None:
    settings = Settings(mode="local", database_url="sqlite:///./_unit_providers.db")
    providers = build_providers(settings)
    assert providers.database is not None
    providers.database.engine.dispose()


def test_server_with_sqlite_url_raises_configuration_error() -> None:
    settings = Settings(mode="server", database_url="sqlite:///./_unit_providers.db")
    with pytest.raises(DomainError) as excinfo:
        build_providers(settings)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "PostgreSQL" in excinfo.value.message


def test_local_with_postgres_url_raises_configuration_error() -> None:
    settings = Settings(mode="local", database_url="postgresql://u:p@localhost:5432/db")
    with pytest.raises(DomainError) as excinfo:
        build_providers(settings)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "SQLite" in excinfo.value.message


def test_server_with_postgres_without_psycopg_raises_clear_error() -> None:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("psycopg 已安装，跳过『缺驱动』用例")

    settings = Settings(mode="server", database_url="postgresql+psycopg://u:p@localhost:5432/db")
    with pytest.raises(DomainError) as excinfo:
        build_providers(settings)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "psycopg" in excinfo.value.message
