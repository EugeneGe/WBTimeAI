"""ExtensionPoint ② ``policy_engine``（全局策略引擎）——签名冻结（W1b 裁定 §1.3②）。

与 ``astra_tool.permission_checker`` 的 tool 级 PDP/PEP **不是同一抽象**（F20）：
本扩展点为 Phase 3 起的**全局策略引擎**挂点（设计 §2.14.1）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import ExtensionContext, PolicyDecision, PolicyExplanation, PolicyRequest

__all__ = ["PolicyEngine", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "policy_engine/v1"


@runtime_checkable
class PolicyEngine(Protocol):
    """全局策略引擎扩展点。"""

    def evaluate(self, request: PolicyRequest, ctx: ExtensionContext) -> PolicyDecision:
        """对请求做出裁决（ALLOW / DENY / APPROVAL）。"""
        ...

    def explain(self, request: PolicyRequest, ctx: ExtensionContext) -> PolicyExplanation:
        """给出裁决的规则级解释（可审计）。"""
        ...
