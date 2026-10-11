"""Sandbox 组合工厂（C-01 config 装配入口，W4 架构裁定 Q3）。

- :func:`build_sandbox_provider`：**唯一**按 ``settings.sandbox_provider`` 分流的装配点
  （经 ``astra_config.providers._build_optional`` 函数级延迟导入调用）；
  - ``local_process`` → **直接**构造 :class:`LocalProcessSandboxProvider`（**不探测** Docker）；
  - ``docker`` → ``docker_available()`` 为真则 :class:`DockerSandboxProvider`，为假则
    **``raise DomainError(CONFIGURATION_ERROR)``（不静默降级，A-5 / §2.10）**。
- :func:`create_local_process_provider` / :func:`create_docker_provider`：模式无关的显式构造入口。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import SANDBOX_PROVIDER_DOCKER, SANDBOX_PROVIDER_LOCAL_PROCESS

from .availability import docker_available
from .base import SandboxProvider
from .docker_provider import DockerSandboxProvider
from .local_process_provider import LocalProcessSandboxProvider

__all__ = [
    "build_sandbox_provider",
    "create_local_process_provider",
    "create_docker_provider",
]


def _setting(settings: Any, name: str, default: Any) -> Any:
    """读取 settings 字段（容错：缺字段 / ``None`` 时回退默认）。"""
    value = getattr(settings, name, default)
    return default if value is None else value


def _default_workdir(settings: Any) -> str | None:
    """解析默认工作目录：``sandbox_workdir`` 优先，否则 ``{data_dir}/sandbox``。"""
    configured = str(_setting(settings, "sandbox_workdir", "") or "").strip()
    if configured:
        return configured
    data_dir = str(_setting(settings, "data_dir", "") or "").strip()
    if data_dir:
        return os.path.join(Path(data_dir).expanduser().as_posix(), "sandbox")
    return None


def create_local_process_provider(settings: Any) -> LocalProcessSandboxProvider:
    """按配置构造 LocalProcess 沙箱（社区默认，**不探测** Docker）。"""
    return LocalProcessSandboxProvider(workspace_root=_default_workdir(settings))


def create_docker_provider(settings: Any) -> DockerSandboxProvider:
    """按配置构造 Docker 沙箱（镜像基线 ``settings.sandbox_image``）。"""
    return DockerSandboxProvider(image=str(_setting(settings, "sandbox_image", "python:3.12-slim")))


def build_sandbox_provider(settings: Any) -> SandboxProvider:
    """按 ``settings.sandbox_provider`` 装配 SandboxProvider（C-01 唯一装配点）。

    Args:
        settings: 生效配置（读 ``sandbox_provider`` / ``sandbox_image`` / ``sandbox_workdir``）。

    Returns:
        装配完成的 :class:`~astra_sandbox.base.SandboxProvider`。

    Raises:
        DomainError: 显式配置 ``docker`` 但不可用（``CONFIGURATION_ERROR``，**不静默降级**）；
            或 ``sandbox_provider`` 取值非法（``CONFIGURATION_ERROR``）。
    """
    kind = str(_setting(settings, "sandbox_provider", SANDBOX_PROVIDER_LOCAL_PROCESS))

    if kind == SANDBOX_PROVIDER_LOCAL_PROCESS:
        return create_local_process_provider(settings)

    if kind == SANDBOX_PROVIDER_DOCKER:
        if not docker_available():
            raise DomainError(
                "显式配置 docker 沙箱但 Docker 不可用；"
                "请安装 Docker（`uv sync --extra docker`）或改用 "
                "ASTRA_SANDBOX_PROVIDER=local_process",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"sandbox_provider": kind},
            )
        return create_docker_provider(settings)

    raise DomainError(
        f"sandbox_provider 取值非法：{kind!r}",
        code=ErrorCode.CONFIGURATION_ERROR,
        data={
            "field": "sandbox_provider",
            "allowed": [SANDBOX_PROVIDER_LOCAL_PROCESS, SANDBOX_PROVIDER_DOCKER],
        },
    )
