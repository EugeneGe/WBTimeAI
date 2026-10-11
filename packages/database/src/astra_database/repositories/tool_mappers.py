"""ORM 行 ↔ 领域 ``Tool`` / ``ToolVersion`` / ``ToolPermission`` 映射。

将 ``astra_database.models.tool`` 的 SQLAlchemy 行转换为 ``astra_domain`` 的
:class:`~astra_domain.entities.tool.Tool` / :class:`~astra_domain.entities.tool.ToolVersion` /
:class:`~astra_domain.entities.tool.ToolPermission`（及反向），使领域层保持零框架依赖（C-03）。

⚠️ 部分 ORM 表未含时间戳列（``tool`` 无时间戳、``tool_version`` 无 ``updated_at``），
   故 ``to_domain`` 的时间戳以当前 UTC 回退（同 ``model_mappers`` 口径）。
"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_domain import Tool, ToolPermission, ToolVersion

from ..models.tool import Tool as OrmTool
from ..models.tool import ToolPermission as OrmToolPermission
from ..models.tool import ToolVersion as OrmToolVersion

__all__ = [
    "tool_to_domain",
    "tool_to_orm",
    "tool_version_to_domain",
    "tool_version_to_orm",
    "tool_permission_to_domain",
    "tool_permission_to_orm",
]


def _dt(value: object):
    """归一化时间戳：``None`` 时回退当前 UTC（ORM 无该列）。"""
    return value if value is not None else utcnow()


def tool_to_domain(row: OrmTool) -> Tool:
    """ORM 工具行 → 领域 ``Tool``。"""
    return Tool(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        category=row.category,
        source=row.source,
        input_schema=dict(row.input_schema) if row.input_schema else {},
        output_schema=dict(row.output_schema) if row.output_schema else {},
        requires_sandbox=bool(row.requires_sandbox),
        status=row.status,
        tool_ref=dict(row.tool_ref) if row.tool_ref else {},
    )


def tool_to_orm(entity: Tool) -> OrmTool:
    """领域 ``Tool`` → ORM 行。"""
    return OrmTool(
        id=entity.id,
        tenant_id=entity.tenant_id,
        name=entity.name,
        display_name=entity.display_name,
        description=entity.description,
        category=entity.category,
        source=entity.source,
        input_schema=dict(entity.input_schema) if entity.input_schema else {},
        output_schema=dict(entity.output_schema) if entity.output_schema else {},
        requires_sandbox=bool(entity.requires_sandbox),
        status=entity.status,
        tool_ref=dict(entity.tool_ref) if entity.tool_ref else None,
    )


def tool_version_to_domain(row: OrmToolVersion) -> ToolVersion:
    """ORM 工具版本行 → 领域 ``ToolVersion``。"""
    return ToolVersion(
        id=row.id,
        tenant_id=getattr(row, "tenant_id", None),
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        tool_id=row.tool_id,
        version=row.version,
        spec=dict(row.spec) if row.spec else {},
    )


def tool_version_to_orm(entity: ToolVersion) -> OrmToolVersion:
    """领域 ``ToolVersion`` → ORM 行。"""
    return OrmToolVersion(
        id=entity.id,
        tool_id=entity.tool_id,
        version=entity.version,
        spec=dict(entity.spec) if entity.spec else {},
    )


def tool_permission_to_domain(row: OrmToolPermission) -> ToolPermission:
    """ORM 权限行 → 领域 ``ToolPermission``。"""
    return ToolPermission(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        tool_id=row.tool_id,
        action=row.action,
        effect=row.effect,
        scope=dict(row.scope) if row.scope else {},
    )


def tool_permission_to_orm(entity: ToolPermission) -> OrmToolPermission:
    """领域 ``ToolPermission`` → ORM 行。"""
    return OrmToolPermission(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_id=entity.agent_id,
        agent_version_id=entity.agent_version_id,
        tool_id=entity.tool_id,
        action=entity.action,
        effect=entity.effect,
        scope=dict(entity.scope) if entity.scope else {},
    )
