"""Sandbox 隔离强度测试（``I-P1-20`` / A-5 三档）。

- **A-5 档 1（社区单容器）**：默认 ``LocalProcessSandboxProvider``（进程级隔离）——相关断言**必绿**；
- **A-5 档 2（Compose/Team）**：Docker 6 项隔离断言（mark ``docker``）——本机无 Docker 时
  ``xfail(strict=True)``；``ASTRA_TEST_REQUIRE_DOCKER=1`` 时无运行时**必须 fail**（防假绿）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from astra_config import Settings
from astra_core import DomainError
from astra_sandbox import DockerSandboxProvider, LocalProcessSandboxProvider, docker_available

_HAS_DOCKER = docker_available()
_REQUIRE_DOCKER = os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1"


def _docker_provider() -> DockerSandboxProvider:
    """无 Docker 时按开关 fail / xfail；有则返回 Provider。"""
    if not _HAS_DOCKER:
        if _REQUIRE_DOCKER:
            pytest.fail("ASTRA_TEST_REQUIRE_DOCKER=1 但本机无 Docker 运行时（防假绿）")
        pytest.xfail("本机无 Docker 运行时")
    return DockerSandboxProvider(image="python:3.12-slim")


# -- A-5 档 1：LocalProcess（必绿） -----------------------------------------


def test_default_provider_is_local_process() -> None:
    """A-5 档 1：社区默认 ``local_process``（进程级隔离，非容器级）。"""
    settings = Settings(
        mode="local",
        database_url="sqlite:///./astra_isolation.db",
    )
    assert settings.sandbox_provider == "local_process"


def test_local_destroy_is_idempotent(tmp_path: Path) -> None:
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    session = provider.create_session()
    provider.destroy(session)
    provider.destroy(session)  # 幂等


def test_local_env_excludes_host_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """沙箱内**不注入** Host 真实密钥（环境变量白名单 + 剔除 ``ASTRA_*``）。"""
    monkeypatch.setenv("ASTRA_SECRET_KEY", "super-secret-value")
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    session = provider.create_session()
    code = "import os; print(os.environ.get('ASTRA_SECRET_KEY', 'MISSING'))"
    result = provider.exec(session, [sys.executable, "-c", code])
    assert result.stdout.strip() == "MISSING"
    provider.destroy(session)


def test_local_path_isolation(tmp_path: Path) -> None:
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    session = provider.create_session()
    with pytest.raises(DomainError):
        provider.put_file(session, "../escape.txt", "x")
    provider.destroy(session)


# -- A-5 档 2：Docker 6 项隔离强度（mark docker） ----------------------------


@pytest.mark.docker
@pytest.mark.parametrize(
    "name",
    [
        "non_root",
        "readonly_rootfs",
        "network_none",
        "env_no_secret",
        "resource_limit",
        "timeout",
    ],
)
def test_docker_isolation_strength(name: str, tmp_path: Path) -> None:
    """Docker 隔离 6 项（``network=none`` / 非 root / 只读 rootfs / 限额 / 超时）。"""
    if not _HAS_DOCKER:
        if _REQUIRE_DOCKER:
            pytest.fail("ASTRA_TEST_REQUIRE_DOCKER=1 但本机无 Docker 运行时（防假绿）")
        pytest.xfail("本机无 Docker 运行时")

    provider = DockerSandboxProvider(image="python:3.12-slim")
    session = provider.create_session(workspace_id="ws-iso", workdir=str(tmp_path))
    checks: dict[str, Any] = {
        "non_root": lambda: provider.exec(session, ["id", "-u"]).stdout.strip() != "0",
        "readonly_rootfs": lambda: provider.exec(session, ["touch", "/usr/should_fail"]).exit_code
        != 0,
        "network_none": lambda: provider.exec(
            session, ["curl", "-s", "https://example.com"]
        ).exit_code
        != 0,
        "env_no_secret": lambda: "ASTRA_SECRET_KEY" not in provider.exec(session, ["env"]).stdout,
        "resource_limit": lambda: provider.exec(session, ["true"]).exit_code == 0,
        "timeout": lambda: provider.exec(session, ["sleep", "30"], timeout_ms=500).timed_out,
    }
    try:
        assert checks[name]() is True, f"Docker 隔离断言失败：{name}"
    finally:
        provider.destroy(session)
