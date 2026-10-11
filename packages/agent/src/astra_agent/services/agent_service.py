"""``AgentService``（Agent / 版本发布 / 工具绑定；设计 §2.4 / ``I-P1-05``）。

数据驱动（``I-P1-05``）：改 ``system_prompt`` / ``agent_tool`` → 影响下一次执行的
system 消息与可用工具集合；**一次发布 = 一个新版本**（旧版本**不可变**）；执行时**总是
加载一个明确 ``agent_version``**。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import (
    AGENT_STATUS_ACTIVE,
    AGENT_TYPE_PRIMARY,
    AGENT_VERSION_STATUS_PUBLISHED,
    Agent,
    AgentSkill,
    AgentSkillRepository,
    AgentTool,
    AgentVersion,
)

from ..repositories import (
    SqlAgentRepository,
    SqlAgentToolRepository,
    SqlAgentVersionRepository,
)

__all__ = ["AgentService"]


class AgentService:
    """Agent 领域服务（DI 注入领域 Protocol 仓储）。"""

    def __init__(
        self,
        *,
        agent_repository: SqlAgentRepository,
        version_repository: SqlAgentVersionRepository,
        agent_tool_repository: SqlAgentToolRepository,
        agent_skill_repository: AgentSkillRepository | None = None,
    ) -> None:
        self._agents = agent_repository
        self._versions = version_repository
        self._agent_tools = agent_tool_repository
        self._agent_skills = agent_skill_repository

    # -- Agent --------------------------------------------------------------

    def create_agent(
        self,
        *,
        tenant_id: str,
        name: str,
        created_by: str,
        type: str = AGENT_TYPE_PRIMARY,
        workspace_id: str | None = None,
        description: str | None = None,
    ) -> Agent:
        """创建 Agent（``DRAFT``，无当前版本）。"""
        return self._agents.add(
            Agent(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=name,
                description=description,
                type=type,
                created_by=created_by,
            )
        )

    def get_agent(self, agent_id: str) -> Agent | None:
        """按主键获取 Agent。"""
        return self._agents.get(agent_id)

    def list_versions(self, agent_id: str) -> list[AgentVersion]:
        """列出某 Agent 的全部版本。"""
        return self._versions.list_by_agent(agent_id)

    # -- 版本发布 -----------------------------------------------------------

    def publish_version(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        model_config: dict[str, Any],
        runtime_config: dict[str, Any],
        created_by: str,
        version: str | None = None,
    ) -> AgentVersion:
        """发布一个新版本（**不可变**）并切换 ``Agent.current_version_id``。

        Args:
            agent_id: 目标 Agent 标识。
            system_prompt: 系统提示词。
            model_config: 模型配置（``ModelConfig.to_dict()`` 结构）。
            runtime_config: 运行配置（``RuntimeConfig.to_dict()`` 结构）。
            created_by: 发布者用户标识。
            version: 版本号（缺省按既有版本数自增为 ``v{n}``）。

        Returns:
            新发布的 :class:`AgentVersion`（``PUBLISHED``）。

        Raises:
            DomainError: Agent 不存在（``NOT_FOUND``）。
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise DomainError(
                f"Agent 不存在：{agent_id}",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": agent_id},
            )
        label = version or f"v{len(self._versions.list_by_agent(agent_id)) + 1}"
        new_version = AgentVersion(
            agent_id=agent_id,
            version=label,
            system_prompt=system_prompt,
            model_config=dict(model_config),
            runtime_config=dict(runtime_config),
            status=AGENT_VERSION_STATUS_PUBLISHED,
            created_by=created_by,
        )
        new_version = self._versions.add(new_version)
        agent.current_version_id = new_version.id
        agent.status = AGENT_STATUS_ACTIVE
        self._agents.update(agent)
        return new_version

    def load_version(self, agent: Agent, version_id: str | None = None) -> AgentVersion:
        """加载一个**明确的** ``agent_version``（缺省取 ``current_version_id``）。

        Raises:
            DomainError: 未指定版本且 Agent 无当前版本（``VALIDATION_ERROR``）；
                或版本不存在 / 归属不符（``NOT_FOUND``）。
        """
        target_id = version_id or agent.current_version_id
        if not target_id:
            raise DomainError(
                "Agent 无当前版本且未显式指定 version_id",
                code=ErrorCode.VALIDATION_ERROR,
                data={"agent_id": agent.id},
            )
        version = self._versions.get(target_id)
        if version is None or version.agent_id != agent.id:
            raise DomainError(
                f"AgentVersion 不存在或归属不符：{target_id}",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": agent.id, "version_id": target_id},
            )
        return version

    # -- 工具绑定 -----------------------------------------------------------

    def bind_tool(
        self,
        *,
        tenant_id: str,
        agent_version_id: str,
        tool_id: str,
        permission_scope: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> AgentTool:
        """把 Tool 绑定到某个 **AgentVersion**（含权限 scope）。"""
        return self._agent_tools.add(
            AgentTool(
                tenant_id=tenant_id,
                agent_version_id=agent_version_id,
                tool_id=tool_id,
                enabled=enabled,
                permission_scope=dict(permission_scope or {}),
            )
        )

    def tools_for_version(self, agent_version_id: str) -> list[AgentTool]:
        """列出某 AgentVersion 绑定的全部 Tool。"""
        return self._agent_tools.list_by_agent_version(agent_version_id)

    # -- Skill 绑定（W2 / T2-09；同构 ``bind_tool`` / ``tools_for_version``）--

    def bind_skill(
        self,
        *,
        tenant_id: str,
        agent_version_id: str,
        skill_id: str,
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> AgentSkill:
        """把 Skill 绑定到某个 **AgentVersion**（含 ``config``）。

        Skill 绑定**随版本化**：一次发布 = 一个新版本，绑定变更可回滚。

        Raises:
            DomainError: 未注入 ``agent_skill_repository``（``INTERNAL_ERROR``）。
        """
        if self._agent_skills is None:
            raise DomainError(
                "AgentService 未装配 agent_skill_repository",
                code=ErrorCode.INTERNAL_ERROR,
                data={"agent_version_id": agent_version_id, "skill_id": skill_id},
            )
        return self._agent_skills.add(
            AgentSkill(
                tenant_id=tenant_id,
                agent_version_id=agent_version_id,
                skill_id=skill_id,
                enabled=enabled,
                config=dict(config or {}),
            )
        )

    def skills_for_version(self, agent_version_id: str) -> list[AgentSkill]:
        """列出某 AgentVersion 绑定的全部 Skill（按 ``id`` 升序）。

        Raises:
            DomainError: 未注入 ``agent_skill_repository``（``INTERNAL_ERROR``）。
        """
        if self._agent_skills is None:
            raise DomainError(
                "AgentService 未装配 agent_skill_repository",
                code=ErrorCode.INTERNAL_ERROR,
                data={"agent_version_id": agent_version_id},
            )
        return self._agent_skills.list_by_agent_version(agent_version_id)

    # -- 一致性校验 ---------------------------------------------------------

    def validate_current_version(self, agent: Agent, version: AgentVersion) -> None:
        """校验 ``agent.current_version_id`` 与版本 ``agent_id`` 一致（应用层）。

        Raises:
            DomainError: 不一致（``VALIDATION_ERROR``）。
        """
        if agent.current_version_id != version.id or version.agent_id != agent.id:
            raise DomainError(
                "current_version_id 与版本归属不一致",
                code=ErrorCode.VALIDATION_ERROR,
                data={
                    "agent_id": agent.id,
                    "current_version_id": agent.current_version_id,
                    "version_id": version.id,
                    "version_agent_id": version.agent_id,
                },
            )
