"""``/tasks`` 路由（W6 / T1-29；W10 / T2-49 扩展；R3 / T2-60 扩展远程面；R3 / T2-61 增变更审阅）。

端点（**既有 W10 / T2-60 行为保持不变**；R3 / T2-61 仅**加性**新增变更审阅端点）：

- ``GET  /tasks``：列表（``task_type`` / ``status`` 过滤 + 分页）；R3 增可选 ``project_id``
  ——提供时走**远程授权**分支（capability ``task.read``；跨范围 → 404）；
- ``GET  /tasks/{task_id}``：任务视图（复用 Phase 0 ``task``；跨租户 / 不存在 → 404，E3）；
- ``GET  /tasks/{task_id}/executions``：执行历史（``task_execution``，按 ``attempt`` 升序；E2）；
- ``POST /tasks/{task_id}/cancel``：取消（幂等；**远程任务**追加 ``EXECUTE + task.cancel``）；
- **R3 / T2-60 远程端点**：
  · ``POST /tasks``：远程提交（F-R2；``202 {task_id}``；``EXECUTE + task.submit``）；
  · ``GET  /tasks/{task_id}/attempts``：Attempt 列表（不透明 ``checkout_ref``，**不含宿主路径**）；
  · ``GET  /tasks/{task_id}/events``：事件回放 / 续读（不透明 cursor / ``Last-Event-ID``；
    过期 → ``EVENT_CURSOR_EXPIRED``）；
  · ``GET  /tasks/{task_id}/logs``：日志行；
  · ``GET  /tasks/{task_id}/diff``：某 Attempt **受限** Diff（``EXECUTE + git.diff``）；
  · ``GET  /tasks/{task_id}/artifacts``：Artifact 元数据；
  · ``GET  /tasks/{task_id}/artifacts/{name}``：Artifact 下载（**逐项重新鉴权**）。
- **R3 / T2-61 变更审阅端点**（C-2 链尾；**复用** T2-60 helper，**不改**其签名）：
  · ``POST /tasks/{task_id}/apply``：显式 Apply（F-R6；``EXECUTE + git.apply``；基线/脏树/冲突 → 409
    且保留原 Project / Attempt；**只**更新服务器 Project 目标分支，**不** Push）；
  · ``POST /tasks/{task_id}/push``：显式 Push（F-R7；**独立**权限 ``EXECUTE + git.push``）；
    须配置写凭证；拒任意 URL / 强推 / 删远端分支）。

Router **只**依赖 ``AppServices``（N-8，经 ``services.tasks`` / ``services.task_executions`` /
``services.remote_tasks`` / ``services.change_review`` 领域 / 应用用例）；**不** import
``astra_workspace`` / ``astra_database`` / ``sqlalchemy``（A33 / L-7 收紧）。
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from astra_application.dto import UserDTO
from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    ApplyTaskRequest,
    ApplyTaskResponse,
    DiffFileResponse,
    PushTaskRequest,
    PushTaskResponse,
    RemoteTaskSubmitRequest,
    RemoteTaskSubmitResponse,
    RemoteTaskViewResponse,
    TaskArtifactResponse,
    TaskAttemptResponse,
    TaskDiffResponse,
    TaskEventPageResponse,
    TaskEventResponse,
    TaskExecutionResponse,
    TaskLogResponse,
    TaskResponse,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _principal(user: UserDTO) -> Any:
    """由当前用户派生远程调用主体（``RemotePrincipal``）。"""
    from astra_workspace import RemotePrincipal

    return RemotePrincipal(tenant_id=_tenant_id(user), user_id=user.id)


def _to_task_response(task: Any) -> TaskResponse:
    """任务实体 → 响应（远程字段默认 ``None``；由 :func:`_with_remote_fields` 增补）。"""
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


def _remote_fields(task: Any) -> dict[str, Any]:
    """由任务载荷派生**加性**远程字段（非远程任务 → 空）。"""
    payload = dict(getattr(task, "payload", None) or {})
    project_id = payload.get("project_id")
    if not project_id:
        return {}
    return {"project_id": str(project_id)}


def _to_task_response_enriched(services: AppServices, task: Any) -> TaskResponse:
    """任务实体 → 响应（远程任务增补 Attempt 计数 / 不透明 ``checkout_ref``）。"""
    response = _to_task_response(task)
    fields = _remote_fields(task)
    if not fields:
        return response
    response.project_id = fields["project_id"]
    records = services.task_executions.list_by_task(str(task.task_id))
    ordered = sorted(records, key=lambda item: int(item.attempt))
    response.attempt_count = len(ordered)
    if ordered:
        latest = ordered[-1]
        response.checkout_ref = getattr(latest, "checkout_ref", None)
        response.base_commit = getattr(latest, "base_commit", None)
        response.result_commit = getattr(latest, "result_commit", None)
        response.environment_digest = getattr(latest, "environment_digest", None)
    return response


def _to_remote_view_response(view: Any) -> RemoteTaskViewResponse:
    """``RemoteTaskView`` → 响应。"""
    return RemoteTaskViewResponse(
        task_id=view.task_id,
        type=view.type,
        status=view.status,
        tenant_id=view.tenant_id,
        workspace_id=view.workspace_id,
        project_id=view.project_id,
        attempt_count=view.attempt_count,
        checkout_ref=view.checkout_ref,
        base_commit=view.base_commit,
        result_commit=view.result_commit,
        environment_digest=view.environment_digest,
        created_at=view.created_at,
        updated_at=view.updated_at,
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


def _is_remote_task(task: Any) -> bool:
    """是否为远程任务（载荷携带 ``project_id``）。"""
    return bool(dict(getattr(task, "payload", None) or {}).get("project_id"))


def _require_remote_service(services: AppServices) -> Any:
    """取远程 Task 服务（缺装配 → 结构化 503，不静默）。"""
    remote = getattr(services, "remote_tasks", None)
    if remote is None:
        raise DomainError(
            "远程 Task 能力未装配",
            code=ErrorCode.DEPENDENCY_MISSING,
            status_code=503,
            data={"capability": "remote_tasks"},
        )
    return remote


def _require_change_review_service(services: AppServices) -> Any:
    """取变更审阅服务（缺装配 → 结构化 503，不静默）。"""
    review = getattr(services, "change_review", None)
    if review is None:
        raise DomainError(
            "变更审阅能力未装配",
            code=ErrorCode.DEPENDENCY_MISSING,
            status_code=503,
            data={"capability": "change_review"},
        )
    return review


@router.get("", response_model=list[TaskResponse], summary="任务列表")
def list_tasks(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    task_type: Annotated[str | None, Query(description="按任务类型过滤（如 agent.run）")] = None,
    status: Annotated[str | None, Query(description="按任务状态过滤")] = None,
    project_id: Annotated[
        str | None, Query(description="按 Project 过滤（提供时走远程授权分支）")
    ] = None,
    workspace_id: Annotated[str | None, Query(description="按 Workspace 过滤（远程分支）")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[TaskResponse]:
    """列出任务。

    - 缺省（无 ``project_id``）→ **既有**租户列表（向后兼容）；
    - 提供 ``project_id`` → **远程授权**分支（capability ``task.read``；跨范围 → 404；不枚举）。
    """
    if project_id is not None:
        remote = _require_remote_service(services)
        views = remote.list_tasks(
            _principal(user),
            workspace_id=workspace_id,
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [_to_remote_view_as_task(view) for view in views]
    filters: dict[str, Any] = {"tenant_id": _tenant_id(user)}
    if task_type:
        filters["type"] = task_type
    if status:
        filters["status"] = status
    tasks = services.tasks.list(**filters)
    page = tasks[offset : offset + limit]
    return [_to_task_response(task) for task in page]


def _to_remote_view_as_task(view: Any) -> TaskResponse:
    """``RemoteTaskView`` → ``TaskResponse``（远程列表复用既有响应壳）。"""
    return TaskResponse(
        id=view.task_id,
        tenant_id=view.tenant_id,
        workspace_id=view.workspace_id,
        type=view.type,
        status=view.status,
        project_id=view.project_id,
        attempt_count=view.attempt_count,
        checkout_ref=view.checkout_ref,
        base_commit=view.base_commit,
        result_commit=view.result_commit,
        environment_digest=view.environment_digest,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


@router.post(
    "",
    response_model=RemoteTaskSubmitResponse,
    status_code=202,
    summary="远程提交任务",
)
def submit_remote_task(
    payload: RemoteTaskSubmitRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> RemoteTaskSubmitResponse:
    """远程提交一个 Task（F-R2；``EXECUTE + task.submit``；``202 {task_id}``）。"""
    from astra_workspace import RemoteTaskSpec

    remote = _require_remote_service(services)
    spec = RemoteTaskSpec(
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        agent_version_id=payload.agent_version_id,
        workflow_version_id=payload.workflow_version_id,
        requirement=payload.requirement,
        base_ref=payload.base_ref,
        environment_id=payload.environment_id,
        idempotency_key=payload.idempotency_key,
        limits=dict(payload.limits),
        created_by=user.id,
    )
    task_id = remote.submit(_principal(user), spec)
    return RemoteTaskSubmitResponse(task_id=str(task_id))


@router.get("/{task_id}", response_model=TaskResponse, summary="任务详情")
def get_task(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TaskResponse:
    """按 id 获取任务（跨租户 / 不存在 → 404；**远程任务**逐项鉴权）。

    远程任务（载荷携带 ``project_id``）走 ``services.remote_tasks``（``EXECUTE + task.read``
    逐次校验；越界 → 404，不泄漏存在性）；非远程任务行为**保持不变**。
    """
    task = _require_owned_task(services, task_id=task_id, tenant_id=_tenant_id(user))
    remote = getattr(services, "remote_tasks", None)
    if remote is not None and _is_remote_task(task):
        view = remote.get_task(_principal(user), task_id)
        return _to_remote_view_as_task(view)
    return _to_task_response_enriched(services, task)


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

    🔴 **远程任务**（载荷携带 ``project_id``）追加 ``EXECUTE + task.cancel`` 逐次校验
    （A-14）；**非远程任务**行为**保持不变**（向后兼容）。
    """
    task = _require_owned_task(services, task_id=task_id, tenant_id=_tenant_id(user))
    remote = getattr(services, "remote_tasks", None)
    if remote is not None and _is_remote_task(task):
        updated = remote.cancel(_principal(user), task_id)
        return _to_task_response_enriched(services, updated)
    if task.is_terminal:
        return _to_task_response(task)
    task.cancel()
    updated = services.tasks.update(task)
    return _to_task_response(updated)


