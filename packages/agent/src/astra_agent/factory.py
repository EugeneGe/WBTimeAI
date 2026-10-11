"""Agent 组组合工厂（能力包）——``build_agent_services(session_factory)``。"""

from __future__ import annotations

from dataclasses import dataclass

from astra_domain import AgentSkillRepository
from sqlalchemy.orm import Session, sessionmaker

from .repositories import (
    SqlAgentRepository,
    SqlAgentToolRepository,
    SqlAgentVersionRepository,
)
from .services import AgentService

__all__ = ["AgentServices", "build_agent_services"]


@dataclass
class AgentServices:
    """Agent 组装配结果（仓储 + 服务）。"""

    agents: SqlAgentRepository
    versions: SqlAgentVersionRepository
    agent_tools: SqlAgentToolRepository
    agent_service: AgentService
    agent_skills: AgentSkillRepository | None = None


def build_agent_services(
    session_factory: sessionmaker[Session],
    *,
    agent_skill_repository: AgentSkillRepository | None = None,
) -> AgentServices:
    """构造 Agent 组仓储与服务。

    W2 / T2-09 **加性**扩展（R6 §6.2）：``agent_skill_repository`` 为**可选注入**——
    其 SQL 实现（``SqlAgentSkillRepository``）落 ``astra_skill.repositories``，经**组合根**
    注入（避免 ``agent→skill`` 包依赖边）；缺省 ``None`` 时 :class:`AgentService` 的
    ``bind_skill`` / ``skills_for_version`` 不可用（向后兼容 Phase 1 行为）。
    """
    agents = SqlAgentRepository(session_factory)
    versions = SqlAgentVersionRepository(session_factory)
    agent_tools = SqlAgentToolRepository(session_factory)
    agent_service = AgentService(
        agent_repository=agents,
        version_repository=versions,
        agent_tool_repository=agent_tools,
        agent_skill_repository=agent_skill_repository,
    )
    return AgentServices(
        agents=agents,
        versions=versions,
        agent_tools=agent_tools,
        agent_service=agent_service,
        agent_skills=agent_skill_repository,
    )
