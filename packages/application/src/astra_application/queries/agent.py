"""Agent 查询（Query / QueryHandler）——设计 §2.2 / §2.4。"""

from __future__ import annotations

from dataclasses import dataclass

from astra_core import DomainError, ErrorCode
from astra_domain import AgentRepository

from ..dto.agent import AgentDTO
from .base import Query

__all__ = [
    "ListAgentsQuery",
    "ListAgentsHandler",
    "GetAgentQuery",
    "GetAgentHandler",
]


@dataclass
class ListAgentsQuery(Query):
    """列出某租户下的全部 Agent。"""

    tenant_id: str = ""


class ListAgentsHandler:
    """列出 Agent 查询处理器（经领域 ``AgentRepository``）。"""

    def __init__(self, agent_repository: AgentRepository) -> None:
        self._agents = agent_repository

    def handle(self, query: ListAgentsQuery) -> list[AgentDTO]:
        """返回 Agent DTO 列表（多租户隔离）。"""
        return [
            AgentDTO.from_entity(agent) for agent in self._agents.list(tenant_id=query.tenant_id)
        ]


@dataclass
class GetAgentQuery(Query):
    """获取单个 Agent 详情（租户校验）。"""

    agent_id: str = ""
    tenant_id: str = ""


class GetAgentHandler:
    """获取 Agent 详情查询处理器。"""

    def __init__(self, agent_repository: AgentRepository) -> None:
        self._agents = agent_repository

    def handle(self, query: GetAgentQuery) -> AgentDTO:
        """返回 Agent DTO（跨租户 / 不存在 → ``NOT_FOUND``）。"""
        agent = self._agents.get(query.agent_id)
        if agent is None or agent.tenant_id != query.tenant_id:
            raise DomainError(
                "Agent 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": query.agent_id},
            )
        return AgentDTO.from_entity(agent)
