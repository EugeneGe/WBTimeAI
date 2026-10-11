"""Agent 用例（Command / CommandHandler）——设计 §2.2 / §2.4。

命令：创建 Agent / 更新 Agent / 发布 AgentVersion（+ Tool 绑定）。
处理器编排能力包服务（``astra_agent.AgentService``）与领域 Protocol（``AgentRepository``），
返回应用层 DTO。Application **不感知** Runtime / Web / ORM（C-03 / Q1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_agent import AgentService
from astra_core import DomainError, ErrorCode
from astra_domain import AGENT_TYPE_PRIMARY, AgentRepository

from ..dto.agent import AgentDTO, AgentVersionDTO
from .base import Command

__all__ = [
    "CreateAgentCommand",
    "CreateAgentHandler",
    "UpdateAgentCommand",
    "UpdateAgentHandler",
    "PublishAgentVersionCommand",
    "PublishAgentVersionHandler",
]


@dataclass
class CreateAgentCommand(Command):
    """创建 Agent 命令。"""

    tenant_id: str = ""
    name: str = ""
    created_by: str = ""
    type: str = AGENT_TYPE_PRIMARY
    workspace_id: str | None = None
    description: str | None = None


class CreateAgentHandler:
    """创建 Agent 命令处理器（委托 ``AgentService``）。"""

    def __init__(self, agents: AgentService) -> None:
        self._agents = agents

    def handle(self, command: CreateAgentCommand) -> AgentDTO:
        """创建 Agent（``DRAFT``，无当前版本）并返回 DTO。"""
        agent = self._agents.create_agent(
            tenant_id=command.tenant_id,
            name=command.name,
            created_by=command.created_by,
            type=command.type,
            workspace_id=command.workspace_id,
            description=command.description,
        )
        return AgentDTO.from_entity(agent)


@dataclass
class UpdateAgentCommand(Command):
    """更新 Agent 命令（仅名称 / 描述 / 状态；缺省字段不变）。"""

    agent_id: str = ""
    tenant_id: str = ""
    name: str | None = None
    description: str | None = None
    status: str | None = None


class UpdateAgentHandler:
    """更新 Agent 命令处理器（经领域 ``AgentRepository``）。"""

    def __init__(self, agent_repository: AgentRepository) -> None:
        self._agents = agent_repository

    def handle(self, command: UpdateAgentCommand) -> AgentDTO:
        """更新 Agent（跨租户 → ``NOT_FOUND``）并返回 DTO。"""
        agent = self._agents.get(command.agent_id)
        if agent is None or agent.tenant_id != command.tenant_id:
            raise DomainError(
                "Agent 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": command.agent_id},
            )
        if command.name is not None:
            agent.name = command.name
        if command.description is not None:
            agent.description = command.description
        if command.status is not None:
            agent.status = command.status
        agent.touch()
        agent = self._agents.update(agent)
        return AgentDTO.from_entity(agent)


@dataclass
class PublishAgentVersionCommand(Command):
    """发布 AgentVersion 命令（一次发布 = 一个新版本，旧版本不可变）。

    ``tools`` 为可选绑定列表：``[{"tool_id": ..., "permission_scope": {...}}, ...]``。
    """

    agent_id: str = ""
    system_prompt: str = ""
    model_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    version: str | None = None
    tenant_id: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


class PublishAgentVersionHandler:
    """发布 AgentVersion 命令处理器（委托 ``AgentService``）。"""

    def __init__(self, agents: AgentService) -> None:
        self._agents = agents

    def handle(self, command: PublishAgentVersionCommand) -> AgentVersionDTO:
        """发布一个新版本（``PUBLISHED``）并按需绑定 Tool，返回 DTO。"""
        version = self._agents.publish_version(
            agent_id=command.agent_id,
            system_prompt=command.system_prompt,
            model_config=command.model_config,
            runtime_config=command.runtime_config,
            created_by=command.created_by,
            version=command.version,
        )
        for tool in command.tools:
            self._agents.bind_tool(
                tenant_id=command.tenant_id,
                agent_version_id=version.id,
                tool_id=str(tool.get("tool_id", "")),
                permission_scope=dict(tool.get("permission_scope") or {}),
                enabled=bool(tool.get("enabled", True)),
            )
        return AgentVersionDTO.from_entity(version)
