"""出网**拒段表**（W1 / T2-03；设计 §2.18）——**再导出** ``astra_domain`` 原语。

🔴 **单一来源、不重复维护**：拒段表与元数据 IP 的唯一数据源是
   :mod:`astra_domain.ports.egress`（``DENY_RANGES`` / ``METADATA_IPS`` / ``is_blocked_ip``）；
   本模块仅**再导出**以便 ``astra_security.egress`` 内部引用（W1 裁定 §4.2）。
"""

from __future__ import annotations

from astra_domain.ports.egress import (
    ALLOWED_SCHEMES,
    DENY_RANGES,
    METADATA_IPS,
    is_blocked_ip,
    is_metadata_ip,
)

__all__ = [
    "DENY_RANGES",
    "METADATA_IPS",
    "ALLOWED_SCHEMES",
    "is_blocked_ip",
    "is_metadata_ip",
]
