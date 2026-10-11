"""出网策略**原语**（唯一来源，零框架）——W1 / T2-03；设计 §2.18。

本模块提供**可复用出网原语**（拒段表 / IP 判定 / 域名匹配 / DNS 解析 / 决策 VO /
``EgressPolicy`` Protocol），下沉 ``astra_domain`` 以被 **``astra_tool``（抽象包）** 与
**``astra_security.egress``（唯一入口）** 共享——**单一来源、零新增依赖边**，
保「抽象包零 ORM」不变量（W1 裁定 §4.1 / §4.2 / F13）。

- 唯一**入口/实现**＝``astra_security.egress.SecurityEgressPolicy``；
- 本模块**只**提供原语，**不**承载配置 / 审计 / 重定向编排（属 ``security``）；
- ``astra_tool.security.check_egress`` **薄委托** 本模块原语（签名 / 语义不变）。

🔴 本子模块**零框架依赖**（仅标准库 + ``astra_core``）；受
   ``test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖。
"""

from __future__ import annotations

import fnmatch
import ipaddress
import socket
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from astra_core import ErrorCode

__all__ = [
    "METADATA_IPS",
    "DENY_RANGES",
    "ALLOWED_SCHEMES",
    "is_metadata_ip",
    "is_blocked_ip",
    "host_matches",
    "resolve_all",
    "EgressDecision",
    "EgressPolicy",
]

#: 云元数据端点（SSRF 重点；与 Phase 1 ``astra_tool.security.METADATA_IPS`` 单一来源）。
METADATA_IPS: frozenset[str] = frozenset(
    {"169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254"}
)

#: **强制拒段**（白名单**不可**覆盖；设计 §2.18 / W1 裁定 §4.4）。
#:
#: 覆盖 RFC1918 / loopback / link-local / ULA / unspecified / reserved / multicast，
#: 以及共享地址空间（CGNAT）/ 文档 / 基准测试等保留段。
DENY_RANGES: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    # RFC1918 私网
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # loopback
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    # link-local
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    # ULA（唯一本地地址）
    ipaddress.ip_network("fc00::/7"),
    # unspecified / "this network"
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),
    # reserved / 特殊用途
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("2001:db8::/32"),
    # multicast
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
)

#: 允许的出网 scheme。
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def is_metadata_ip(ip: str) -> bool:
    """判断 IP 是否为云元数据端点（``169.254.169.254`` 等）。"""
    return ip in METADATA_IPS


def is_blocked_ip(ip: str) -> bool:
    """判断 IP 是否为**禁止**访问（内网 / 环回 / 链路本地 / 保留 / 组播 / 元数据端点）。

    Args:
        ip: 待判定 IP 字面值。

    Returns:
        ``True`` 表示拒绝（含非法 IP，**fail-closed**）。
    """
    if is_metadata_ip(ip):
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True  # 非法 IP：拒绝
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return True
    for network in DENY_RANGES:
        if address.version == network.version and address in network:
            return True
    return False


def host_matches(host: str, patterns: Sequence[str] | Iterable[str] | None) -> bool:
    """判断 ``host`` 是否命中白名单（域名精确 / glob，或 IP 字面）。

    ``patterns`` 可含 scheme / path / port（会被剥离）；**空列表 ⇒ 一律不命中**
    （默认拒绝全部）。

    Args:
        host: 目标主机名（或 IP 字面）。
        patterns: 白名单条目集合。

    Returns:
        ``True`` 表示命中。
    """
    if not patterns:
        return False
    lowered = host.lower()
    for raw in patterns:
        pattern = str(raw).strip().lower()
        if not pattern:
            continue
        pattern = pattern.split("://", 1)[-1].split("/", 1)[0]
        pattern_host = pattern.rsplit(":", 1)[0] if ":" in pattern else pattern
        if lowered == pattern_host:
            return True
        if "*" in pattern_host and fnmatch.fnmatch(lowered, pattern_host):
            return True
    return False


def _default_resolver(host: str) -> list[str]:
    """默认域名解析：``socket.getaddrinfo`` → IP 列表（**非 subprocess**）。"""
    infos = socket.getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


def resolve_all(
    host: str,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> list[str]:
    """解析域名到**全部** IP（原语；解析失败**向上抛出**由调用方裁决）。

    Args:
        host: 目标主机名。
        resolver: 可注入解析器（测试用）；缺省 ``socket.getaddrinfo``。

    Returns:
        IP 字符串列表（可能为空）。
    """
    resolver_fn: Callable[[str], Iterable[str]] = (
        resolver if callable(resolver) else _default_resolver
    )
    return [str(ip) for ip in resolver_fn(host)]


@dataclass(frozen=True)
class EgressDecision:
    """出网决策值对象（``authorize`` / ``authorize_redirect`` 的返回值，**不抛**）。

    Attributes:
        allowed: 是否放行。
        code: 错误码（拒绝时为 ``PERMISSION_DENIED``；放行时为 ``UNKNOWN`` / ``OK`` 语义占位）。
        reason: 人类可读原因（拒绝时说明拒因）。
        host: 目标 host。
        resolved_ip: 放行时**钉定** IP（供后续连接，抵御 rebinding）。
        chain: 已走过的重定向跳（URL 序列）。
    """

    allowed: bool
    code: ErrorCode
    reason: str
    host: str
    resolved_ip: str | None = None
    chain: tuple[str, ...] = ()


@runtime_checkable
class EgressPolicy(Protocol):
    """出网策略接口（**唯一入口**语义；实现落 ``astra_security.egress``）。

    唯一实现＝``astra_security.egress.policy.SecurityEgressPolicy``；本 Protocol 供
    ``astra_tool`` / ``astra_security`` 面向抽象编程（不新增依赖边）。
    """

    def authorize(
        self,
        url: str,
        *,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
    ) -> EgressDecision:
        """校验单个 URL（**不抛**，返回决策）。"""
        ...

    def authorize_redirect(
        self,
        *,
        from_url: str,
        location: str,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
        chain: tuple[str, ...] = (),
    ) -> EgressDecision:
        """校验一次重定向（**不抛**；以 ``location`` 重跑逐跳校验）。"""
        ...

    def enforce(
        self,
        url: str,
        *,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
    ) -> str:
        """强制校验（拒绝即 ``raise DomainError(PERMISSION_DENIED)``；放行返回钉定 IP）。"""
        ...
