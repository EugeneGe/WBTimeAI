"""Schedule schema（调度 CRUD 视图；W7 / T2-39）。

面向 ``/schedules`` 的请求 / 响应模型。**触发类型 / 目标类型词表**与
``astra_task.scheduler.triggers`` 冻结契约同口径（``cron`` / ``event`` / ``webhook`` /
``manual``；``agent`` / ``workflow``），此处以**字面值**出现（Router 层不 import ``astra_task``，
守 ``test_api_routers_have_no_orm_dependency``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateScheduleRequest",
    "UpdateScheduleRequest",
    "ScheduleResponse",
    "TriggerScheduleResponse",
]


class CreateScheduleRequest(BaseModel):
    """创建调度请求（字段与 ``schedule`` 表 / ``ScheduleSpec`` 对齐）。"""

    name: str = Field(..., min_length=1, description="调度名称（租户 + 目标内唯一）")
    target_type: str = Field(default="agent", description="目标类型：agent / workflow")
    target_id: str = Field(..., min_length=1, description="目标标识（Agent / Workflow id）")
    trigger: str = Field(default="manual", description="触发类型：cron / event / webhook / manual")
    workspace_id: str | None = Field(default=None, description="归属 Workspace（可空）")
    organization_id: str | None = Field(default=None, description="组织归属（可空）")
    cron: str | None = Field(default=None, description="cron 表达式（trigger=cron 时必填）")
    event_type: str | None = Field(default=None, description="事件类型（trigger=event 时必填）")
    payload: dict[str, Any] = Field(default_factory=dict, description="触发载荷")
    enabled: bool = Field(default=True, description="是否启用")
    next_run_at: datetime | None = Field(default=None, description="下次触发时间（可空）")


class UpdateScheduleRequest(BaseModel):
    """更新调度请求（仅传需变更字段；``None`` 视为不变）。"""

    name: str | None = Field(default=None, min_length=1)
    trigger: str | None = Field(default=None, description="cron / event / webhook / manual")
    cron: str | None = Field(default=None)
    event_type: str | None = Field(default=None)
    payload: dict[str, Any] | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    next_run_at: datetime | None = Field(default=None)


class ScheduleResponse(BaseModel):
    """调度响应（``ScheduleSpec`` 的对外视图）。"""

    id: str
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    target_type: str = "agent"
    target_id: str = ""
    trigger: str = "manual"
    cron: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TriggerScheduleResponse(BaseModel):
    """显式触发调度的响应（返回幂等创建 / 命中的 ``task_id``）。"""

    schedule_id: str
    task_id: str
