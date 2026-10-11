"""Sandbox 网络隔离配置（T2-56；设计 §2.18 / §2.8.1）。

两档网络策略：

- **OFFLINE（默认）**：``network=none``——沙箱容器**无任何网络**（DNS / UDP / TCP / 宿主网络
  一律不可达）；
- **ALLOWLISTED**：接入**内部** Docker 网络（``internal: true``，**无外部路由**），沙箱只能与
  同网络内的**受控 Egress Proxy** 通信；容器注入 ``HTTP_PROXY`` / ``HTTPS_PROXY`` 指向代理，
  由代理对**每次连接**调用既有 ``EgressPolicy``（唯一判定源，不得另建白名单）。

🔴 **保守默认**：Agent / Build / Test Sandbox 默认 ``network=none``；若部署不能证明**网络层**
   强制策略，**不得**给 Agent Sandbox 开公网路由（A-13 / D19 / RK-6）。

🔴 本模块**零** Web / ORM / ``astra_database``（抽象包分层）；仅标准库 + 本包常量。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "NETWORK_OFFLINE",
    "NETWORK_PROFILE_OFFLINE",
    "NETWORK_PROFILE_ALLOWLISTED",
    "DEFAULT_EGRESS_NETWORK",
    "DEFAULT_EGRESS_PROXY_PORT",
    "NETWORK_PROFILES",
    "SandboxNetworkConfig",
    "network_config_from_settings",
]

#: Docker 网络模式：无网络。
NETWORK_OFFLINE = "none"

#: 网络档位：离线（默认，``network=none``）。
NETWORK_PROFILE_OFFLINE = "offline"

#: 网络档位：白名单（接入**内部**网络 + 受控 Egress Proxy）。
NETWORK_PROFILE_ALLOWLISTED = "allowlisted"

#: 合法网络档位集合。
NETWORK_PROFILES = (NETWORK_PROFILE_OFFLINE, NETWORK_PROFILE_ALLOWLISTED)

#: 默认内部 Egress 网络名（Compose 档创建，``internal: true``）。
DEFAULT_EGRESS_NETWORK = "astra-sandbox-egress"

#: 受控 Egress Proxy 默认监听端口。
DEFAULT_EGRESS_PROXY_PORT = 8888


@dataclass(frozen=True)
class SandboxNetworkConfig:
    """Sandbox 网络策略（不可变）。

    Attributes:
        profile: 档位（``offline`` / ``allowlisted``）。
        egress_network: ALLOWLISTED 时接入的内部网络名。
        egress_proxy_url: 受控 Egress Proxy 地址
            （``http://host:port``；ALLOWLISTED 时必填才有意义）。
        proxy_port: 代理端口（用于构造默认 URL / 文档）。
    """

    profile: str = NETWORK_PROFILE_OFFLINE
    egress_network: str = DEFAULT_EGRESS_NETWORK
    egress_proxy_url: str = ""
    proxy_port: int = DEFAULT_EGRESS_PROXY_PORT

    def __post_init__(self) -> None:
        """校验档位合法。"""
        if self.profile not in NETWORK_PROFILES:
            raise ValueError(
                f"非法 sandbox 网络档位：{self.profile!r}；允许 {list(NETWORK_PROFILES)}"
            )

    @property
    def is_isolated(self) -> bool:
        """是否处于**默认隔离**（无公网路由）。"""
        return self.profile == NETWORK_PROFILE_OFFLINE

    @property
    def network_mode(self) -> str:
        """Docker ``network_mode`` 取值。

        - ``offline`` → ``"none"``；
        - ``allowlisted`` → 内部网络名（``internal: true``，无外部路由）。
        """
        if self.profile == NETWORK_PROFILE_ALLOWLISTED:
            return self.egress_network
        return NETWORK_OFFLINE

    def container_environment(self) -> dict[str, str]:
        """需要注入沙箱容器的代理环境变量（仅 ALLOWLISTED 且配 URL 时非空）。"""
        if self.profile != NETWORK_PROFILE_ALLOWLISTED or not self.egress_proxy_url:
            return {}
        return {
            "HTTP_PROXY": self.egress_proxy_url,
            "HTTPS_PROXY": self.egress_proxy_url,
            "http_proxy": self.egress_proxy_url,
            "https_proxy": self.egress_proxy_url,
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1",
        }


def network_config_from_settings(settings: Any) -> SandboxNetworkConfig:
    """由 ``Settings`` 构造 :class:`SandboxNetworkConfig`（容错缺字段 → 默认 OFFLINE）。

    Args:
        settings: 生效配置（读 ``sandbox_network_profile`` / ``sandbox_egress_network`` /
            ``sandbox_egress_proxy_url``）。

    Returns:
        :class:`SandboxNetworkConfig`。
    """
    profile = str(getattr(settings, "sandbox_network_profile", NETWORK_PROFILE_OFFLINE) or "")
    if profile not in NETWORK_PROFILES:
        profile = NETWORK_PROFILE_OFFLINE
    network = str(
        getattr(settings, "sandbox_egress_network", DEFAULT_EGRESS_NETWORK)
        or DEFAULT_EGRESS_NETWORK
    )
    proxy_url = str(getattr(settings, "sandbox_egress_proxy_url", "") or "")
    return SandboxNetworkConfig(profile=profile, egress_network=network, egress_proxy_url=proxy_url)
