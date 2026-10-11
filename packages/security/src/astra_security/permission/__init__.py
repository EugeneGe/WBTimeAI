"""``astra_security.permission``：权限单一判定链（W3 / T2-13 · 裁定 §2）。

- :class:`ResourcePermissionChecker`：**运行期唯一**权限判定源（实现于 ``checker.py``）；
- ``capability.py``：scope / capability 匹配原语（T2-13 建立，T2-14 扩充）。

🔴 本子包与 ``astra_tool.permission_checker`` 的 PEP/PDP **分层两挂点、禁 re-export**
   （W3 裁定 §2.4 / Erratum-C）；``astra_security`` **不依赖** ``astra_tool``。
"""

from __future__ import annotations

from .approval import ApprovalService
from .capability import (
    WILDCARD,
    capability_is_escalation,
    capability_matches_any,
    denied_capabilities,
    effective_capabilities,
    granted_capabilities,
    match_capability,
    matches_capability_pattern,
)
from .checker import ResourcePermissionChecker

__all__ = [
    "ResourcePermissionChecker",
    # 基础审批机制（W4 / T2-26，零迁移；结构化满足 astra_domain.ApprovalGateway）
    "ApprovalService",
    "WILDCARD",
    "matches_capability_pattern",
    "capability_matches_any",
    "granted_capabilities",
    "denied_capabilities",
    "capability_is_escalation",
    "match_capability",
    "effective_capabilities",
]
