"""配置层三级加载与覆盖单元测试（ENV → config.yaml → 默认值）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_config.loader import load_yaml_config, reset_settings_cache
from astra_config.settings import Settings

_ENV_KEYS = (
    "ASTRA_MODE",
    "ASTRA_DATABASE_URL",
    "ASTRA_LOG_LEVEL",
    "ASTRA_SECRET_KEY",
    "ASTRA_CONFIG_FILE",
)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.mode == "local"
    assert settings.database_url.startswith("sqlite")


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "mode: server\ndatabase_url: sqlite:///from_yaml.db\nlog_level: DEBUG\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTRA_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("ASTRA_MODE", "local")  # ENV 应覆盖 yaml 的 server
    monkeypatch.delenv("ASTRA_DATABASE_URL", raising=False)
    monkeypatch.delenv("ASTRA_LOG_LEVEL", raising=False)
    reset_settings_cache()

    settings = Settings()
    assert settings.mode == "local"  # ENV 优先
    assert settings.database_url == "sqlite:///from_yaml.db"  # yaml 提供
    assert settings.log_level == "DEBUG"  # yaml 提供


def test_sensitive_key_not_read_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("secret_key: leaked-secret\nmode: local\n", encoding="utf-8")
    data = load_yaml_config(config_file)
    assert "secret_key" not in data
    assert data.get("mode") == "local"
