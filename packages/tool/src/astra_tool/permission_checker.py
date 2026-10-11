"""``PermissionChecker``（纯逻辑）+ PEP / PDP 挂点（设计 §2.5.3 / 总纲 §12 RP-06 / RP-07）。

**核心原则 ⑩**：执行必过权限，且**执行前逐次校验**。

- :class:`PermissionChecker`：纯逻辑（零 ORM、零 ``sqlalchemy``）；授权数据经 **DI 注入**
  （已解析的 ``ToolPermission`` 集合 + ``tool_id → name`` 映射）；**deny-by-default**；
- :class:`PolicyEnforcementPoint`（PEP，RP-06）：**挂点 Protocol + 空实现**
  （总纲 §12.3：调用点固定在 ``PermissionChecker`` 内部）；
- :class:`PolicyDecisionPoint`（PDP，RP-07）：**挂点 Protocol**；Phase 1 不介入
  （决策返回 ``None`` 即不改变结果；``APPROVAL`` 为 Phase 3 预留）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from astra_domain import ToolAction, ToolEffect, ToolPermission

from .base import Tool

__all__ = [
    "PermissionRequest",
    "PolicyEnforcementPoint",
    "PolicyDecisionPoint",
    "NoopPolicyEnforcementPoint",
    "NoopPolicyDecisionPoint",
    "PermissionChecker",
]


@dataclass(frozen=True)
class PermissionRequest:
    """一次权限判定请求（PEP / PDP 的入参）。

    Attributes:
        tool_name: 工具名。
        action: 动作（``ToolAction`` 字面值）。
        effect: 判定前（或被 PEP 改写后）的效果。
        tenant_id / workspace_id / run_id / agent_id: 执行归属。
        scope: 该 Agent 对该工具的权限 scope（JSON 结构）。
    """

    tool_name: str
    action: str
    effect: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    run_id: str | None = None
    agent_id: str | None = None
    scope: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class PolicyEnforcementPoint(Protocol):
    """策略执行点（PEP，总纲 §12 RP-06）。

    强制以**同一挂点**统一改写决策（审计 / 强制约束）；Phase 1 为空实现。
    """

    def enforce(self, *, request: PermissionRequest) -> str:
        """对判定结果做最终强制（返回改写后的 ``ToolEffect`` 字面值）。"""
        ...


@runtime_checkable
class PolicyDecisionPoint(Protocol):
    """策略决策点（PDP，总纲 §12 RP-07）。

    返回 ``None`` 表示「不介入」（视为废弃票）；Phase 1 恒为 ``None``。
    """

    def decide(self, *, request: PermissionRequest) -> str | None:
        """返回决策（``ToolEffect`` 字面值）或 ``None``（不介入）。"""
        ...


class NoopPolicyEnforcementPoint:
    """PEP 空实现（Phase 1）：原样返回判定结果。"""

    def enforce(self, *, request: PermissionRequest) -> str:
        """原样返回 ``request.effect``。"""
        return request.effect


class NoopPolicyDecisionPoint:
    """PDP 空实现（Phase 1）：恒不介入（返回 ``None``）。"""

    def decide(self, *, request: PermissionRequest) -> str | None:
        """恒返回 ``None``（不改变判定）。"""
        return None


class PermissionChecker:
    """Tool 权限校验器（纯逻辑 + DI）。

    Args:
        permissions: 已解析的 ``ToolPermission`` 集合（DI 注入）。
        tool_id_to_name: ``tool_id → tool.name`` 映射（用于把权限对齐到工具名）。
        pep: 策略执行点（默认 :class:`NoopPolicyEnforcementPoint`）。
        pdp: 策略决策点（默认 :class:`NoopPolicyDecisionPoint`）。
    """

    def __init__(
        self,
        *,
        permissions: Sequence[ToolPermission] | None = None,
        tool_id_to_name: Mapping[str, str] | None = None,
        pep: PolicyEnforcementPoint | None = None,
        pdp: PolicyDecisionPoint | None = None,
    ) -> None:
        name_of = dict(tool_id_to_name or {})
        self._rules: dict[tuple[str, str], str] = {}
        for permission in permissions or ():
            name = name_of.get(permission.tool_id, permission.tool_id)
            self._rules[(name, str(permission.action))] = str(permission.effect)
        self._pep: PolicyEnforcementPoint = pep or NoopPolicyEnforcementPoint()
        self._pdp: PolicyDecisionPoint = pdp or NoopPolicyDecisionPoint()

    @property
    def policy_enforcement_point(self) -> PolicyEnforcementPoint:
        """暴露 PEP 挂点（供装配 / 断言）。"""
        return self._pep

    @property
    def policy_decision_point(self) -> PolicyDecisionPoint:
        """暴露 PDP 挂点（供装配 / 断言）。"""
        return self._pdp

    def check(self, ctx: Any, tool: Tool, action: str) -> ToolEffect:
        """执行前逐次校验（design §2.5.3）。

        Args:
            ctx: 执行上下文（:class:`~astra_tool.context.ToolContext`）。
            tool: 目标工具。
            action: 动作（``ToolAction`` 字面值 / 枚举）。

        Returns:
            判定效果 ``ToolEffect``（``ALLOW`` / ``DENY``；``APPROVAL`` 为预留位）。
        """
        tool_name = tool.spec.metadata.name
        action_value = ToolAction.ensure(action).value

        # deny-by-default：未显式 ALLOW 的动作一律 DENY。
        effect = ToolEffect.ensure(self._rules.get((tool_name, action_value), ToolEffect.DENY))

        scope = getattr(ctx, "permission_scope", None)
        request = PermissionRequest(
            tool_name=tool_name,
            action=action_value,
            effect=effect.value,
            tenant_id=getattr(ctx, "tenant_id", None),
            workspace_id=getattr(ctx, "workspace_id", None),
            run_id=getattr(ctx, "run_id", None),
            agent_id=getattr(ctx, "agent_id", None),
            scope=scope.to_dict() if scope is not None else {},
        )

        # PEP（RP-06）：调用点固定在 PermissionChecker 内部。
        effect = ToolEffect.ensure(self._pep.enforce(request=request))

        # PDP（RP-07）：Phase 1 不介入；非 None 时按决策改写。
        decision = self._pdp.decide(request=request)
        if decision is not None:
            effect = ToolEffect.ensure(decision)

        return effect

    def is_allowed(self, ctx: Any, tool: Tool, action: str) -> bool:
        """便捷判断：仅 ``ALLOW`` 视为放行。"""
        return self.check(ctx, tool, action) is ToolEffect.ALLOW
