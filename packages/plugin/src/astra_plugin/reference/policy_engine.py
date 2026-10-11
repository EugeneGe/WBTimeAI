"""``policy_engine`` 参考实现：:class:`NoopPolicyEngine`（默认放行）。

🔴 **NON-SECURE**：默认全放行——**仅用于契约演示**；真实策略引擎归 Phase 3–4。
"""

from __future__ import annotations

from astra_domain import (
    ExtensionContext,
    PolicyDecision,
    PolicyEffect,
    PolicyExplanation,
    PolicyRequest,
)

__all__ = ["NoopPolicyEngine"]


class NoopPolicyEngine:
    """默认放行的策略引擎（**NON-SECURE / 仅契约演示**）。"""

    def evaluate(self, request: PolicyRequest, ctx: ExtensionContext) -> PolicyDecision:
        """恒返回 ``ALLOW``。"""
        return PolicyDecision(effect=PolicyEffect.ALLOW, matched_policy_id=None, reason="noop")

    def explain(self, request: PolicyRequest, ctx: ExtensionContext) -> PolicyExplanation:
        """返回对应 ``ALLOW`` 的解释。"""
        return PolicyExplanation(
            decision=self.evaluate(request, ctx),
            matched_rules=(),
            notes="noop policy engine（默认放行）",
        )
