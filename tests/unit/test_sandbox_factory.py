"""``build_sandbox_provider`` 装配单测（含 ``docker`` 不可用 → 报错，不静默降级）。"""

from __future__ import annotations

import astra_sandbox.factory as factory_module
import pytest
from astra_config import Settings
from astra_core import DomainError, ErrorCode
from astra_sandbox import (
    DockerSandboxProvider,
    LocalProcessSandboxProvider,
    build_sandbox_provider,
)


def _settings(**kwargs: object) -> Settings:
    base = {
        "mode": "local",
        "database_url": "sqlite:///./astra_unit.db",
        "data_dir": "/tmp/astra-unit",  # noqa: S108 - 仅字符串，不实际写盘
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_local_process_does_not_probe_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> bool:  # pragma: no cover - 若被调用即失败
        raise AssertionError("local_process 不应探测 Docker")

    monkeypatch.setattr(factory_module, "docker_available", _boom)
    provider = build_sandbox_provider(_settings(sandbox_provider="local_process"))
    assert isinstance(provider, LocalProcessSandboxProvider)
    assert provider.kind == "local_process"
    assert provider.available is True


def test_docker_unavailable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory_module, "docker_available", lambda: False)
    with pytest.raises(DomainError) as excinfo:
        build_sandbox_provider(_settings(sandbox_provider="docker"))
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_docker_available_builds_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory_module, "docker_available", lambda: True)
    provider = build_sandbox_provider(
        _settings(sandbox_provider="docker", sandbox_image="python:3.12-slim")
    )
    assert isinstance(provider, DockerSandboxProvider)
    assert provider.kind == "docker"
