"""``astra_security.egress``——出网策略（**唯一入口**；W1 / T2-03；设计 §2.18）。

- :class:`SecurityEgressPolicy`：**唯一入口** 具体实现（配置驱动 allow/deny + 重定向逐跳 +
  超时 + 审计）；
- :class:`~astra_domain.ports.egress.EgressPolicy` / ``EgressDecision``：面向抽象
  （原语下沉 ``astra_domain``）；
- :mod:`.deny_ranges` / :mod:`.dns`：**再导出 / 包装** ``astra_domain`` 原语（单一来源）；
- :data:`EGRESS_WIRING_POINTS`：四个出网面接线点（``I-P2-32`` / DoD ``D14``）。

🔴 **单一来源**：拒段表 / IP 判定 / DNS 解析**不重复维护**，全部复用
   ``astra_domain.ports.egress``（W1 裁定 §4.1 / §4.2）。
"""

from __future__ import annotations

from astra_domain.ports.egress import (
    ALLOWED_SCHEMES,
    DENY_RANGES,
    METADATA_IPS,
    EgressDecision,
    EgressPolicy,
    host_matches,
    is_blocked_ip,
    is_metadata_ip,
)

from .dns import resolve_all, resolve_and_validate
from .policy import EGRESS_ACTION, EGRESS_WIRING_POINTS, EgressWiringPoint, SecurityEgressPolicy

__all__ = [
    # 唯一入口实现
    "SecurityEgressPolicy",
    "EGRESS_ACTION",
    "EGRESS_WIRING_POINTS",
    "EgressWiringPoint",
    # 面向抽象（原语）
    "EgressPolicy",
    "EgressDecision",
    # 再导出 / 包装 domain 原语
    "DENY_RANGES",
    "METADATA_IPS",
    "ALLOWED_SCHEMES",
    "is_metadata_ip",
    "is_blocked_ip",
    "host_matches",
    "resolve_all",
    "resolve_and_validate",
]
