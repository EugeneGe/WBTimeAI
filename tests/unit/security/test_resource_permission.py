"""权限**单一判定链**单元测试（W3 / T2-13；验收 ``I-P2-14``）。

覆盖（纯逻辑，注入假仓储）：

- 链顺序：① resource_permission → ② permission_scope（只收窄）→ ③ 默认拒绝；
- **显式 DENY 优先于 ALLOW**；
- 无权限的 ``EXECUTE`` 被拒（默认拒绝）；
- 实例级 ``permission_scope`` **只收窄不放开**（越权声明无效 + 记审计）；
- ``check_capability`` 主体级 capability 判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_domain import (
    PermissionQuery,
    ResourcePermission,
    ToolEffect,
)
from astra_security import ResourcePermissionChecker

_TENANT = "tenant-1"
_AGENT = "agent-1"
_TOOL_ID = "tool-1"


class _FakeRepository:
    """内存假仓储（仅实现判定链所需 ``list_for_subject``）。"""

    def __init__(self, rules: list[ResourcePermission]) -> None:
        self._rules = list(rules)

    def list_for_subject(
        self, tenant_id: str, subject_type: str, subject_id: str
    ) -> list[ResourcePermission]:
        return [
            rule
            for rule in self._rules
            if rule.tenant_id == tenant_id
            and rule.subject_type == subject_type
            and rule.subject_id == subject_id
        ]

    # -- 未使用但满足 Protocol 形态 ----------------------------------------
    def get(self, permission_id: str) -> ResourcePermission | None:  # noqa: D102
        return None

    def add(self, permission: ResourcePermission) -> ResourcePermission:  # noqa: D102
        self._rules.append(permission)
        return permission

    def upsert(self, permission: ResourcePermission) -> ResourcePermission:  # noqa: D102
        return self.add(permission)

    def list_by_resource(
        self, tenant_id: str, resource_type: str, resource_id: str
    ) -> list[ResourcePermission]:  # noqa: D102
        return [
            rule
            for rule in self._rules
            if rule.tenant_id == tenant_id
            and rule.resource_type == resource_type
            and rule.resource_id == resource_id
        ]

    def delete(self, permission_id: str) -> None:  # noqa: D102
        return None


class _RecordingAudit:
    """记录审计写入的假审计仓储。"""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def add(self, record: Any) -> Any:  # noqa: D102
        self.records.append(record)
        return record

    def exists_request_id(self, request_id: str) -> bool:  # noqa: D102
        return False

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[Any]:  # noqa: D102
        return []


@dataclass
class _Scope:
    """轻量 scope 承载（鸭子类型；避免依赖 T2-14 的 ``PermissionScope.capabilities``）。"""

    capabilities: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class _Ctx:
    """最小执行上下文。"""

    tenant_id: str = _TENANT
    agent_id: str | None = _AGENT
    permission_scope: Any = None


class _Meta:
    """工具元数据。"""

    name = "shell"


class _Spec:
    """工具规格。"""

    metadata = _Meta()
    name = "shell"


class _Tool:
    """最小 Tool 形态。"""

    spec = _Spec()
    tool_id = _TOOL_ID


def _rule(
    *,
    resource_id: str | None,
    action: str = "EXECUTE",
    effect: str = "ALLOW",
    scope: dict[str, Any] | None = None,
) -> ResourcePermission:
    """构造一条资源权限规则。"""
    return ResourcePermission(
        tenant_id=_TENANT,
        subject_type="agent",
        subject_id=_AGENT,
        resource_type="TOOL",
        resource_id=resource_id,
        action=action,
        effect=effect,
        scope=scope or {},
    )


def _checker(rules: list[ResourcePermission], audit: Any = None) -> ResourcePermissionChecker:
    """构造注入假仓储的判定链。"""
    return ResourcePermissionChecker(repository=_FakeRepository(rules), audit=audit)


def test_no_rule_is_default_deny() -> None:
    """③ 默认拒绝：无任何规则 → ``DENY``。"""
    assert _checker([]).check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_missing_subject_is_default_deny() -> None:
    """无主体（缺 ``agent_id``）→ ③ 默认拒绝。"""
    checker = _checker([_rule(resource_id=None)])
    assert checker.check(_Ctx(agent_id=None), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_type_level_allow_grants() -> None:
    """① 类型级（``resource_id IS NULL``）ALLOW → 放行。"""
    checker = _checker([_rule(resource_id=None)])
    assert checker.check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.ALLOW
    assert checker.is_allowed(_Ctx(), _Tool(), "EXECUTE") is True


def test_instance_level_allow_grants() -> None:
    """① 实例级 ALLOW（``resource_id == tool_id``）→ 放行。"""
    checker = _checker([_rule(resource_id=_TOOL_ID)])
    assert checker.check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.ALLOW


def test_instance_rule_for_other_tool_does_not_grant() -> None:
    """① 实例级规则针对**其它** Tool → 不匹配 → 默认拒绝。"""
    checker = _checker([_rule(resource_id="other-tool")])
    assert checker.check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_explicit_deny_wins_over_allow() -> None:
    """① **显式 DENY 优先于 ALLOW**。"""
    checker = _checker([_rule(resource_id=None), _rule(resource_id=None, effect="DENY")])
    assert checker.check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_action_mismatch_is_denied() -> None:
    """① action 不匹配（规则为 VIEW，请求 EXECUTE）→ 默认拒绝。"""
    checker = _checker([_rule(resource_id=None, action="VIEW")])
    assert checker.check(_Ctx(), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_instance_scope_deny_narrows() -> None:
    """② ``scope.deny`` 命中动作 → 拒绝（只收窄）。"""
    checker = _checker([_rule(resource_id=None)])
    ctx = _Ctx(permission_scope=_Scope(deny=["EXECUTE"]))
    assert checker.check(ctx, _Tool(), "EXECUTE") is ToolEffect.DENY


def test_instance_scope_capability_subset_allows() -> None:
    """② 实例级 capability ⊆ 主体级授予 → 放行（合法收窄）。"""
    checker = _checker(
        [_rule(resource_id=None, scope={"capabilities": ["git.commit", "git.push"]})]
    )
    ctx = _Ctx(permission_scope=_Scope(capabilities=["git.commit"]))
    assert checker.check(ctx, _Tool(), "EXECUTE") is ToolEffect.ALLOW


def test_instance_scope_capability_escalation_denied_and_audited() -> None:
    """② 实例级声明的 capability **超出**主体级 → 无效（不放行）+ **记审计**。"""
    audit = _RecordingAudit()
    checker = _checker(
        [_rule(resource_id=None, scope={"capabilities": ["git.commit"]})], audit=audit
    )
    ctx = _Ctx(permission_scope=_Scope(capabilities=["git.commit", "git.force_push"]))
    assert checker.check(ctx, _Tool(), "EXECUTE") is ToolEffect.DENY
    assert audit.records, "越权声明应记审计"
    assert audit.records[0].action == "permission.scope_escalation"
    assert "git.force_push" in audit.records[0].metadata["capabilities"]


def test_check_capability_subject_allow() -> None:
    """``check_capability``：主体级 ALLOW scope 含 capability → 放行。"""
    checker = _checker([_rule(resource_id=None, scope={"capabilities": ["git.commit"]})])
    decision = checker.check_capability(
        PermissionQuery(
            tenant_id=_TENANT,
            subject_type="agent",
            subject_id=_AGENT,
            capability="git.commit",
        )
    )
    assert decision.allowed is True
    assert decision.effect == ToolEffect.ALLOW.value


def test_check_capability_default_deny() -> None:
    """``check_capability``：无授权 → 默认拒绝。"""
    checker = _checker([_rule(resource_id=None, scope={"capabilities": ["git.commit"]})])
    decision = checker.check_capability(
        PermissionQuery(
            tenant_id=_TENANT,
            subject_type="agent",
            subject_id=_AGENT,
            capability="db.drop",
        )
    )
    assert decision.allowed is False
