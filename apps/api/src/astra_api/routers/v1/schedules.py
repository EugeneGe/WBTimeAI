"""``/schedules`` 路由（W7 / T2-39；设计 §3.4 / §2.9）。

端点：

- ``POST /schedules`` · ``GET /schedules`` · ``GET /schedules/{id}`` ·
  ``PUT /schedules/{id}`` · ``DELETE /schedules/{id}``（CRUD）；
- ``POST /schedules/{id}/trigger``：**显式触发**一次（manual / webhook 路径），返回幂等
  ``task_id``。

Router **只**依赖 ``AppServices``（N-8）：**不** import ``astra_database`` / ``sqlalchemy`` /
``astra_task`` / ``astra_config``（``test_api_routers_have_no_orm_dependency``）；调度**经**
``services.schedules``（领域 ``ScheduleRepository`` Protocol）与 ``services.scheduler``
（组合根装配的 ``SchedulerTick``）取用，**不**直调 session / Provider。跨租户 / 不存在 → 404。

🔴 幂等（R6）：同一 ``(target_type, target_id, fire_time)`` 二次触发**只产生 1 个 task**——
   封装在 ``ScheduleRepository.get_or_create_task``，Router 无需感知。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, status

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.schedule import (
    CreateScheduleRequest,
    ScheduleResponse,
    TriggerScheduleResponse,
    UpdateScheduleRequest,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _tenant_id(user: Any) -> str:
    """取当前用户租户标识。"""
    return str(getattr(user, "tenant_id", "") or "")


def _to_schedule_response(schedule: object) -> ScheduleResponse:
    """``ScheduleSpec`` 实体 → 响应（泛化只读映射；不 import 实体类型）。"""
    return ScheduleResponse(
        id=str(getattr(schedule, "id")),  # noqa: B009 - 泛化只读映射
        tenant_id=getattr(schedule, "tenant_id", None),
        organization_id=getattr(schedule, "organization_id", None),
        workspace_id=getattr(schedule, "workspace_id", None),
        name=str(getattr(schedule, "name", "") or ""),
        target_type=str(getattr(schedule, "target_type", "") or ""),
        target_id=str(getattr(schedule, "target_id", "") or ""),
        trigger=str(getattr(schedule, "trigger", "") or ""),
        cron=getattr(schedule, "cron", None),
        event_type=getattr(schedule, "event_type", None),
        payload=dict(getattr(schedule, "payload", {}) or {}),
        enabled=bool(getattr(schedule, "enabled", True)),
        last_run_at=getattr(schedule, "last_run_at", None),
        next_run_at=getattr(schedule, "next_run_at", None),
        created_at=getattr(schedule, "created_at", None),
        updated_at=getattr(schedule, "updated_at", None),
    )


def _require_owned_schedule(services: AppServices, *, schedule_id: str, tenant_id: str) -> Any:
    """取当前租户下的调度，不存在 / 跨租户 → 404（隔离不变量 I-1）。"""
    schedule = services.schedules.get(schedule_id)
    if schedule is None or str(getattr(schedule, "tenant_id", "") or "") != tenant_id:
        raise DomainError("调度不存在", code=ErrorCode.NOT_FOUND, data={"schedule_id": schedule_id})
    return schedule


@router.post("", response_model=ScheduleResponse, status_code=201, summary="创建调度")
def create_schedule(
    payload: CreateScheduleRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ScheduleResponse:
    """创建一个调度（``ScheduleRepository.create`` 内部构造领域实体 + 校验）。"""
    schedule = services.schedules.create(
        tenant_id=_tenant_id(user),
        name=payload.name,
        target_type=payload.target_type,
        target_id=payload.target_id,
        trigger=payload.trigger,
        workspace_id=payload.workspace_id,
        organization_id=payload.organization_id,
        cron=payload.cron,
        event_type=payload.event_type,
        payload=dict(payload.payload),
        enabled=payload.enabled,
    )
    if payload.next_run_at is not None:
        schedule.next_run_at = payload.next_run_at
        schedule = services.schedules.update(schedule)
    return _to_schedule_response(schedule)


@router.get("", response_model=list[ScheduleResponse], summary="调度列表")
def list_schedules(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ScheduleResponse]:
    """列出当前租户的全部调度。"""
    return [
        _to_schedule_response(schedule)
        for schedule in services.schedules.list_by_tenant(_tenant_id(user))
    ]


@router.get("/{schedule_id}", response_model=ScheduleResponse, summary="调度详情")
def get_schedule(
    schedule_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ScheduleResponse:
    """按 id 获取调度（跨租户 / 不存在 → 404）。"""
    schedule = _require_owned_schedule(
        services, schedule_id=schedule_id, tenant_id=_tenant_id(user)
    )
    return _to_schedule_response(schedule)


@router.put("/{schedule_id}", response_model=ScheduleResponse, summary="更新调度")
def update_schedule(
    schedule_id: str,
    payload: UpdateScheduleRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ScheduleResponse:
    """更新调度（仅提供需变更字段；重校验词表 / 条件必填）。"""
    schedule = _require_owned_schedule(
        services, schedule_id=schedule_id, tenant_id=_tenant_id(user)
    )
    if payload.name is not None:
        schedule.name = payload.name
    if payload.trigger is not None:
        schedule.trigger = payload.trigger
    if payload.cron is not None:
        schedule.cron = payload.cron
    if payload.event_type is not None:
        schedule.event_type = payload.event_type
    if payload.payload is not None:
        schedule.payload = dict(payload.payload)
    if payload.enabled is not None:
        schedule.enabled = payload.enabled
    if payload.next_run_at is not None:
        schedule.next_run_at = payload.next_run_at
    schedule.assert_valid()
    schedule.touch()
    updated = services.schedules.update(schedule)
    return _to_schedule_response(updated)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除调度")
def delete_schedule(
    schedule_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> None:
    """删除调度（跨租户 / 不存在 → 404）。"""
    schedule = _require_owned_schedule(
        services, schedule_id=schedule_id, tenant_id=_tenant_id(user)
    )
    services.schedules.delete(schedule)


@router.post(
    "/{schedule_id}/trigger",
    response_model=TriggerScheduleResponse,
    summary="显式触发调度",
)
def trigger_schedule(
    schedule_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TriggerScheduleResponse:
    """**显式触发**一次调度（manual / webhook 路径），返回幂等 ``task_id``。

    经组合根装配的 ``services.scheduler``（``SchedulerTick``）触发；**幂等**（R6）：
    同一 ``(target_type, target_id, fire_time)`` 只产生 1 个 ``task``。
    """
    schedule = _require_owned_schedule(
        services, schedule_id=schedule_id, tenant_id=_tenant_id(user)
    )
    now = datetime.now(UTC)
    task_id = services.scheduler.fire_now(now, schedule)
    if task_id is None:  # pragma: no cover - fire_now 恒返回 task_id
        raise DomainError(
            "调度触发失败", code=ErrorCode.INTERNAL_ERROR, data={"schedule_id": schedule_id}
        )
    return TriggerScheduleResponse(schedule_id=schedule_id, task_id=task_id)
