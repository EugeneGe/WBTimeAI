"""权限**单一判定链**集成测试（W3 / T2-13；验收 ``I-P2-14``）。

经真实 SQL 仓储（``SqlResourcePermissionRepository``）+ 注入 ``SqlAuditRepository`` 验证：

- ① ``resource_permission``（主体级）→ ② ``permission_scope``（只收窄）→ ③ 默认拒绝；
- 显式 DENY 优先于 ALLOW；类型级 / 实例级叠加；
- **类型级（``resource_id IS NULL``）upsert 去重**（应用层 6 键幂等，W3 裁定 §1.1）；
- 实例级越权 capability → 无效 + 落 ``audit_log``（``permission.scope_escalation``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_database import SqlAuditRepository, SqlResourcePermissionRepository
from astra_domain import PermissionQuery, ResourcePermission, ToolEffect
from astra_identity import build_identity_services
from astra_security import ResourcePermissionChecker

_TENANT_SLUG = "default"
_AGENT = "agent-1"
_TOOL_ID = "tool-1"


@dataclass
class _Scope:
    capabilities: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class _Ctx:
    tenant_id: str
    agent_id: str | None = _AGENT
    permission_scope: Any = None


class _Meta:
    name = "shell"


class _Spec:
    metadata = _Meta()
    name = "shell"


class _Tool:
    spec = _Spec()
    tool_id = _TOOL_ID


def _tenant_id(session_factory: object) -> str:
    """确保默认租户存在并返回其 id。"""
    identity = build_identity_services(session_factory)  # type: ignore[arg-type]
    return identity.tenants.ensure_default().id


def _checker(session_factory: object, *, audit: Any = None) -> ResourcePermissionChecker:
    """构造注入 SQL 仓储的判定链。"""
    return ResourcePermissionChecker(
        repository=SqlResourcePermissionRepository(session_factory),  # type: ignore[arg-type]
        audit=audit,
    )


def _upsert(
    session_factory: object,
    tenant_id: str,
    *,
    resource_id: str | None,
    action: str = "EXECUTE",
    effect: str = "ALLOW",
    scope: dict[str, Any] | None = None,
) -> ResourcePermission:
    """经 SQL 仓储 upsert 一条规则。"""
    repository = SqlResourcePermissionRepository(session_factory)  # type: ignore[arg-type]
    return repository.upsert(
        ResourcePermission(
            tenant_id=tenant_id,
            subject_type="agent",
            subject_id=_AGENT,
            resource_type="TOOL",
            resource_id=resource_id,
            action=action,
            effect=effect,
            scope=scope or {},
        )
    )


def test_single_chain_default_deny(session_factory: object) -> None:
    """③ 无规则 → 默认拒绝。"""
    tenant_id = _tenant_id(session_factory)
    checker = _checker(session_factory)
    assert checker.check(_Ctx(tenant_id=tenant_id), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_single_chain_type_level_allow(session_factory: object) -> None:
    """① 类型级 ALLOW → 放行。"""
    tenant_id = _tenant_id(session_factory)
    _upsert(session_factory, tenant_id, resource_id=None)
    checker = _checker(session_factory)
    assert checker.check(_Ctx(tenant_id=tenant_id), _Tool(), "EXECUTE") is ToolEffect.ALLOW


def test_single_chain_deny_priority_over_allow(session_factory: object) -> None:
    """① 类型级 ALLOW + 实例级 DENY → **DENY 优先**。"""
    tenant_id = _tenant_id(session_factory)
    _upsert(session_factory, tenant_id, resource_id=None, effect="ALLOW")
    _upsert(session_factory, tenant_id, resource_id=_TOOL_ID, effect="DENY")
    checker = _checker(session_factory)
    assert checker.check(_Ctx(tenant_id=tenant_id), _Tool(), "EXECUTE") is ToolEffect.DENY


def test_single_chain_type_level_upsert_dedupes(session_factory: object) -> None:
    """类型级（``resource_id IS NULL``）upsert 幂等去重（应用层 6 键）。"""
    tenant_id = _tenant_id(session_factory)
    _upsert(session_factory, tenant_id, resource_id=None, effect="ALLOW")
    _upsert(session_factory, tenant_id, resource_id=None, effect="DENY")
    repository = SqlResourcePermissionRepository(session_factory)  # type: ignore[arg-type]
    rules = repository.list_for_subject(tenant_id, "agent", _AGENT)
    assert len(rules) == 1
    assert rules[0].effect == "DENY"


def test_single_chain_escalation_denied_and_audited(session_factory: object) -> None:
    """② 实例级越权 capability → 无效 + 落 ``audit_log``。"""
    tenant_id = _tenant_id(session_factory)
    _upsert(session_factory, tenant_id, resource_id=None, scope={"capabilities": ["git.commit"]})
    audit = SqlAuditRepository(session_factory)  # type: ignore[arg-type]
    checker = _checker(session_factory, audit=audit)
    ctx = _Ctx(
        tenant_id=tenant_id,
        permission_scope=_Scope(capabilities=["git.commit", "db.drop"]),
    )
    assert checker.check(ctx, _Tool(), "EXECUTE") is ToolEffect.DENY
    records = audit.list_by_tenant(tenant_id)
    assert any(r.action == "permission.scope_escalation" for r in records)


def test_check_capability_from_resource_permission(session_factory: object) -> None:
    """``check_capability``：主体级 scope 授予 capability → 放行。"""
    tenant_id = _tenant_id(session_factory)
    _upsert(session_factory, tenant_id, resource_id=None, scope={"capabilities": ["git.commit"]})
    checker = _checker(session_factory)
    decision = checker.check_capability(
        PermissionQuery(
            tenant_id=tenant_id,
            subject_type="agent",
            subject_id=_AGENT,
            capability="git.commit",
        )
    )
    assert decision.allowed is True
