"""Tool 领域服务（``PermissionService``，设计 §2.5.3 / Q4）。

**零 ORM、零 ``astra_database``**：经 **依赖注入** 领域 Protocol 仓储
（``astra_domain.ToolRepository`` / ``astra_domain.ToolPermissionRepository`` /
``astra_domain.ResourcePermissionRepository``）读写授权；SQL 实现落
``astra_database.repositories``（W4 架构裁定 Q1 = 方案 B）。

W3 / T2-13 补丁（裁定 §20 Erratum-2 · 运行期判定源统一）：运行期**唯一**判定源
``astra_security.ResourcePermissionChecker`` **只读** ``resource_permission``，故
``/tools/permissions`` 的 ``grant`` / ``revoke`` / ``list`` 必须写 / 读 ``resource_permission``，
否则经该 API 授予的 ``ALLOW`` 永不可达（→ ``tool_call.status=DENIED``）。

本服务支持注入 **可选的** ``ResourcePermissionRepository``：

- **注入时**（组合根接线）：``grant`` 经 ``upsert`` 落 ``resource_permission``
  （``subject_type="agent"`` / ``resource_type="TOOL"`` / ``resource_id=tool_id``）；
  ``list`` / ``get`` / ``revoke`` 亦经 ``resource_permission`` 读写（**API 契约不变**）。
- **未注入时**（默认 / 单测）：保持旧路径（``tool_permission``），其降为**默认策略模板**
  （不作运行期判定源，R2 §2.3）。

``agent_version_id`` 无对应列，不落库（与 ``0010`` 回填口径一致）；语义为「按 Agent 授权」，
与 ``ResourcePermissionChecker`` 的 ``subject_id=agent_id`` 一致（裁定 §20.2 F32）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import (
    TOOL_EFFECT_ALLOW,
    ResourcePermission,
    ResourcePermissionRepository,
    ToolAction,
    ToolEffect,
    ToolPermission,
    ToolPermissionRepository,
    ToolRepository,
)

from ..base import Tool
from ..permission_checker import (
    PermissionChecker,
    PolicyDecisionPoint,
    PolicyEnforcementPoint,
)
from ..registry import ToolRegistry

__all__ = ["PermissionService"]

#: 资源权限主体类型（Agent）——与 ``ResourcePermissionChecker`` 对齐（F32）。
_SUBJECT_TYPE_AGENT = "agent"

#: 资源权限资源类型（Tool）——与 ``ResourcePermissionChecker`` 对齐（F32）。
_RESOURCE_TYPE_TOOL = "TOOL"


def _resource_to_tool_permission(permission: ResourcePermission) -> ToolPermission:
    """``ResourcePermission`` 行 → ``ToolPermission`` 视图（**只读 DTO 映射**）。

    ``agent_version_id`` 无对应列，恒回填 ``None``（与 ``0010`` 回填口径一致）。
    """
    return ToolPermission(
        id=permission.id,
        tenant_id=permission.tenant_id,
        created_at=permission.created_at,
        updated_at=permission.updated_at,
        agent_id=permission.subject_id or None,
        agent_version_id=None,
        tool_id=permission.resource_id or "",
        action=permission.action,
        effect=permission.effect,
        scope=dict(permission.scope or {}),
    )


class PermissionService:
    """Tool 授权读写与判定服务（DI 注入领域 Protocol 仓储）。

    Args:
        tool_repository: 工具目录仓储（域 Protocol）。
        tool_permission_repository: Tool 权限仓储（域 Protocol；默认策略模板，非运行期判定源）。
        resource_permission_repository: **可选** 资源权限仓储（域 Protocol）。注入时授权写 / 读
            落 ``resource_permission``（运行期**唯一**判定源，W3 / T2-13 补丁）；``None`` 时回退
            ``tool_permission``（保持旧行为，向后兼容）。
        tool_registry: **可选** 运行期工具注册表。注入时，``grant`` 会把已持久化 ``tool`` 行的
            真实 id 归一到同名注册表条目（``ResourcePermissionChecker`` 以
            ``getattr(tool, "tool_id")`` 作实例级 ``resource_id`` 比对；内置工具仅注册在内存注册表、
            默认无 ``tool_id``，不补齐则实例级授权**永不命中** → 恒默认拒绝）。
        pep: 可选策略执行点（RP-06）。
        pdp: 可选策略决策点（RP-07）。
    """

    def __init__(
        self,
        *,
        tool_repository: ToolRepository,
        tool_permission_repository: ToolPermissionRepository,
        resource_permission_repository: ResourcePermissionRepository | None = None,
        tool_registry: ToolRegistry | None = None,
        pep: PolicyEnforcementPoint | None = None,
        pdp: PolicyDecisionPoint | None = None,
    ) -> None:
        self._tools = tool_repository
        self._permissions = tool_permission_repository
        self._resource_permissions = resource_permission_repository
        self._registry = tool_registry
        self._pep = pep
        self._pdp = pdp

    @property
    def uses_resource_permission(self) -> bool:
        """是否经 ``resource_permission`` 读写授权（组合根接线后恒 ``True``）。"""
        return self._resource_permissions is not None

    # -- 授权读写 -----------------------------------------------------------

    def grant(
        self,
        *,
        tenant_id: str,
        tool_id: str,
        action: str = ToolAction.EXECUTE.value,
        effect: str = TOOL_EFFECT_ALLOW,
        scope: Mapping[str, Any] | None = None,
        agent_id: str | None = None,
        agent_version_id: str | None = None,
    ) -> ToolPermission:
        """授予 / 更新一条 Tool 权限（agent × tool × effect × scope）。

        经 ``resource_permission`` 落库时（W3 / T2-13 补丁）：``subject_type="agent"``、
        ``resource_type="TOOL"``、``subject_id=agent_id``、``resource_id=tool_id``（实例级）、
        ``action`` / ``effect`` / ``scope`` 直传；幂等经 ``upsert``（6 键）。

        Raises:
            DomainError: 动作 / 效果非法（``VALIDATION_ERROR``）；``APPROVAL`` 为预留位。
        """
        action_value = ToolAction.ensure(action).value
        effect_value = ToolEffect.ensure(effect)
        if effect_value not in (ToolEffect.ALLOW, ToolEffect.DENY):
            raise DomainError(
                "effect=APPROVAL 为 Phase 3 预留位，本阶段不支持",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "effect", "value": str(effect_value)},
            )
        scope_value = dict(scope) if scope else {}
        if self._resource_permissions is not None:
            stored = self._resource_permissions.upsert(
                ResourcePermission(
                    tenant_id=tenant_id,
                    subject_type=_SUBJECT_TYPE_AGENT,
                    subject_id=str(agent_id or ""),
                    resource_type=_RESOURCE_TYPE_TOOL,
                    resource_id=tool_id or None,
                    action=action_value,
                    effect=effect_value.value,
                    scope=scope_value,
                )
            )
            self._align_registry_identity(tool_id)
            return _resource_to_tool_permission(stored)
        return self._permissions.add(
            ToolPermission(
                tenant_id=tenant_id,
                agent_id=agent_id,
                agent_version_id=agent_version_id,
                tool_id=tool_id,
                action=action_value,
                effect=effect_value.value,
                scope=scope_value,
            )
        )

    def get_permission(self, permission_id: str, *, tenant_id: str) -> ToolPermission:
        """按 id 获取权限（**校验租户归属**：跨租户一律 ``NOT_FOUND``，I-1）。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``，映射 HTTP 404）。
        """
        if self._resource_permissions is not None:
            resource_permission = self._resource_permissions.get(permission_id)
            if resource_permission is None or resource_permission.tenant_id != tenant_id:
                raise DomainError(
                    "权限不存在",
                    code=ErrorCode.NOT_FOUND,
                    data={"permission_id": permission_id},
                )
            return _resource_to_tool_permission(resource_permission)
        permission = self._permissions.get(permission_id)
        if permission is None or permission.tenant_id != tenant_id:
            raise DomainError(
                "权限不存在",
                code=ErrorCode.NOT_FOUND,
                data={"permission_id": permission_id},
            )
        return permission

    def list_permissions(self, agent_id: str, *, tenant_id: str = "") -> list[ToolPermission]:
        """列出某 Agent 的全部 Tool 权限。

        经 ``resource_permission`` 读取时，按 ``(tenant_id, "agent", agent_id)`` 取主体级规则，
        再过滤 ``resource_type == "TOOL"``（与运行期判定链同源）。
        """
        if self._resource_permissions is not None:
            rules = self._resource_permissions.list_for_subject(
                tenant_id, _SUBJECT_TYPE_AGENT, agent_id
            )
            return [
                _resource_to_tool_permission(rule)
                for rule in rules
                if rule.resource_type == _RESOURCE_TYPE_TOOL
            ]
        return self._permissions.list_by_agent(agent_id)

    def revoke(self, permission_id: str, *, tenant_id: str) -> None:
        """撤销一条权限（先校验租户归属）。"""
        if self._resource_permissions is not None:
            # 校验存在性 + 租户归属（跨租户 → NOT_FOUND），再删除。
            self.get_permission(permission_id, tenant_id=tenant_id)
            self._resource_permissions.delete(permission_id)
            return
        permission = self.get_permission(permission_id, tenant_id=tenant_id)
        self._permissions.delete(permission)

    # -- 判定 ---------------------------------------------------------------

    def build_checker(self, *, agent_id: str) -> PermissionChecker:
        """依某 Agent 的授权装配 :class:`PermissionChecker`（DI）。

        🔴 本方法为**默认策略模板评估器**入口（R2 §2.3），**非**运行期判定链；运行期经
        ``ResourcePermissionChecker``（``astra_security``）判定。
        """
        permissions: Sequence[ToolPermission] = self._permissions.list_by_agent(agent_id)
        return PermissionChecker(
            permissions=permissions,
            tool_id_to_name=self._resolve_tool_names(permissions),
            pep=self._pep,
            pdp=self._pdp,
        )

    def check(self, ctx: Any, tool: Tool, action: str, *, agent_id: str) -> ToolEffect:
        """执行前逐次校验（便捷入口；模板评估器路径）。"""
        return self.build_checker(agent_id=agent_id).check(ctx, tool, action)

    # -- 内部 ---------------------------------------------------------------

    def _align_registry_identity(self, tool_id: str) -> None:
        """把已持久化 ``tool`` 行的真实 id 归一到**同名运行期注册表条目**（W3 / T2-13 补丁）。

        运行期 ``ResourcePermissionChecker`` 以 ``getattr(tool, "tool_id")`` 作实例级
        ``resource_id`` 与授权比对；内置工具仅注册在内存注册表、默认**无** ``tool_id``（F17），
        故 instance 级授权永不命中（→ 恒默认拒绝）。授权写入时（``grant``）以查询到的 ``tool``
        行 ``id`` 补齐同名注册表条目的 ``tool_id``，使实例级授权在运行期可命中。

        生产语义下同名 ``tool`` 仅一行，赋值恒等；测试含多行时以**最近一次授权**为准
        （运行期注册表条目为进程内单例，仅能承载一个 ``tool_id``）。

        宽松：注册表未注入 / 未持久化 / 未注册时**静默跳过**（不阻断授权）。
        """
        if self._registry is None:
            return
        tool = self._tools.get(tool_id)
        if tool is None:
            tool = self._tools.get_by_name(tool_id)
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            return
        try:
            registered = self._registry.get(tool_name)
        except Exception:  # noqa: BLE001 - 未注册（NOT_FOUND）时静默跳过
            return
        if getattr(registered, "tool_id", None) != tool_id:
            registered.tool_id = tool_id  # type: ignore[attr-defined]

    def _resolve_tool_names(self, permissions: Sequence[ToolPermission]) -> dict[str, str]:
        """构造 ``tool_id → tool.name`` 映射（用于把权限对齐到工具名）。"""
        mapping: dict[str, str] = {}
        for permission in permissions:
            tool_id = permission.tool_id
            if not tool_id or tool_id in mapping:
                continue
            tool = self._tools.get(tool_id)
            if tool is not None:
                mapping[tool_id] = tool.name
        return mapping