# -- R3 / T2-60：远程 Task 子资源 --------------------------------------------


@router.get(
    "/{task_id}/attempts",
    response_model=list[TaskAttemptResponse],
    summary="任务 Attempt 列表（远程）",
)
def list_task_attempts(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[TaskAttemptResponse]:
    """列出任务 Attempt（``EXECUTE + task.read``；不透明 ``checkout_ref``，**不含宿主路径**）。"""
    remote = _require_remote_service(services)
    attempts = remote.list_attempts(_principal(user), task_id)
    return [
        TaskAttemptResponse(
            attempt=item.attempt,
            status=item.status,
            checkout_ref=item.checkout_ref,
            base_commit=item.base_commit,
            result_commit=item.result_commit,
            environment_digest=item.environment_digest,
            worker_id=item.worker_id,
            started_at=item.started_at,
            finished_at=item.finished_at,
            duration_ms=item.duration_ms,
            error=item.error,
            artifact_refs=item.artifact_refs,
        )
        for item in attempts
    ]


@router.get(
    "/{task_id}/events",
    response_model=TaskEventPageResponse,
    summary="任务事件（回放 / 续读）",
)
def list_task_events(
    task_id: str,
    request: Request,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    cursor: Annotated[str | None, Query(description="不透明续读游标（优先）")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> Response | TaskEventPageResponse:
    """事件回放 / 续读（``?cursor=`` / ``Last-Event-ID``；过期 → ``EVENT_CURSOR_EXPIRED``）。

    - ``Accept: text/event-stream`` → **SSE**（回放当前窗口内事件）；
    - 否则 → JSON ``TaskEventPageResponse``（含下一页不透明 cursor）。
    """
    remote = _require_remote_service(services)
    page = remote.list_events(_principal(user), task_id, cursor=cursor, last_event_id=last_event_id)
    if _wants_sse(request.headers.get("accept")):
        return StreamingResponse(
            _sse_frames(page), media_type="text/event-stream", headers=_SSE_HEADERS
        )
    return TaskEventPageResponse(
        events=[
            TaskEventResponse(
                seq=event.seq, type=event.type, payload=event.payload, created_at=event.created_at
            )
            for event in page.events
        ],
        next_cursor=page.next_cursor,
    )


#: SSE 响应头（禁用缓冲 / 缓存）。
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _wants_sse(accept: str | None) -> bool:
    """``Accept`` 协商（含 ``text/event-stream`` → SSE）。"""
    if not accept:
        return False
    return "text/event-stream" in accept.lower()


def _sse_frames(page: Any) -> Any:
    """把事件页编码为 SSE 帧序列（回放；收尾空帧标记 ``done``）。"""
    for event in page.events:
        data = json.dumps(event.payload or {}, ensure_ascii=False, default=str)
        yield f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"
    yield f"event: done\ndata: {json.dumps({'next_cursor': page.next_cursor})}\n\n"


@router.get(
    "/{task_id}/logs",
    response_model=list[TaskLogResponse],
    summary="任务日志（远程）",
)
def list_task_logs(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[TaskLogResponse]:
    """列出任务日志行（``EXECUTE + task.read``；**不含** Secret 明文）。"""
    remote = _require_remote_service(services)
    logs = remote.list_logs(_principal(user), task_id)
    return [
        TaskLogResponse(
            seq=item.seq,
            attempt=item.attempt,
            level=item.level,
            message=item.message,
            created_at=item.created_at,
        )
        for item in logs
    ]


@router.get(
    "/{task_id}/diff",
    response_model=TaskDiffResponse,
    summary="任务 Diff（受限，远程）",
)
def get_task_diff(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    attempt: Annotated[int | None, Query(ge=1, description="Attempt 序号（缺省取最近）")] = None,
) -> TaskDiffResponse:
    """返回某 Attempt 的**受限** Diff（``EXECUTE + git.diff``；不 Apply / 不 Push）。

    🔴 **R5 补全轮（F4 / R5A-02）裁定**：远程 API 的 Diff **唯一出口** =
    ``ChangeReviewService.diff``（经 Sandbox、真实文件摘要 + 逐次授权审计）；
    ``available=False``（缺 ``base/result`` 提交）→ **200 降级**（``files=[]``，不报错）。
    此前误接占位 ``RemoteTaskService.get_diff``（恒 ``files=[]``）——
    现统一至变更审阅服务的真实出口。
    """
    review = _require_change_review_service(services)
    diff = review.diff(_principal(user), task_id, attempt=attempt)
    return TaskDiffResponse(
        attempt=diff.attempt,
        checkout_ref=diff.checkout_ref,
        base_commit=diff.base_commit,
        result_commit=diff.result_commit,
        available=diff.available,
        files=[
            DiffFileResponse(
                path=item.path,
                change_type=item.change_type,
                additions=item.additions,
                deletions=item.deletions,
            )
            for item in diff.files
        ],
        truncated=diff.truncated,
    )


@router.get(
    "/{task_id}/artifacts",
    response_model=list[TaskArtifactResponse],
    summary="任务 Artifact 元数据（远程）",
)
def list_task_artifacts(
    task_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    attempt: Annotated[int | None, Query(ge=1, description="Attempt 序号（缺省取最近）")] = None,
) -> list[TaskArtifactResponse]:
    """列出某 Attempt 的 Artifact 元数据（``EXECUTE + task.read``）。"""
    remote = _require_remote_service(services)
    artifacts = remote.list_artifacts(_principal(user), task_id, attempt=attempt)
    return [
        TaskArtifactResponse(
            name=item.name, ref=item.ref, size=item.size, content_type=item.content_type
        )
        for item in artifacts
    ]


@router.get(
    "/{task_id}/artifacts/{name}",
    summary="下载 Artifact（远程，逐项鉴权）",
)
def download_task_artifact(
    task_id: str,
    name: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    attempt: Annotated[int | None, Query(ge=1, description="Attempt 序号（缺省取最近）")] = None,
) -> Response:
    """下载 Artifact（**逐项重新鉴权**：``EXECUTE + artifact.download``）。"""
    remote = _require_remote_service(services)
    download = remote.download_artifact(_principal(user), task_id, name=name, attempt=attempt)
    safe_name = name.replace('"', "")
    return Response(
        content=download.content,
        media_type=download.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# -- R3 / T2-61：变更审阅（显式 Apply / 显式 Push；C-2 链尾；复用 T2-60 helper） ------


@router.post(
    "/{task_id}/apply",
    response_model=ApplyTaskResponse,
    summary="显式应用变更（不 Push，F-R6）",
)
def apply_task_change(
    task_id: str,
    payload: ApplyTaskRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ApplyTaskResponse:
    """把 Attempt 结果**仅**应用到服务器 Project 目标分支（F-R6；``EXECUTE + git.apply``）。

    **不** Push。跨租户 / 越界 → 404；缺 capability → 403；目标前进 / 脏工作树 / 冲突 → 409
    （**保留原 Project / Attempt**）；未装配 → 503。
    """
    review = _require_change_review_service(services)
    result = review.apply(_principal(user), task_id, target_ref=payload.target_ref)
    return ApplyTaskResponse(
        task_id=result.task_id,
        target_ref=result.target_ref,
        base_commit=result.base_commit,
        result_commit=result.result_commit,
        applied_commit=result.applied_commit,
        already_applied=result.already_applied,
    )


@router.post(
    "/{task_id}/push",
    response_model=PushTaskResponse,
    summary="显式推送（独立权限，F-R7）",
)
def push_task_change(
    task_id: str,
    payload: PushTaskRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PushTaskResponse:
    """把服务器 Project 目标分支推送到远端（F-R7；**独立**权限 ``EXECUTE + git.push``）。

    跨租户 / 越界 → 404；缺 capability → 403；任意 URL / 强推 / 删分支 → 403；
    未配置写凭证 → 422；推送被拒 → 409；未装配 → 503。
    """
    review = _require_change_review_service(services)
    result = review.push(
        _principal(user),
        task_id,
        target_ref=payload.target_ref,
        remote=payload.remote,
    )
    return PushTaskResponse(
        task_id=result.task_id,
        target_ref=result.target_ref,
        remote=result.remote,
        ref=result.ref,
        pushed=result.pushed,
        already_up_to_date=result.already_up_to_date,
    )
