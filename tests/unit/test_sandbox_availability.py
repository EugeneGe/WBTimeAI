"""``astra_sandbox.availability`` 三态探测 + ``astra doctor`` docker 判定（F-2 回归）。

背景（QA V-A F-2）：部署镜像**仅含 docker SDK、无 docker CLI**；旧 ``check_docker`` 以
``shutil.which("docker")`` 判定 → worker ``astra doctor`` 误报 FAIL，而装配侧
``docker_available()``（SDK + ``ping``）实为可用。本用例锁定「doctor 语义 == capabilities
装配语义」：两者**共用** :func:`~astra_sandbox.availability.docker_sdk_status`，**不**依赖 CLI。
"""

from __future__ import annotations

import sys
import types

import astra_sandbox.availability as availability
import pytest
from astra_cli import doctor_checks as dc
from astra_config import Settings


def _settings(sandbox_provider: str) -> Settings:
    """构造最小可用的 ``Settings``（仅字符串，不落盘）。"""
    return Settings(
        mode="local",
        database_url="sqlite:///./astra_unit.db",
        data_dir="/tmp/astra-unit",  # noqa: S108 - 仅字符串，不实际写盘
        sandbox_provider=sandbox_provider,
    )


def _fake_docker(*, ping: bool = True, raise_on_env: bool = False) -> types.ModuleType:
    """构造替身 ``docker`` 模块（``from_env().ping()`` 可控）。"""
    module = types.ModuleType("docker")

    def from_env() -> object:
        if raise_on_env:
            raise RuntimeError("daemon down")

        class _Client:
            def ping(self) -> bool:  # noqa: D401 - 替身
                return ping

        return _Client()

    module.from_env = from_env  # type: ignore[attr-defined]
    return module


# -- docker_sdk_status / docker_available --------------------------------------


def test_status_no_sdk_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """``docker`` SDK 不可导入 → ``no_sdk``，且 ``docker_available()`` 为假。"""
    monkeypatch.setitem(sys.modules, "docker", None)  # 令 ``import docker`` 抛 ImportError
    assert availability.docker_sdk_status() == "no_sdk"
    assert availability.docker_available() is False


def test_status_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 就位 + ``ping()`` 真 → ``reachable``；``docker_available()`` 为真。"""
    monkeypatch.setitem(sys.modules, "docker", _fake_docker(ping=True))
    assert availability.docker_sdk_status() == "reachable"
    assert availability.docker_available() is True


def test_status_unreachable_when_ping_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 就位但 ``ping()`` 假 → ``unreachable``。"""
    monkeypatch.setitem(sys.modules, "docker", _fake_docker(ping=False))
    assert availability.docker_sdk_status() == "unreachable"
    assert availability.docker_available() is False


def test_status_unreachable_when_from_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_env()`` 抛异常 → ``unreachable``（探测容错，不抛出）。"""
    monkeypatch.setitem(sys.modules, "docker", _fake_docker(raise_on_env=True))
    assert availability.docker_sdk_status() == "unreachable"


# -- check_docker（F-2 核心回归：不依赖 docker CLI） ----------------------------


def test_check_docker_ok_via_sdk_without_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """**F-2 回归**：SDK 可达即 ``ok``——即便无 docker CLI（旧实现会误报 FAIL）。"""
    monkeypatch.setattr(availability, "docker_sdk_status", lambda: "reachable")
    name, status, detail = dc.check_docker(_settings("docker"))
    assert (name, status) == ("docker", "ok")
    assert "SDK" in detail


def test_check_docker_fails_when_docker_required_but_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式要求 docker 但无 SDK → ``fail``（明确配置错误，非静默）。"""
    monkeypatch.setattr(availability, "docker_sdk_status", lambda: "no_sdk")
    name, status, detail = dc.check_docker(_settings("docker"))
    assert (name, status) == ("docker", "fail")
    assert "SDK" in detail


def test_check_docker_skips_when_sdk_missing_community(monkeypatch: pytest.MonkeyPatch) -> None:
    """社区（local_process）无 SDK → ``skip``（降级，非错误）。"""
    monkeypatch.setattr(availability, "docker_sdk_status", lambda: "no_sdk")
    name, status, _ = dc.check_docker(_settings("local_process"))
    assert (name, status) == ("docker", "skip")


def test_check_docker_fails_when_docker_required_but_daemon_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式要求 docker 但 daemon 不可达 → ``fail``。"""
    monkeypatch.setattr(availability, "docker_sdk_status", lambda: "unreachable")
    name, status, _ = dc.check_docker(_settings("docker"))
    assert (name, status) == ("docker", "fail")


def test_check_docker_skips_when_daemon_unreachable_community(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """社区 daemon 不可达 → ``skip``。"""
    monkeypatch.setattr(availability, "docker_sdk_status", lambda: "unreachable")
    name, status, _ = dc.check_docker(_settings("local_process"))
    assert (name, status) == ("docker", "skip")
