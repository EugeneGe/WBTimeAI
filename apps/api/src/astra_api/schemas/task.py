"""Task schema（任务视图，W6 / T1-29；W10-E2 增执行记录视图；R3 / T2-60 增远程视图）。

- :class:`TaskResponse`：复用 Phase 0 ``task`` 视图（R3 / T2-60 **加性**补充远程字段，默认
  ``None``；对既有非远程任务保持不变）；
- :class:`TaskExecutionResponse`：``task_execution`` 一行视图（W10 / T2-49 收尾 · E2）；
- **R3 / T2-60 远程视图**：提交请求 / 任务快照 / Attempt / Event（含不透明 cursor）/ Log /
  Diff / Artifact；🔴 一律**不含**宿主绝对路径（只暴露不透明 ``checkout_ref``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "TaskResponse",
    "TaskExecutionResponse",
    # R3 / T2-60
    "RemoteTaskSubmitRequest",
    "RemoteTaskSubmitResponse",
    "RemoteTaskViewResponse",
    "TaskAttemptResponse",
    "TaskEventResponse",
    "TaskEventPageResponse",
    "TaskLogResponse",
    "DiffFileResponse",
    "TaskDiffResponse",
    "TaskArtifactResponse",
]


class TaskResponse(BaseModel):
    """任务响应（``agent.run`` 任务的对外视图）。

    🔴 R3 / T2-60 **加性**远程字段（``project_id`` / ``attempt_count`` / ``checkout_ref`` /
    ``base_commit`` / ``result_commit`` / ``environment_digest``）：默认 ``None``；仅远程任务
    填充。``checkout_ref`` 为**不透明**句柄（**不含**宿主绝对路径）。
    """

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    type: str = ""
    status: str = "CREATED"
    priority: int = 0
    execution_mode: str = "INLINE"
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # -- R3 / T2-60 远程字段（加性，默认 None） -----------------------------
    project_id: str | None = None
    attempt_count: int | None = None
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None


class TaskExecutionResponse(BaseModel):
    """任务执行记录响应（``task_execution``；W10-E2；字段对齐领域实体）。"""

    id: str
    task_id: str = ""
    attempt: int = Field(default=1, description="尝试序号（从 1 起）")
    worker_id: str | None = None
    status: str = "RUNNING"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None


# -- R3 / T2-60：远程 Task 视图 ----------------------------------------------


class RemoteTaskSubmitRequest(BaseModel):
    """远程任务提交请求（F-R2；``agent_version_id`` | ``workflow_version_id`` 二选一）。"""

    workspace_id: str = Field(min_length=1, description="归属 Workspace 标识")
    project_id: str = Field(min_length=1, description="归属 Project 标识")
    agent_version_id: str | None = Field(default=None, description="固定 Agent 版本")
    workflow_version_id: str | None = Field(default=None, description="固定 Workflow 版本")
    requirement: str = Field(default="", description="需求文本（用户输入）")
    base_ref: str | None = Field(default=None, description="基准引用（分支 / tag / 提交）")
    environment_id: str | None = Field(default=None, description="环境标识（可空）")
    idempotency_key: str | None = Field(default=None, description="幂等键（同键同体复用）")
    limits: dict[str, Any] = Field(default_factory=dict, description="资源限额（JSON）")


class RemoteTaskSubmitResponse(BaseModel):
    """远程任务提交响应（``202 {task_id}``）。"""

    task_id: str


class RemoteTaskViewResponse(BaseModel):
    """远程任务状态快照视图（**不含宿主路径**）。"""

    task_id: str
    type: str = ""
    status: str = "CREATED"
    tenant_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    attempt_count: int = 0
    checkout_ref: str | None = Field(default=None, description="不透明 checkout 句柄")
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskAttemptResponse(BaseModel):
    """Attempt 视图（**不含宿主路径**）。"""

    attempt: int = 1
    status: str = ""
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None
    worker_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    artifact_refs: dict[str, Any] | None = None


class TaskEventResponse(BaseModel):
    """任务级事件帧（``seq`` 单调；可经不透明 cursor 续读）。"""

    seq: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class TaskEventPageResponse(BaseModel):
    """事件分页响应（含下一页**不透明** cursor）。"""

    events: list[TaskEventResponse] = Field(default_factory=list)
    next_cursor: str = ""


class TaskLogResponse(BaseModel):
    """任务日志行。"""

    seq: int
    attempt: int = 1
    level: str = "info"
    message: str = ""
    created_at: datetime | None = None


class DiffFileResponse(BaseModel):
    """受限 Diff 的单个文件变更摘要。"""

    path: str
    change_type: str = "modified"
    additions: int = 0
    deletions: int = 0


class TaskDiffResponse(BaseModel):
    """某 Attempt 的**受限** Diff（T2-60 只读；Apply / Push 归 T2-61）。"""

    attempt: int = 1
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    available: bool = False
    files: list[DiffFileResponse] = Field(default_factory=list)
    truncated: bool = False


class TaskArtifactResponse(BaseModel):
    """Artifact 元数据（下载**逐项重新鉴权**）。"""

    name: str
    ref: str
    size: int | None = None
    content_type: str | None = None
