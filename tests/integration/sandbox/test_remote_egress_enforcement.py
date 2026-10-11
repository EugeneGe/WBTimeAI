"""Sandbox 网络隔离与 Egress Proxy 强制（R1 / T2-56；设计 §2.18 / §2.8.1）。

验收口径 ``I-P2-42`` / 发布门禁 ``#42`` / ``D19``：

- **默认隔离**：Agent / Build / Test Sandbox ``network=none``（DNS / UDP / TCP / 宿主网络不可达）；
- **受控出网**：``allowlisted`` 档接入**内部**网络（无外部路由）+ 受控 Egress Proxy；
  代理对每次连接调用**同一** :class:`SecurityEgressPolicy`（**唯一判定源**，不另建白名单）；
- **拒段不可覆盖**：私网 / 元数据 / DNS rebinding 一律被拒（白名单不可覆盖）；
- **网络层强制**：断言仅在**可证明网络层强制**的 Docker / Compose 档成立（A-13）；
  缺该能力的 CI 转 **Manual 但不豁免**（A-12）。

本机无 Docker → 网络层用例 ``skip``（Manual / 服务器面）；**静态装配 + 策略委派**用例**始终执行**。
"""

from __future__ import annotations

import pytest
from astra_config import Settings
from astra_sandbox import (
    DEFAULT_EGRESS_NETWORK,
    NETWORK_OFFLINE,
    NETWORK_PROFILE_ALLOWLISTED,
    NETWORK_PROFILE_OFFLINE,
    DockerSandboxProvider,
    SandboxNetworkConfig,
    create_docker_provider,
    network_config_from_settings,
)
from astra_security.egress import ControlledEgressProxy, SecurityEgressPolicy

# -- 1. 默认隔离（network=none） --------------------------------------------


def test_docker_provider_defaults_to_network_none() -> None:
    """默认档位 ``offline`` → ``network=none``（保守默认，无任何网络）。"""
    provider = DockerSandboxProvider()
    assert provider.network_profile == NETWORK_PROFILE_OFFLINE
    assert provider.network == NETWORK_OFFLINE
    assert provider.container_environment() == {}


def test_network_config_defaults_offline() -> None:
    cfg = network_config_from_settings(Settings())
    assert cfg.profile == NETWORK_PROFILE_OFFLINE
    assert cfg.network_mode == NETWORK_OFFLINE
    assert cfg.is_isolated is True
    assert cfg.container_environment() == {}


@pytest.mark.parametrize("bad", ["public", "host", "bridge", ""])
def test_network_config_rejects_illegal_profile(bad: str) -> None:
    with pytest.raises(ValueError):
        SandboxNetworkConfig(profile=bad)


# -- 2. ALLOWLISTED 档：内部网络 + 代理注入 ---------------------------------


def test_allowlisted_profile_uses_internal_network_and_injects_proxy() -> None:
    proxy_url = "http://egress-proxy:8888"
    provider = DockerSandboxProvider(
        network_profile=NETWORK_PROFILE_ALLOWLISTED,
        egress_network=DEFAULT_EGRESS_NETWORK,
        egress_proxy_url=proxy_url,
    )
    # 接入内部网络（非 none），但**非**外部网络名。
    assert provider.network == DEFAULT_EGRESS_NETWORK
    assert provider.network != NETWORK_OFFLINE
    assert provider.network_profile == NETWORK_PROFILE_ALLOWLISTED
    env = provider.container_environment()
    assert env["HTTP_PROXY"] == proxy_url
    assert env["HTTPS_PROXY"] == proxy_url
    # 本地回环不走代理。
    assert "127.0.0.1" in env["NO_PROXY"]


def test_allowlisted_without_proxy_url_injects_nothing() -> None:
    provider = DockerSandboxProvider(
        network_profile=NETWORK_PROFILE_ALLOWLISTED, egress_proxy_url=""
    )
    # 未配代理 URL → 不注入环境变量（避免“看起来可出网”的假象）。
    assert provider.container_environment() == {}


def test_factory_reads_network_config_from_settings() -> None:
    settings = Settings(
        mode="local",
        database_url="sqlite:///./astra_unit.db",
        data_dir="/tmp/astra-unit",  # noqa: S108 - 仅字符串
        sandbox_network_profile="allowlisted",
        sandbox_egress_network="astra-sandbox-egress",
        sandbox_egress_proxy_url="http://egress-proxy:8888",
    )
    provider = create_docker_provider(settings)
    assert provider.network == "astra-sandbox-egress"
    assert provider.container_environment()["HTTPS_PROXY"] == "http://egress-proxy:8888"


