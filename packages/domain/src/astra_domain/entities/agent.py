"""Agent 组领域实体（设计 §2.4）。

纯 dataclass，零框架依赖（C-03）；主键经 :class:`~astra_domain.entities.base.Entity`
默认由 :func:`astra_core.generate_id` 生成（C-04）。

- :class:`Agent`：聚合根（身份与生命周期）；
- :class:`AgentVersion`：不可变版本快照；
- :class:`AgentTool`：Tool 绑定 + 权限 scope。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import AGENT_STATUS_DRAFT, AGENT_TYPE_PRIMARY, AGENT_VERSION_STATUS_DRAFT
from .base import AggregateRoot

__all__ = ["Agent", "AgentVersion", "AgentTool"]


@dataclass
class Agent(AggregateRoot):
    """Agent 聚合根（数据驱动配置的身份与生命周期）。

    Attributes:
        workspace_id: 归属工作区标识（可空）。
        name: Agent 名称。
        description: 描述（可空）。
        type: Agent 类型（``AgentType`` 字面值）。
        status: 生命周期状态（``AgentStatus`` 字面值）。
        current_version_id: 当前生效版本标识（可空）。
        created_by: 创建者用户标识。
    """

    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    type: str = AGENT_TYPE_PRIMARY
    status: str = AGENT_STATUS_DRAFT
    current_version_id: str | None = None
    created_by: str = ""


@dataclass
class AgentVersion(AggregateRoot):
    """AgentVersion 聚合根（一次发布 = 一个新版本，不可变）。

    Attributes:
        agent_id: 所属 Agent 标识。
        version: 版本号（如 ``v1``）。
        system_prompt: 系统提示词。
        model_config: 模型配置（``ModelConfig.to_dict()`` 结构）。
        runtime_config: 运行配置（``RuntimeConfig.to_dict()`` 结构）。
        status: 版本状态（``AgentVersionStatus`` 字面值）。
        created_by: 创建者用户标识。
    """

    agent_id: str = ""
    version: str = ""
    system_prompt: str = ""
    model_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    status: str = AGENT_VERSION_STATUS_DRAFT
    created_by: str = ""


@dataclass
class AgentTool(AggregateRoot):
    """AgentTool 聚合根（绑定到 AgentVersion 的 Tool + 权限 scope）。

    Attributes:
        agent_version_id: 绑定的 AgentVersion 标识。
        tool_id: 绑定的 Tool 标识。
        enabled: 是否启用。
        permission_scope: 权限 scope（``PermissionScope.to_dict()`` 结构）。
    """

    agent_version_id: str = ""
    tool_id: str = ""
    enabled: bool = True
    permission_scope: dict[str, Any] = field(default_factory=dict)
