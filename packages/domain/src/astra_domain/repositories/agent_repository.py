"""Agent 组仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``agent`` / ``agent_version`` / ``agent_tool``。
SQLAlchemy 实现位于拥有该聚合的能力包 ``repositories/``。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.agent import Agent, AgentTool, AgentVersion
from ..entities.agent_skill import AgentSkill
from .base import Repository

__all__ = [
    "AgentRepository",
    "AgentVersionRepository",
    "AgentToolRepository",
    "AgentSkillRepository",
]


@runtime_checkable
class AgentRepository(Repository[Agent], Protocol):
    """Agent 仓储接口（多租户隔离）。"""

    def list_by_tenant(self, tenant_id: str) -> list[Agent]:
        """列出某租户下的全部 Agent。"""
        ...


@runtime_checkable
class AgentVersionRepository(Repository[AgentVersion], Protocol):
    """AgentVersion 仓储接口（不可变版本快照）。"""

    def list_by_agent(self, agent_id: str) -> list[AgentVersion]:
        """列出某 Agent 的全部版本。"""
        ...


@runtime_checkable
class AgentToolRepository(Repository[AgentTool], Protocol):
    """AgentTool 仓储接口（Tool 绑定）。"""

    def list_by_agent_version(self, agent_version_id: str) -> list[AgentTool]:
        """列出某 AgentVersion 绑定的全部 Tool。"""
        ...


@runtime_checkable
class AgentSkillRepository(Repository[AgentSkill], Protocol):
    """AgentSkill 仓储接口（Skill 绑定；W2 裁定 R6，同构 ``AgentToolRepository``）。

    🔴 定义在 ``astra_domain``（与 ``AgentToolRepository`` 同层），``astra_skill`` /
    ``astra_agent`` 两侧共同面向本 Protocol（避免 ``agent→skill`` 硬依赖）。
    """

    def list_by_agent_version(self, agent_version_id: str) -> list[AgentSkill]:
        """列出某 AgentVersion 绑定的全部 Skill（按 ``id`` 升序）。"""
        ...
