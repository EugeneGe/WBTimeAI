"""MCP 授权读写服务（W3 / T2-13 补丁 · 裁定 §20 Erratum-2 / §21.4 X1/X2）。

运行期**唯一**判定源 ``astra_security.ResourcePermissionChecker`` **只读** ``resource_permission``
（``resource_type="TOOL"``，裁定 F32/F35），故 ``/mcp/permissions`` 的 ``grant`` / ``list`` 必须
写 / 读 ``resource_permission``，否则经该 API 授予的 ``ALLOW`` **永不可达**
（→ ``tool_call.status=DENIED``，与 ``/tools/permissions`` 同一类缺口；裁定 §20.1.5 X1/X2）。

⚠️ **不能只换存储目标，必须先做 id 映射**（裁定 §21.4(4)）：``/mcp/permissions`` 请求体用
``mcp_tool_id``（``mcp_tool`` 表 id），而判定链比对的是 **``tool`` 表行 id**
（``ResourcePermissionChecker`` 用 ``rule.resource_id == getattr(tool, "tool_id")``；
``MCPToolAdapter`` 暴露 ``tool_id``）。本服务先把 ``mcp_tool_id → tool 行 id`` 映射：

- **主**：经 ``tool.tool_ref``（``kind="mcp"`` + ``id=mcp_tool_id``）反查 ``tool`` 行；
- **备**：经 ``tool.name == "mcp:<server>.<tool>"`` 反查（与 ``MCPRegistry.sync_to_tool_registry``
  的命名口径一致）。

拿到 ``tool`` 行 id 后落 ``resource_permission``（``subject_type="agent"``、
``resource_type="TOOL"``、``resource_id=<tool 行 id>``、``action``、``effect``、``scope``）。

**未同步进 ``tool`` 表**的 MCPTool 无实例级锚 → **fail-closed**：``grant`` **不**写
``resource_permission``（该授权**不会**进入运行期判定链），改落 **deprecated 默认策略模板**
``mcp_permission``（**保留 ``/mcp/*`` API 契约的「写入 → 列举」往返**），并**结构化告警**
（勿静默吞没，裁定 §21.4(4)）；``list`` 亦按**同一映射口径**分支。

``mcp_permission`` 表 / ``SqlMCPPermissionRepository`` **保留不动**（deprecated、不 drop，
R1 §1.2 / 裁定 §20.1.5 X2）。``resource_permission_repository`` 为**加性可选**注入——
未注入时**逐字保留**旧行为（``mcp_permission``），向后兼容（对齐 ``astra_tool.PermissionService``
加性可选注入样式，裁定 §21.3）。

🔴 MCP 侧**无需** ``_align_registry_identity`` 桥接（``MCPToolAdapter`` 已暴露 ``tool_id``，
裁定 §21.4(3)）。本模块**零** ``astra_security`` 依赖（R2）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import (
    TOOL_TYPE_MCP,
    ResourcePermission,
    ResourcePermissionRepository,
    ToolAction,
    ToolEffect,
    ToolRepository,
)

from .domain import (
    MCP_ACTION_EXECUTE,
    MCP_EFFECT_DENY,
    MCPPermission,
    MCPPermissionRepository,
    MCPServerRepository,
    MCPToolRepository,
)

__all__ = ["MCPPermissionService"]

_LOGGER = logging.getLogger(__name__)

#: 资源权限主体类型（Agent）——与 ``ResourcePermissionChecker`` 对齐（F32）。
_SUBJECT_TYPE_AGENT = "agent"

#: 资源权限资源类型（Tool）——与 ``ResourcePermissionChecker`` 对齐（F32）。
_RESOURCE_TYPE_TOOL = "TOOL"


def _resource_to_mcp_permission(
    permission: ResourcePermission, *, mcp_tool_id: str
) -> MCPPermission:
    """``ResourcePermission`` 行 → ``MCPPermission`` 视图（**只读 DTO 映射**）。

    ``agent_version_id`` 无对应列，恒回填 ``None``；``mcp_tool_id`` 由调用方以**解析口径**传入
    （``grant`` 用请求值、``list`` 用查询值），保证「写入 → 列举」同口径往返。
    """
    return MCPPermission(
        id=permission.id,
        tenant_id=permission.tenant_id,
        created_at=permission.created_at,
        updated_at=permission.updated_at,
        agent_id=permission.subject_id or None,
        agent_version_id=None,
        mcp_tool_id=mcp_tool_id,
        action=permission.action,
        effect=permission.effect,
        scope=dict(permission.scope or {}),
    )


class MCPPermissionService:
    """MCP 授权读写服务（DI 注入领域 Protocol 仓储；裁定 §21.4 X1/X2）。

    Args:
        mcp_permission_repository: MCP 授权**默认策略模板**仓储（deprecated；非运行期判定源）。
        mcp_tool_repository: ``mcp_tool`` 发现目录仓储（供 ``mcp_tool_id → tool 行 id`` 映射）。
        mcp_server_repository: ``mcp_server`` 仓储（映射备路径取 ``server.name``）。
        tool_repository: ``tool`` 执行注册表仓储（``tool_ref`` 反查 / 命名反查）。
        resource_permission_repository: **可选** 资源权限仓储（域 Protocol）。注入时授权写 / 读
            落 ``resource_permission``（运行期**唯一**判定源，裁定 §21.4）；``None`` 时回退
            ``mcp_permission``（逐字保留旧行为，向后兼容）。
    """

    def __init__(
        self,
        *,
        mcp_permission_repository: MCPPermissionRepository,
        mcp_tool_repository: MCPToolRepository,
        mcp_server_repository: MCPServerRepository,
        tool_repository: ToolRepository,
        resource_permission_repository: ResourcePermissionRepository | None = None,
    ) -> None:
        self._mcp_permissions = mcp_permission_repository
        self._mcp_tools = mcp_tool_repository
        self._mcp_servers = mcp_server_repository
        self._tools = tool_repository
        self._resource_permissions = resource_permission_repository

    @property
    def uses_resource_permission(self) -> bool:
        """是否经 ``resource_permission`` 读写授权（组合根接线后恒 ``True``）。"""
        return self._resource_permissions is not None

    # -- 授权读写 -----------------------------------------------------------

    def grant(
        self,
        *,
        tenant_id: str,
        mcp_tool_id: str,
        action: str = MCP_ACTION_EXECUTE,
        effect: str = MCP_EFFECT_DENY,
        scope: Mapping[str, Any] | None = None,
        agent_id: str | None = None,
        agent_version_id: str | None = None,
    ) -> MCPPermission:
        """授予 / 更新一条 MCP Tool 授权（agent × mcp_tool × effect × scope）。

        经 ``resource_permission`` 落库时（裁定 §21.4）：先做 ``mcp_tool_id → tool 行 id`` 映射，
        再 ``upsert``（``subject_type="agent"`` / ``resource_type="TOOL"`` /
        ``subject_id=agent_id`` / ``resource_id=<tool 行 id>``）。**未映射**（未同步进 ``tool``
        表）→ fail-closed：不写 ``resource_permission``，改落 deprecated ``mcp_permission``
        模板并告警。

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
            tool_row_id = self._resolve_tool_row_id(mcp_tool_id)
            if tool_row_id is not None:
                stored = self._resource_permissions.upsert(
                    ResourcePermission(
                        tenant_id=tenant_id,
                        subject_type=_SUBJECT_TYPE_AGENT,
                        subject_id=str(agent_id or ""),
                        resource_type=_RESOURCE_TYPE_TOOL,
                        resource_id=tool_row_id,
                        action=action_value,
                        effect=effect_value.value,
                        scope=scope_value,
                    )
                )
                return _resource_to_mcp_permission(stored, mcp_tool_id=mcp_tool_id)
            # fail-closed：MCPTool 未同步进 ``tool`` 表 → 无实例级锚 → 不写运行期判定源。
            self._warn_unmapped_tool(mcp_tool_id, tenant_id=tenant_id)

        # 默认策略模板（deprecated）：未接线 / 未映射时的**兜底**（保留 API 契约的往返）。
        return self._mcp_permissions.add(
            MCPPermission(
                tenant_id=tenant_id,
                agent_id=agent_id,
                agent_version_id=agent_version_id,
                mcp_tool_id=mcp_tool_id,
                action=action_value,
                effect=effect_value.value,
                scope=scope_value,
            )
        )

    def list_by_tool(self, mcp_tool_id: str, *, tenant_id: str = "") -> list[MCPPermission]:
        """列出某 MCPTool 的全部授权条目（**同一映射口径**）。

        经 ``resource_permission`` 读取时，先做 ``mcp_tool_id → tool 行 id`` 映射，再按
        ``(tenant_id, "TOOL", <tool 行 id>)`` 列举（与运行期判定链**同源**）；**未映射**时读
        deprecated ``mcp_permission`` 模板（与 ``grant`` 分支一致）。
        """
        if self._resource_permissions is None:
            return self._mcp_permissions.list_by_tool(mcp_tool_id)
        tool_row_id = self._resolve_tool_row_id(mcp_tool_id)
        if tool_row_id is None:
            return self._mcp_permissions.list_by_tool(mcp_tool_id)
        rules = self._resource_permissions.list_by_resource(
            tenant_id, _RESOURCE_TYPE_TOOL, tool_row_id
        )
        return [_resource_to_mcp_permission(rule, mcp_tool_id=mcp_tool_id) for rule in rules]

    def revoke(self, permission_id: str, *, tenant_id: str) -> None:
        """撤销一条授权（先校验租户归属：跨租户一律 ``NOT_FOUND``，I-1）。

        运行期判定源（``resource_permission``）与 deprecated 模板（``mcp_permission``）两处均查；
        命中哪处删哪处。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``，映射 HTTP 404）。
        """
        if self._resource_permissions is not None:
            rule = self._resource_permissions.get(permission_id)
            if rule is not None:
                if rule.tenant_id != tenant_id:
                    raise DomainError(
                        "权限不存在",
                        code=ErrorCode.NOT_FOUND,
                        data={"permission_id": permission_id},
                    )
                self._resource_permissions.delete(permission_id)
                return
        permission = self._mcp_permissions.get(permission_id)
        if permission is None or permission.tenant_id != tenant_id:
            raise DomainError(
                "权限不存在",
                code=ErrorCode.NOT_FOUND,
                data={"permission_id": permission_id},
            )
        self._mcp_permissions.delete(permission)

    # -- 内部 ---------------------------------------------------------------

    def _resolve_tool_row_id(self, mcp_tool_id: str) -> str | None:
        """``mcp_tool_id``（``mcp_tool`` 表 id）→ ``tool`` 执行注册表行 id（裁定 §21.4(4)）。

        主路径经 ``tool.tool_ref``（``kind="mcp"`` + ``id``）反查；备路径经命名
        ``"mcp:<server>.<tool>"`` 反查。未同步进 ``tool`` 表 → 返回 ``None``（fail-closed）。
        """
        if not mcp_tool_id:
            return None
        # 主：tool_ref 反查（mcp_tool_id 全局唯一，可唯一定位 tool 行）。
        for row in self._tools.list(source=TOOL_TYPE_MCP):
            tool_ref = getattr(row, "tool_ref", None) or {}
            if tool_ref.get("kind") == TOOL_TYPE_MCP and str(tool_ref.get("id")) == str(
                mcp_tool_id
            ):
                row_id = str(getattr(row, "id", "") or "")
                if row_id:
                    return row_id
        # 备：mcp_tool → server → 命名反查。
        mcp_tool = self._mcp_tools.get(mcp_tool_id)
        if mcp_tool is None:
            return None
        server = self._mcp_servers.get(getattr(mcp_tool, "mcp_server_id", "") or "")
        server_name = getattr(server, "name", None)
        if not server_name:
            return None
        tool = self._tools.get_by_name(
            f"mcp:{server_name}.{getattr(mcp_tool, 'name', '')}",
            tenant_id=getattr(server, "tenant_id", None) or None,
        )
        if tool is None:
            return None
        row_id = str(getattr(tool, "id", "") or "")
        return row_id or None

    def _warn_unmapped_tool(self, mcp_tool_id: str, *, tenant_id: str) -> None:
        """结构化告警：MCPTool 未同步进 ``tool`` 表 → 授权 fail-closed（不静默吞没）。"""
        _LOGGER.warning(
            "mcp.permission.unmapped_tool mcp_tool_id=%s tenant_id=%s",
            mcp_tool_id,
            tenant_id,
            extra={
                "event": "mcp.permission.unmapped_tool",
                "mcp_tool_id": mcp_tool_id,
                "tenant_id": tenant_id,
            },
        )
