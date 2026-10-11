"""权限判定链的领域 Protocol 与 DTO（设计 §2.10.1；W3 裁定 §2 / Erratum-C）。

本模块**仅**承载：

- :class:`PermissionChecker` **Protocol**（单一判定链抽象）；
- :class:`PermissionQuery` / :class:`PermissionDecision` **DTO**；
- **资源权限链**的 PEP / PDP 挂点 Protocol（:class:`PolicyEnforcementPoint` /
  :class:`PolicyDecisionPoint`，入参 :class:`PermissionQuery`）与空实现。

🔴 **PEP/PDP 为分层第二挂点**（W3 裁定 §2.4 / Erratum-C）：本模块的 PEP/PDP 与
   ``astra_tool.permission_checker`` 的 PEP/PDP **同名异义、不合并 / 不 re-export /
   不互相继承**（对齐 W1b ``secret_provider`` 同名异义先例）。Phase 1/2 均为**空实现**，
   Phase 3 ``PolicyEngine``（``policy_engine/v1`` ExtensionPoint）可分别实现两处。

🔴 零框架依赖（纯 dataclass / Protocol / typing）——受
   ``test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .value_objects.tool import ToolEffect

__all__ = [
    "PermissionQuery",
    "PermissionDecision",
    "PermissionChecker",
    "PolicyEnforcementPoint",
    "PolicyDecisionPoint",
    "NoopPolicyEnforcementPoint",
    "NoopPolicyDecisionPoint",
]


@dataclass(frozen=True)
class PermissionQuery:
    """一次能力 / 资源权限判定请求（PEP / PDP 与 ``check_capability`` 的入参）。

    Attributes:
        tenant_id: 租户标识（硬隔离，I-1）。
        subject_type: 主体类型（``role`` / ``user`` / ``agent``）。
        subject_id: 主体标识。
        capability: 待判定的 capability（如 ``tool:git.commit`` / ``git.commit``）。
        resource_type: 资源类型（可空；未提供时按 capability 家族推断）。
        resource_id: 资源标识（可空）。
        action: 动作（可空）。
    """

    tenant_id: str
    subject_type: str
    subject_id: str
    capability: str
    resource_type: str | None = None
    resource_id: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class PermissionDecision:
    """能力 / 资源权限判定结果（``check_capability`` 的输出）。

    Attributes:
        allowed: 是否放行。
        effect: 效果字面值（``ALLOW`` / ``DENY``）。
        reason: 人类可读原因（供审计 / 调试）。
        source: 命中的判定来源（如 ``resource_permission`` / ``default_deny`` / ``scope``）。
    """

    allowed: bool
    effect: str
    reason: str = ""
    source: str | None = None

    @classmethod
    def allow(cls, *, reason: str = "", source: str | None = None) -> PermissionDecision:
        """构造 ``ALLOW`` 决策。"""
        return cls(allowed=True, effect=ToolEffect.ALLOW.value, reason=reason, source=source)

    @classmethod
    def deny(cls, *, reason: str = "", source: str | None = None) -> PermissionDecision:
        """构造 ``DENY`` 决策。"""
        return cls(allowed=False, effect=ToolEffect.DENY.value, reason=reason, source=source)


@runtime_checkable
class PermissionChecker(Protocol):
    """单一判定链抽象（实现落 ``astra_security.permission.ResourcePermissionChecker``）。

    签名**冻结**（W3 裁定 §2.2）：结构化契合 Runtime ``ToolExecutor.execute`` 调用点
    （``checker.check(ctx, tool, action)``）。
    """

    def check(self, ctx: object, tool: object, action: str) -> ToolEffect:
        """执行前逐次校验：① resource_permission → ② permission_scope（只收窄）→ ③ 默认拒绝。"""
        ...

    def is_allowed(self, ctx: object, tool: object, action: str) -> bool:
        """便捷判断：仅 ``ALLOW`` 视为放行。"""
        ...

    def check_capability(self, query: PermissionQuery) -> PermissionDecision:
        """判定某 capability 是否被授予（后端下发输入源）。"""
        ...


@runtime_checkable
class PolicyEnforcementPoint(Protocol):
    """资源权限链策略执行点（PEP；入参 :class:`PermissionQuery`）。

    Phase 1/2 为空实现；Phase 3 ``PolicyEngine`` 选择性接入（**位于判定链 ④**）。
    """

    def enforce(self, *, query: PermissionQuery, effect: str) -> str:
        """对判定结果做最终强制（返回改写后的 ``ToolEffect`` 字面值）。"""
        ...


@runtime_checkable
class PolicyDecisionPoint(Protocol):
    """资源权限链策略决策点（PDP；入参 :class:`PermissionQuery`）。

    返回 ``None`` 表示「不介入」（视为弃权票）；Phase 1/2 恒为 ``None``。
    """

    def decide(self, *, query: PermissionQuery) -> str | None:
        """返回决策（``ToolEffect`` 字面值）或 ``None``（不介入）。"""
        ...


class NoopPolicyEnforcementPoint:
    """PEP 空实现：原样返回判定结果。"""

    def enforce(self, *, query: PermissionQuery, effect: str) -> str:
        """原样返回 ``effect``。"""
        return effect


class NoopPolicyDecisionPoint:
    """PDP 空实现：恒不介入（返回 ``None``）。"""

    def decide(self, *, query: PermissionQuery) -> str | None:
        """恒返回 ``None``。"""
        return None
