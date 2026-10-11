"""SandboxProvider 契约套件（参数化 fake / local_process / docker）。

断言抽象可替换：协议满足 / 生命周期 / 目录隔离（文件往返）/ 退出码透传 / ``destroy()`` 幂等
（``C-P1-21``）。

- 协议收敛（``isinstance``）无需 Docker 运行时——三实现均直接断言；
- 生命周期 / 执行需真实运行时：``local_process`` / ``fake`` 必绿；``docker`` 参数
  ``xfail(strict=True)``；设 ``ASTRA_TEST_REQUIRE_DOCKER=1`` 时无运行时**必须 fail**（防假绿）。
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest
from astra_sandbox import (
    DockerSandboxProvider,
    LocalProcessSandboxProvider,
    docker_available,
)
from astra_sandbox.base import SandboxProvider

pytestmark = pytest.mark.contracts

_HAS_DOCKER = docker_available()
_REQUIRE_DOCKER = os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1"


class FakeSandboxProvider:
    """Fake 提供方：文件 / 执行委托 ``LocalProcessSandboxProvider``（契约参数化用）。"""

    kind = "fake"

    def __init__(self) -> None:
        self._delegate = LocalProcessSandboxProvider()

    @property
    def available(self) -> bool:
        return True

    def create_session(self, **kwargs: Any) -> Any:
        return self._delegate.create_session(**kwargs)

    def exec(self, session: Any, command: Any, **kwargs: Any) -> Any:
        return self._delegate.exec(session, command, **kwargs)

    def put_file(self, session: Any, path: str, content: str) -> None:
        self._delegate.put_file(session, path, content)

    def get_file(self, session: Any, path: str) -> str:
        return self._delegate.get_file(session, path)

    def destroy(self, session: Any) -> None:
        self._delegate.destroy(session)


def _build_provider(name: str, tmp_path: Any) -> Any:
    """按名构造 provider（构造本身不使用 Docker 运行时）。"""
    if name == "fake":
        return FakeSandboxProvider()
    if name == "local_process":
        return LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    if name == "docker":
        return DockerSandboxProvider(image="python:3.12-slim")
    raise AssertionError(f"未知 provider: {name!r}")  # pragma: no cover


# -- 协议收敛（无需 Docker 运行时） ------------------------------------------


@pytest.fixture(params=["fake", "local_process", "docker"])
def provider(request: pytest.FixtureRequest, tmp_path: Any) -> Any:
    """参数化三实现（构造即返回；协议断言不依赖运行时）。"""
    return _build_provider(request.param, tmp_path)


def test_provider_satisfies_protocol(provider: Any) -> None:
    assert isinstance(provider, SandboxProvider)
    assert provider.kind in {"docker", "local_process", "fake"}
    assert isinstance(provider.available, bool)


# -- 生命周期 / 执行（需运行时） -------------------------------------------


def _live_params() -> list[Any]:
    params = [
        pytest.param("fake", id="fake"),
        pytest.param("local_process", id="local_process"),
    ]
    if _HAS_DOCKER:
        params.append(pytest.param("docker", id="docker", marks=pytest.mark.docker))
    elif _REQUIRE_DOCKER:
        # 强开关：不做 xfail，直接运行 → 无 Docker 即 fail（防假绿）。
        params.append(pytest.param("docker", id="docker", marks=pytest.mark.docker))
    else:
        params.append(
            pytest.param(
                "docker",
                id="docker",
                marks=[
                    pytest.mark.docker,
                    pytest.mark.xfail(strict=True, reason="本机无 Docker 运行时"),
                ],
            )
        )
    return params


@pytest.fixture(params=_live_params())
def live_provider(request: pytest.FixtureRequest, tmp_path: Any) -> Any:
    """参数化三实现（仅 ``fake`` / ``local_process`` 与真实运行时有保证）。"""
    return _build_provider(request.param, tmp_path)


def test_lifecycle_files_and_destroy_idempotent(live_provider: Any) -> None:
    session = live_provider.create_session(workspace_id="ws-1", run_id="run-1")
    assert isinstance(session.provider, str) and session.provider
    assert session.workdir

    live_provider.put_file(session, "data.txt", "content-123")
    assert live_provider.get_file(session, "data.txt") == "content-123"

    live_provider.destroy(session)
    live_provider.destroy(session)  # 幂等：重复调用不报错


def test_exec_output_and_exit_code(live_provider: Any) -> None:
    session = live_provider.create_session()
    ok = live_provider.exec(session, [sys.executable, "-c", "print('hello')"])
    assert ok.exit_code == 0
    assert "hello" in ok.stdout

    failed = live_provider.exec(session, [sys.executable, "-c", "import sys; sys.exit(3)"])
    assert failed.exit_code == 3
    live_provider.destroy(session)
