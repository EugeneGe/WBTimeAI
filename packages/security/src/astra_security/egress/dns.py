"""出网 **DNS 校验**（W1 / T2-03；设计 §2.18）——包装 ``astra_domain`` 原语。

职责：**全量 IP 校验** + **二次解析防 DNS rebinding** + **连接 IP 一致性**
（首解析与二次解析均须为公网；任一命中拒段即拒）。

🔴 **单一来源**：解析与拒段判定复用 :mod:`astra_domain.ports.egress` 原语，本模块**不**
   重复维护拒段表（W1 裁定 §4.2）。
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterable

from astra_domain.ports.egress import is_blocked_ip
from astra_domain.ports.egress import resolve_all as _resolve_all

__all__ = ["resolve_all", "resolve_and_validate"]


def resolve_all(
    host: str,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> list[str]:
    """解析域名到**全部** IP（薄包装 ``astra_domain`` 原语）。"""
    return _resolve_all(host, resolver=resolver)


def resolve_and_validate(
    host: str,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
    deny_private: bool = True,
) -> tuple[list[str], str | None]:
    """解析域名并**全量校验**，抵御 DNS rebinding；返回钉定 IP 列表与违规项。

    Args:
        host: 目标主机名。
        resolver: 可注入解析器（测试用）。
        deny_private: 是否执行拒段校验（``False`` 时仅做一致性二次解析）。

    Returns:
        ``(ips, violation)``：``violation`` 为 ``None`` 表示通过；否则为拒因字符串
        （命中拒段的 IP / 解析失败说明）。连接应使用 ``ips[0]``（**钉定 IP**）。
    """
    try:
        first = resolve_all(host, resolver=resolver)
    except (socket.gaierror, OSError, ValueError) as exc:
        return [], f"域名解析失败：{exc}"
    if not first:
        return [], "域名无解析结果"

    if deny_private:
        for ip in first:
            if is_blocked_ip(ip):
                return first, f"解析到禁止访问的地址：{ip}"
        try:
            second = resolve_all(host, resolver=resolver)
        except (socket.gaierror, OSError, ValueError) as exc:
            return first, f"二次解析失败（疑似 DNS rebinding）：{exc}"
        for ip in second:
            if is_blocked_ip(ip):
                return first, f"检测到 DNS rebinding：{ip}"
    return first, None
