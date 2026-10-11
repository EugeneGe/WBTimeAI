"""Agent schema（请求 / 响应，W6 / T1-28）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "AgentToolBind",
    "PublishRequest",
    "RunRequest",
    "AgentResponse",
    "AgentVersionResponse",
    "AgentToolResponse",
]


class CreateAgentRequest(BaseModel):
    """创建 Agent 请求。"""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: str = Field(default="PRIMARY", max_length=50)
    workspace_id: str | None = None


class UpdateAgentRequest(BaseModel):
    """更新 Agent 请求（缺省字段不变）。"""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, max_length=50)


class AgentToolBind(BaseModel):
    """AgentVersion ↔ Tool 绑定入参。"""

    tool_id: str = Field(min_length=1)
    permission_scope: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PublishRequest(BaseModel):
    """发布 AgentVersion 请求。

    注：``model_config`` 是 pydantic 保留名，故字段命名为 ``model_configuration``
    并设 ``alias="model_config"``（``populate_by_name`` 允许两者）。
    """

    model_config = ConfigDict(populate_by_name=True)

    system_prompt: str = ""
    model_configuration: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    tools: list[AgentToolBind] = Field(default_factory=list)


class RunRequest(BaseModel):
    """运行 Agent 请求。"""

    message: str = ""
    conversation_id: str | None = None
    workspace_id: str | None = None
    run_mode: str = Field(default="INLINE", max_length=20)


class AgentResponse(BaseModel):
    """Agent 响应。"""

    id: str
    tenant_id: str | None = None
    name: str
    workspace_id: str | None = None
    description: str | None = None
    type: str = "PRIMARY"
    status: str = "DRAFT"
    current_version_id: str | None = None
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentVersionResponse(BaseModel):
    """AgentVersion 响应（``model_config`` 以别名对外，见 :class:`PublishRequest`）。"""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    agent_id: str
    version: str
    system_prompt: str = ""
    model_configuration: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "PUBLISHED"
    created_by: str = ""
    created_at: datetime | None = None


class AgentToolResponse(BaseModel):
    """AgentVersion ↔ Tool 绑定响应。"""

    id: str
    tenant_id: str | None = None
    agent_version_id: str
    tool_id: str
    enabled: bool = True
    permission_scope: dict[str, Any] = Field(default_factory=dict)
