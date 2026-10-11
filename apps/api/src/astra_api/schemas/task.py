"""Task schema（任务视图，W6 / T1-29；W10-E2 增执行记录视图）。

- :class:`TaskResponse`：复用 Phase 0 ``task`` 视图；
- :class:`TaskExecutionResponse`：``task_execution`` 一行视图（W10 / T2-49 收尾 · E2；
  字段对齐 ``astra_task.TaskExecutionRecord`` 实体）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["TaskResponse", "TaskExecutionResponse"]


class TaskResponse(BaseModel):
    """任务响应（``agent.run`` 任务的对外视图）。"""

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
