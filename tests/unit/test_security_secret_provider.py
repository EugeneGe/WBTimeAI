"""``EnvSecretProvider`` 单测（读取与缺失报错）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_security import EnvSecretProvider


def test_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASTRA_SECRET_KEY", "from-env")
    provider = EnvSecretProvider()
    assert provider.get("SECRET_KEY") == "from-env"
    assert provider.get_required("SECRET_KEY") == "from-env"


def test_missing_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASTRA_MISSING_KEY", raising=False)
    assert EnvSecretProvider().get("MISSING_KEY", "fallback") == "fallback"


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASTRA_MISSING_KEY", raising=False)
    with pytest.raises(DomainError) as excinfo:
        EnvSecretProvider().get_required("MISSING_KEY")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_reads_from_secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASTRA_FILE_KEY", raising=False)
    (tmp_path / "FILE_KEY").write_text("from-file\n", encoding="utf-8")
    provider = EnvSecretProvider(secrets_dir=tmp_path)
    assert provider.get("FILE_KEY") == "from-file"
