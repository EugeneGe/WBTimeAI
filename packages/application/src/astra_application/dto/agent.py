"""Agent 相关 DTO（设计 §2.2 / §2.4；应用层，零框架依赖）。

- :class:`AgentDTO`：Agent 视图；
- :class:`AgentVersionDTO`：AgentVersion 视图（一次发布 = 一个不可变版本）；
- :class:`AgentToolDTO`：AgentVersion ↔ Tool 绑定视图（含权限 scope）。

🔴 约定（A27）：业务 DTO 顶层键**不得**同时使用 ``{code, message, data, request_id}``
   （保留给统一响应壳）；语义相近字段改用 ``result`` / ``items`` / ``payload``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_domain import Agent, AgentTool, AgentVersion

from .base import DTO

__all__ = ["AgentDTO", "AgentVersionDTO", "AgentToolDTO"]


@dataclass
class AgentDTO(DTO):
    """Agent DTO。"""

    id: str
    tenant_id: str | None
    name: str
    workspace_id: str | None = None
    description: str | None = None
    type: str = "PRIMARY"
    status: str = "DRAFT"
    current_version_id: str | None = None
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: Agent) -> AgentDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            name=entity.name,
            workspace_id=entity.workspace_id,
            description=entity.description,
            type=entity.type,
            status=entity.status,
            current_version_id=entity.current_version_id,
            created_by=entity.created_by,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass
class AgentVersionDTO(DTO):
    """AgentVersion DTO（**不可变**：一次发布 = 一个新版本）。"""

    id: str
    agent_id: str
    version: str
    system_prompt: str = ""
    model_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    status: str = "PUBLISHED"
    created_by: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: AgentVersion) -> AgentVersionDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            agent_id=entity.agent_id,
            version=entity.version,
            system_prompt=entity.system_prompt,
            model_config=dict(entity.model_config or {}),
            runtime_config=dict(entity.runtime_config or {}),
            status=entity.status,
            created_by=entity.created_by,
            created_at=entity.created_at,
        )


@dataclass
class AgentToolDTO(DTO):
    """AgentVersion ↔ Tool 绑定 DTO（含权限 scope）。"""

    id: str
    tenant_id: str | None
    agent_version_id: str
    tool_id: str
    enabled: bool = True
    permission_scope: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_entity(cls, entity: AgentTool) -> AgentToolDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            agent_version_id=entity.agent_version_id,
            tool_id=entity.tool_id,
            enabled=entity.enabled,
            permission_scope=dict(entity.permission_scope or {}),
        )
