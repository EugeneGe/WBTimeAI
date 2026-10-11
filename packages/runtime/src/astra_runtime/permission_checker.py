"""Runtime 侧 ``RuntimePermissionChecker``（薄封装 + 调用点；W5 架构裁定 Q4）。

**复用** :class:`astra_tool.permission_checker.PermissionChecker`（**不复制逻辑**）；
PEP（RP-06）/ PDP（RP-07）调用点固定在 ``astra_tool.PermissionChecker`` 内部（总纲 §12.3），
本薄封装只做**委托**。
"""

from __future__ import annotations

from typing import Any

from astra_domain import ToolEffect
from astra_tool import PermissionChecker

__all__ = ["RuntimePermissionChecker"]


class RuntimePermissionChecker:
    """Runtime 侧权限校验薄封装（委托 ``astra_tool.PermissionChecker``）。"""

    def __init__(self, delegate: PermissionChecker | None = None) -> None:
        self._delegate = delegate or PermissionChecker()

    @property
    def delegate(self) -> PermissionChecker:
        """底层 ``astra_tool`` 校验器（供装配 / 断言）。"""
        return self._delegate

    @property
    def policy_enforcement_point(self):  # noqa: ANN201 - 透传 PEP 挂点
        """透传 PEP（RP-06）挂点。"""
        return self._delegate.policy_enforcement_point

    @property
    def policy_decision_point(self):  # noqa: ANN201 - 透传 PDP 挂点
        """透传 PDP（RP-07）挂点。"""
        return self._delegate.policy_decision_point

    def check(self, ctx: Any, tool: Any, action: str) -> ToolEffect:
        """执行前逐次校验（委托 ``astra_tool.PermissionChecker.check``）。"""
        return self._delegate.check(ctx, tool, action)

    def is_allowed(self, ctx: Any, tool: Any, action: str) -> bool:
        """便捷判断：仅 ``ALLOW`` 视为放行。"""
        return self._delegate.is_allowed(ctx, tool, action)
