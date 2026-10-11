"""Workflow schema（请求 / 响应，W4 / T2-25）。

端点（``/workflows*``）：CRUD + ``/versions`` + ``/publish`` + ``/run``（SSE）+ 运行详情 / 取消。

🔴 ``/run`` 的 SSE 分支**不套统一响应壳**（总纲 §11.1 例外）——由响应壳中间件按
   ``content-type`` 跳过；HTTP JSON 分支仍走统一响应壳。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CreateWorkflowRequest",
    "UpdateWorkflowRequest",
    "WorkflowNodeInput",
    "WorkflowEdgeInput",
    "PublishWorkflowRequest",
    "RunWorkflowRequest",
    "WorkflowResponse",
    "WorkflowVersionResponse",
    "WorkflowRunResponse",
    "WorkflowNodeRunResponse",
    "WorkflowReplayResponse",
]


class CreateWorkflowRequest(BaseModel):
    """创建 Workflow 请求。"""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    workspace_id: str | None = None


class UpdateWorkflowRequest(BaseModel):
    """更新 Workflow 请求（缺省字段不变）。"""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, max_length=50)


class WorkflowNodeInput(BaseModel):
    """发布快照中的节点定义。"""

    key: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=50)
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeInput(BaseModel):
    """发布快照中的连边定义（``from`` / ``to`` 为 schema 保留名 → 别名）。"""

    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    condition: str | None = None


class PublishWorkflowRequest(BaseModel):
    """发布 WorkflowVersion 请求（一次发布 = 一个新版本）。"""

    nodes: list[WorkflowNodeInput] = Field(default_factory=list)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list)
    entry: str | None = None
    version: str | None = None


class RunWorkflowRequest(BaseModel):
    """运行 Workflow 请求。"""

    execution_mode: str = Field(default="INLINE", max_length=20)
    trigger: str = Field(default="user", max_length=20)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    """Workflow 响应。"""

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    status: str = "DRAFT"
    current_version_id: str | None = None
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowVersionResponse(BaseModel):
    """WorkflowVersion 响应（``definition`` 为完整图快照）。"""

    id: str
    workflow_id: str = ""
    version: str = ""
    status: str = "DRAFT"
    definition: dict[str, Any] = Field(default_factory=dict)
    created_by: str = ""
    created_at: datetime | None = None


class WorkflowRunResponse(BaseModel):
    """WorkflowRun 响应。"""

    id: str
    tenant_id: str | None = None
    workflow_version_id: str = ""
    trigger: str = "user"
    status: str = "PENDING"
    task_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class WorkflowNodeRunResponse(BaseModel):
    """WorkflowNodeRun 响应。"""

    id: str
    workflow_run_id: str = ""
    node_key: str = ""
    status: str = "PENDING"
    attempt: int = 1
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowReplayResponse(BaseModel):
    """运行重放快照响应（``I-P2-06`` 可重建视图）。"""

    run_id: str = ""
    workflow_id: str = ""
    workflow_version_id: str = ""
    status: str = ""
    trigger: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    task_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
