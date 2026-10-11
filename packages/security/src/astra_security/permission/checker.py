"""权限**单一判定链**实现（设计 §2.10.1；W3 裁定 §2 / Erratum-C）。

:class:`ResourcePermissionChecker` 是 **运行期唯一** 的权限判定源（W3 裁定 §2.2）：

```
调用点（Runtime ToolExecutor，每 tool call 一次）
  └─ ResourcePermissionChecker.check(ctx, tool, action)
       ① 主体级：resource_permission(subject × resource_type × resource_id? × action)
             · 显式 DENY → 立即拒绝（deny 优先于 allow）
             · 无显式 ALLOW → 视为未授权 → 直接 ③（默认拒绝）
             · 显式 ALLOW → 进入 ②
       ② 实例级：agent_tool.permission_scope —— ★ 只收窄、不放开
             · scope.deny 命中 → 拒绝
             · scope 声明主体级未授予的 capability → 无效（不放行）+ 记审计
       ③ 默认拒绝（DEFAULT_DENY）
       ④ 资源权限链 PEP 挂点（enforce）→ PDP 挂点（decide）—— Phase 1/2 空实现
```

🔴 本文件是判定链的**唯一实现**；``astra_tool.PermissionChecker`` **不再作为运行期判定源**
   （降为默认策略模板评估器）。签名**冻结**（结构化契合 runtime 调用点，ToolExecutor /
   AgentRuntime 签名零改）。

🔴 ``astra_security`` **不依赖** ``astra_tool``；本实现经 DI 注入 ``ResourcePermissionRepository``
   使用权限数据（组合根装配）。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from astra_domain import (
    AUDIT_OUTCOME_DENIED,
    AuditLog,
    AuditRepository,
    NoopPolicyDecisionPoint,
    NoopPolicyEnforcementPoint,
    PermissionDecision,
    PermissionQuery,
    PolicyDecisionPoint,
    PolicyEnforcementPoint,
    ResourcePermission,
    ResourcePermissionRepository,
    ToolAction,
    ToolEffect,
)

from .capability import (
    capability_is_escalation,
    denied_capabilities,
    granted_capabilities,
)

__all__ = ["ResourcePermissionChecker"]

#: 资源类型（Tool 权限）。
_RESOURCE_TYPE_TOOL = "TOOL"

#: 主体类型（Agent）。
_SUBJECT_TYPE_AGENT = "agent"


def _tool_name(tool: Any) -> str:
    """从 Tool 对象抽取工具名（兼容 ``spec.metadata.name`` / ``spec.name``）。"""
    spec = getattr(tool, "spec", None)
    metadata = getattr(spec, "metadata", None)
    return str(getattr(metadata, "name", None) or getattr(spec, "name", None) or "")


def _tool_id(tool: Any) -> str | None:
    """从 Tool 对象抽取工具标识（可空）。"""
    value = getattr(tool, "tool_id", None)
    return str(value) if value else None


class ResourcePermissionChecker:
    """资源权限**单一判定链**（运行期唯一判定源）。

    Args:
        repository: 资源权限仓储（域 Protocol，DI 注入）。
        pep: 资源权限链策略执行点（默认 :class:`NoopPolicyEnforcementPoint`）。
        pdp: 资源权限链策略决策点（默认 :class:`NoopPolicyDecisionPoint`）。
        audit: 审计仓储（可空）；记录「实例级越权声明」审计。
    """

    def __init__(
        self,
        *,
        repository: ResourcePermissionRepository,
        pep: PolicyEnforcementPoint | None = None,
        pdp: PolicyDecisionPoint | None = None,
        audit: AuditRepository | None = None,
    ) -> None:
        self._repository = repository
        self._pep: PolicyEnforcementPoint = pep or NoopPolicyEnforcementPoint()
        self._pdp: PolicyDecisionPoint = pdp or NoopPolicyDecisionPoint()
        self._audit = audit

    @property
    def policy_enforcement_point(self) -> PolicyEnforcementPoint:
        """暴露资源权限链 PEP 挂点（供装配 / 断言）。"""
        return self._pep

    @property
    def policy_decision_point(self) -> PolicyDecisionPoint:
        """暴露资源权限链 PDP 挂点（供装配 / 断言）。"""
        return self._pdp

    # -- 判定链 -------------------------------------------------------------

    def check(self, ctx: Any, tool: Any, action: str) -> ToolEffect:
        """执行前逐次校验（单一判定链 ①②③④）。"""
        tool_name = _tool_name(tool)
        tool_id = _tool_id(tool)
        action_value = ToolAction.ensure(action).value
        tenant_id = str(getattr(ctx, "tenant_id", "") or "")
        agent_id = getattr(ctx, "agent_id", None)
        subject_id = str(agent_id) if agent_id else ""

        query = PermissionQuery(
            tenant_id=tenant_id,
            subject_type=_SUBJECT_TYPE_AGENT,
            subject_id=subject_id,
            capability=f"tool:{tool_name}" if tool_name else "tool",
            resource_type=_RESOURCE_TYPE_TOOL,
            resource_id=tool_id,
            action=action_value,
        )

        # 无主体（缺 agent_id）→ 直接 ③ 默认拒绝。
        if not subject_id:
            return self._finalize(query, ToolEffect.DENY)

        rules = self._repository.list_for_subject(tenant_id, _SUBJECT_TYPE_AGENT, subject_id)

        # ① 主体级：筛选 resource_type/action/（实例级或类型级）匹配的规则。
        matched = [
            rule
            for rule in rules
            if rule.resource_type == _RESOURCE_TYPE_TOOL
            and rule.action == action_value
            and (rule.resource_id is None or rule.resource_id == tool_id)
        ]
        denied = [rule for rule in matched if rule.effect == ToolEffect.DENY.value]
        allowed = [rule for rule in matched if rule.effect == ToolEffect.ALLOW.value]

        # 显式 DENY 优先于 ALLOW。
        if denied:
            return self._finalize(query, ToolEffect.DENY)
        # 无显式 ALLOW → ③ 默认拒绝。
        if not allowed:
            return self._finalize(query, ToolEffect.DENY)

        # ② 实例级 permission_scope —— 只收窄、不放开。
        narrowed = self._apply_instance_scope(ctx, query, matched_allowed=allowed)
        return self._finalize(query, narrowed)

    def is_allowed(self, ctx: Any, tool: Any, action: str) -> bool:
        """便捷判断：仅 ``ALLOW`` 视为放行。"""
        return self.check(ctx, tool, action) is ToolEffect.ALLOW

    def check_capability(self, query: PermissionQuery) -> PermissionDecision:
        """判定某 capability 是否被授予（后端下发的 ``can()`` 输入源）。"""
        rules = self._repository.list_for_subject(
            query.tenant_id, query.subject_type, query.subject_id
        )
        granted_patterns: list[str] = []
        for rule in rules:
            caps = granted_capabilities(rule.scope)
            deny_caps = denied_capabilities(rule.scope)
            if _capability_matches(query.capability, deny_caps):
                return PermissionDecision.deny(
                    reason="显式 DENY（capability）", source="resource_permission"
                )
            if rule.effect == ToolEffect.ALLOW.value and _capability_matches(
                query.capability, caps
            ):
                granted_patterns.append(query.capability)
        if granted_patterns:
            return PermissionDecision.allow(
                reason="主体级 ALLOW（capability）", source="resource_permission"
            )
        return PermissionDecision.deny(reason="默认拒绝（deny-by-default）", source="default_deny")

    # -- 内部 ---------------------------------------------------------------

    def _apply_instance_scope(
        self, ctx: Any, query: PermissionQuery, *, matched_allowed: list[ResourcePermission]
    ) -> ToolEffect:
        """② 实例级收窄：``scope.deny`` 命中 → 拒绝；越权 capability → 无效 + 审计。"""
        scope = getattr(ctx, "permission_scope", None)
        if scope is None:
            return ToolEffect.ALLOW

        tool_name = _tool_name_from_capability(query.capability)
        deny_list = denied_capabilities(scope)
        action_value = query.action or ""
        if action_value in deny_list or (tool_name and tool_name in deny_list):
            return ToolEffect.DENY

        declared = granted_capabilities(scope)
        if declared:
            granted: list[str] = []
            for rule in matched_allowed:
                granted.extend(granted_capabilities(rule.scope))
            escalations = [
                cap for cap in declared if capability_is_escalation(cap, granted=granted)
            ]
            if escalations:
                self._record_escalation(query, escalations)
                return ToolEffect.DENY
        return ToolEffect.ALLOW

    def _finalize(self, query: PermissionQuery, effect: ToolEffect) -> ToolEffect:
        """④ 资源权限链 PEP（enforce）→ PDP（decide）。"""
        enforced = ToolEffect.ensure(self._pep.enforce(query=query, effect=effect.value))
        decision = self._pdp.decide(query=query)
        if decision is not None:
            return ToolEffect.ensure(decision)
        return enforced

    def _record_escalation(self, query: PermissionQuery, escalations: list[str]) -> None:
        """记录「实例级越权声明」审计（失败不阻断判定）。"""
        if self._audit is None:
            return
        try:
            self._audit.add(
                AuditLog(
                    tenant_id=query.tenant_id,
                    action="permission.scope_escalation",
                    request_id=generate_id(),
                    resource_type=query.resource_type,
                    resource_id=query.resource_id,
                    outcome=AUDIT_OUTCOME_DENIED,
                    metadata={
                        "subject_type": query.subject_type,
                        "subject_id": query.subject_id,
                        "capabilities": list(escalations),
                    },
                )
            )
        except Exception:  # noqa: BLE001 - 审计失败不得阻断权限判定
            pass


def _capability_matches(capability: str, patterns: list[str]) -> bool:
    """轻量包装（避免在模块内重复 import）。"""
    from .capability import capability_matches_any

    return capability_matches_any(capability, patterns)


def _tool_name_from_capability(capability: str) -> str:
    """从 ``tool:<name>`` capability 反解工具名（无前缀时原样返回）。"""
    prefix = "tool:"
    if capability.startswith(prefix):
        return capability[len(prefix) :]
    return ""