# -- 3. 受控 Egress Proxy：复用**唯一**判定源 -------------------------------


def _public_resolver(host: str) -> list[str]:
    """把任意域名解析为固定公网 IP（测试用，避免真实 DNS）。"""
    return ["93.184.216.34"]


def test_proxy_reuses_same_policy_instance() -> None:
    """代理**复用**注入的同一 EgressPolicy（唯一判定源，不另建白名单）。"""
    policy = SecurityEgressPolicy(allow=["example.com"], resolver=_public_resolver)
    proxy = ControlledEgressProxy(policy)
    assert proxy.policy is policy


def test_proxy_denies_when_not_allowlisted() -> None:
    policy = SecurityEgressPolicy()  # 空白名单 → 默认拒绝全部
    proxy = ControlledEgressProxy(policy)
    assert proxy.authorize_connect("example.com", 443).allowed is False
    assert proxy.authorize_url("http://example.com/").allowed is False


def test_proxy_allows_allowlisted_host() -> None:
    policy = SecurityEgressPolicy(allow=["example.com"], resolver=_public_resolver)
    proxy = ControlledEgressProxy(policy)
    decision = proxy.authorize_connect("example.com", 443)
    assert decision.allowed is True
    assert decision.resolved_ip == "93.184.216.34"
    # 强制判定返回**钉定 IP**（供隧道使用，抵御 rebinding）。
    assert proxy.enforce_connect("example.com", 443) == "93.184.216.34"


def test_proxy_rejects_private_and_metadata_even_if_allowlisted() -> None:
    """拒段**不可被白名单覆盖**：私网 / 元数据地址被拒。"""
    policy = SecurityEgressPolicy(
        allow=["169.254.169.254", "10.0.0.1", "127.0.0.1"], resolver=_public_resolver
    )
    proxy = ControlledEgressProxy(policy)
    for host in ("169.254.169.254", "10.0.0.1", "127.0.0.1"):
        assert proxy.authorize_connect(host, 80).allowed is False, host


def test_proxy_rejects_dns_rebinding() -> None:
    """DNS rebinding：首解析公网、二次解析私网 → 拒绝。"""
    calls = {"n": 0}

    def _flip(host: str) -> list[str]:
        calls["n"] += 1
        return ["93.184.216.34"] if calls["n"] == 1 else ["10.0.0.5"]

    policy = SecurityEgressPolicy(allow=["example.com"], resolver=_flip)
    proxy = ControlledEgressProxy(policy)
    assert proxy.authorize_connect("example.com", 443).allowed is False


def test_proxy_denies_non_http_scheme() -> None:
    policy = SecurityEgressPolicy(allow=["*"], resolver=_public_resolver)
    proxy = ControlledEgressProxy(policy)
    assert proxy.authorize_url("ftp://example.com/").allowed is False


# -- 4. 网络层强制（Docker/Compose 档；CI 无 Docker → Manual） ---------------


def _docker_client_or_none():  # type: ignore[no-untyped-def]
    """返回可用 Docker 客户端；不可用返回 ``None``（本机无 Docker → 走 Manual）。"""
    try:
        import docker
    except ImportError:
        return None
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception:  # noqa: BLE001 - 探测容错
        return None


_DOCKER_CLIENT = _docker_client_or_none()


@pytest.mark.skipif(
    _DOCKER_CLIENT is None,
    reason="无 Docker：网络层强制属 Docker/Compose 档 Manual 面（A-13/A-12，不豁免；由服务器复验）",
)
def test_live_sandbox_network_none_blocks_direct_egress() -> None:
    """Docker Sandbox ``network=none`` 内 DNS / TCP 直连**均失败**（网络层强制证据）。"""
    provider = DockerSandboxProvider(client=_DOCKER_CLIENT)
    session = provider.create_session()
    try:
        # DNS 解析失败（无网络）。
        dns = provider.exec(
            session,
            ["python", "-c", "import socket; socket.getaddrinfo('example.com', 80)"],
        )
        assert dns.exit_code != 0
        # TCP 直连失败。
        tcp = provider.exec(
            session,
            [
                "python",
                "-c",
                "import socket; socket.create_connection(('93.184.216.34', 443), timeout=3)",
            ],
        )
        assert tcp.exit_code != 0
    finally:
        provider.destroy(session)
