"""ORM 行 ↔ 领域实体映射（Agent / AgentVersion / AgentTool）。

将 ``astra_database.models.agent`` 的 SQLAlchemy 行与 ``astra_domain`` 实体互转。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from astra_database.models.agent import Agent as OrmAgent
from astra_database.models.agent import AgentTool as OrmAgentTool
from astra_database.models.agent import AgentVersion as OrmAgentVersion
from astra_domain import Agent, AgentTool, AgentVersion

__all__ = [
    "agent_to_domain",
    "agent_to_orm",
    "version_to_domain",
    "version_to_orm",
    "agent_tool_to_domain",
    "agent_tool_to_orm",
]


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


# -- Agent ------------------------------------------------------------------


def agent_to_domain(row: OrmAgent) -> Agent:
    """ORM Agent 行 → 领域 ``Agent``。"""
    return Agent(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workspace_id=row.workspace_id,
        name=row.name,
        description=row.description,
        type=row.type,
        status=row.status,
        current_version_id=row.current_version_id,
        created_by=row.created_by,
    )


def agent_to_orm(entity: Agent) -> OrmAgent:
    """领域 ``Agent`` → ORM 行。"""
    return OrmAgent(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        name=entity.name,
        description=entity.description,
        type=entity.type,
        status=entity.status,
        current_version_id=entity.current_version_id,
        created_by=entity.created_by,
    )


# -- AgentVersion -----------------------------------------------------------


def version_to_domain(row: OrmAgentVersion) -> AgentVersion:
    """ORM AgentVersion 行 → 领域 ``AgentVersion``。"""
    created = _dt(getattr(row, "created_at", None))
    return AgentVersion(
        id=row.id,
        tenant_id=None,
        created_at=created,
        updated_at=_dt(getattr(row, "updated_at", None)) if hasattr(row, "updated_at") else created,
        agent_id=row.agent_id,
        version=row.version,
        system_prompt=row.system_prompt,
        model_config=dict(row.model_config or {}),
        runtime_config=dict(row.runtime_config or {}),
        status=row.status,
        created_by=row.created_by,
    )


def version_to_orm(entity: AgentVersion) -> OrmAgentVersion:
    """领域 ``AgentVersion`` → ORM 行。"""
    return OrmAgentVersion(
        id=entity.id,
        agent_id=entity.agent_id,
        version=entity.version,
        system_prompt=entity.system_prompt,
        model_config=dict(entity.model_config or {}),
        runtime_config=dict(entity.runtime_config or {}),
        status=entity.status,
        created_by=entity.created_by,
        created_at=_dt(entity.created_at),
    )


# -- AgentTool --------------------------------------------------------------


def agent_tool_to_domain(row: OrmAgentTool) -> AgentTool:
    """ORM AgentTool 行 → 领域 ``AgentTool``。"""
    return AgentTool(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_version_id=row.agent_version_id,
        tool_id=row.tool_id,
        enabled=bool(row.enabled),
        permission_scope=dict(row.permission_scope or {}),
    )


def agent_tool_to_orm(entity: AgentTool) -> OrmAgentTool:
    """领域 ``AgentTool`` → ORM 行。"""
    return OrmAgentTool(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_version_id=entity.agent_version_id,
        tool_id=entity.tool_id,
        enabled=entity.enabled,
        permission_scope=dict(entity.permission_scope or {}) or None,
    )
