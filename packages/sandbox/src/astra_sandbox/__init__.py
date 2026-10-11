"""Astra AI Sandbox 抽象层（``astra_sandbox``，设计 §2.10）。

- 抽象接口：SandboxProvider / SandboxSession / ExecResult（``base``）；
- 实现：DockerSandboxProvider（容器级）/ LocalProcessSandboxProvider（进程级，社区默认）；
- 可用性探测：:func:`docker_available`（``availability``，函数内延迟 ``import docker``）；
- 装配：:func:`build_sandbox_provider`（``factory``，C-01 config 装配入口）。

🔴 ``astra_sandbox`` 属**抽象包**：零 ORM、零 ``astra_database`` 导入（分层纪律）。
"""

from __future__ import annotations

from .availability import docker_available
from .base import ExecResult, SandboxProvider, SandboxSession
from .docker_provider import DockerSandboxProvider
from .factory import (
    build_sandbox_provider,
    create_docker_provider,
    create_local_process_provider,
)
from .local_process_provider import LocalProcessSandboxProvider
from .network import (
    DEFAULT_EGRESS_NETWORK,
    DEFAULT_EGRESS_PROXY_PORT,
    NETWORK_OFFLINE,
    NETWORK_PROFILE_ALLOWLISTED,
    NETWORK_PROFILE_OFFLINE,
    NETWORK_PROFILES,
    SandboxNetworkConfig,
    network_config_from_settings,
)
from .process_spawner import SubprocessProcessSpawner

__all__ = [
    "SandboxProvider",
    "SandboxSession",
    "ExecResult",
    "DockerSandboxProvider",
    "LocalProcessSandboxProvider",
    "SubprocessProcessSpawner",
    "docker_available",
    "build_sandbox_provider",
    "create_local_process_provider",
    "create_docker_provider",
    # T2-56：网络档位 / 受控 Egress 网络
    "SandboxNetworkConfig",
    "network_config_from_settings",
    "NETWORK_OFFLINE",
    "NETWORK_PROFILE_OFFLINE",
    "NETWORK_PROFILE_ALLOWLISTED",
    "NETWORK_PROFILES",
    "DEFAULT_EGRESS_NETWORK",
    "DEFAULT_EGRESS_PROXY_PORT",
]
