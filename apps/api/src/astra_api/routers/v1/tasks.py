"""``/tasks`` 路由（W6 / T1-29；W10 / T2-49 扩展：列表 / 取消 / 执行历史）。

端点：

- ``GET  /tasks``：列表（``task_type`` / ``status`` 过滤 + 分页；``tenant_id`` 取当前用户）；
- ``GET  /tasks/{task_id}``：任务视图（复用 Phase 0 ``task``；**跨租户 / 不存在 → 404**，E3）；
- ``GET  /tasks/{task_id}/executions``：执行历史（``task_execution``，按 ``attempt`` 升序；E2）；
- ``POST /tasks/{task_id}/cancel``：取消（委托 ``Task.cancel()``；终态**幂等**返回既有状态）。

Router **只**依赖 ``AppServices``（N-8，经 ``services.tasks`` /
``services.task_executions`` 领域 Protocol）；**不** import ``astra_database`` /
``sqlalchemy``（A33 收紧）。

🔴 列表按租户过滤：经领域 ``TaskRepository.list(**filters)``（``tenant_id`` 列已存在，
   ``SqlTaskRepository.list`` 支持等值过滤）——**无需** ``list_by_tenant`` / 新迁移
   （裁定 R-W10-04「不足则加性新增」的前置核实结论：现有接口已足）。
🔴 详情 / 执行历史 / 取消统一「跨租户 / 不存在 → 404（不泄漏存在性）」（I-1 硬隔离；E3）。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_application.dto import UserDTO
from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import TaskExecutionResponse, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_task_response(task: Any) -> TaskResponse:
    """任务实体 → 响应。"""
    return TaskResponse(
        id=str(task.task_id),
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        type=str(task.type),
        status=str(task.status),
        priority=int(task.priority),
        execution_mode=str(task.execution_mode),
        payload=dict(task.payload or {}),
        result=task.result,
        error=task.error,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _to_execution_response(record: Any) -> TaskExecutionResponse:
    """执行记录实体 → 响应。"""
    return TaskExecutionResponse(
        id=str(record.id),
        task_id=str(record.task_id),
        attempt=int(record.attempt),
        worker_id=record.worker_id,
        status=str(record.status),
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        error=record.error,
    )


def _require_owned_task(services: AppServices, *, task_id: str, tenant_id: str) -> Any:
    """取当前租户下的任务，不存在 / 跨租户 → 404（隔离 I-1，不泄漏存在性）。"""
    task = services.tasks.get(task_id)
    if task is None or str(getattr(task, "tenant_id", "") or "") != tenant_id:
        raise DomainError("任务不存在", code=ErrorCode.NOT_FOUND, data={"task_id": task_id})
    return task


@router.get("", response_model=list[TaskResponse], summary="任务列表")
def list_tasks(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    task_type: Annotated[str | None, Query(description="按任务类型过滤（如 agent.run）")] = None,
    status: Annotated[str | None, Query(description="按任务状态过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[TaskResponse]:
    """列出当前租户的任务（可类型 / 状态过滤；分页）。"""
    filters: dict[str, Any] = {"tenant_id": _tenant_id(user)}
    if task_type:
        filters["type"] = task_type
    if status:
        filters["status"] = status
    tasks = services.tasks.list(**filters)
    page = tasks[offset : offset + limit]
    return [_to_task_response(task) for task in page]


@router.get("/{task_id}", response_model=TaskResponse, summary="任务详情")
def get_task(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TaskResponse:
    """按 id 获取任务（跨租户 / 不存在 → 404）。"""
    task = _require_owned_task(services, task_id=task_id, tenant_id=_tenant_id(user))
    return _to_task_response(task)


@router.get(
    "/{task_id}/executions",
    response_model=list[TaskExecutionResponse],
    summary="任务执行历史",
)
def list_task_executions(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[TaskExecutionResponse]:
    """列出任务的执行记录（``task_execution``，按 ``attempt`` 升序；无记录 → 空列表）。

    跨租户 / 不存在 → 404（先校验任务归属，再取执行历史）。
    """
    _require_owned_task(services, task_id=task_id, tenant_id=_tenant_id(user))
    records = services.task_executions.list_by_task(task_id)
    return [_to_execution_response(record) for record in records]


@router.post("/{task_id}/cancel", response_model=TaskResponse, summary="取消任务")
def cancel_task(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TaskResponse:
    """取消任务（``CREATED | PENDING | RUNNING → CANCELLED``；终态**幂等**返回既有状态）。

    跨租户 / 不存在 → 404；已终态（``SUCCESS`` / ``FAILED`` / ``CANCELLED``）→ 直接返回既有状态。
    """
    task = _require_owned_task(services, task_id=task_id, tenant_id=_tenant_id(user))
    if task.is_terminal:
        return _to_task_response(task)
    task.cancel()
    updated = services.tasks.update(task)
    return _to_task_response(updated)
