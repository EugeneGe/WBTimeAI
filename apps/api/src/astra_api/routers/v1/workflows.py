"""``/workflows`` 路由（W4 / T2-25；设计 §2.5 / §2.12 / §2.16）。

端点：

- ``POST /workflows`` 创建；``GET /workflows`` 列表；``GET/PUT/DELETE /workflows/{id}``
  详情 / 更新 / 删除；
- ``GET /workflows/{id}/versions`` 版本列表；``POST /workflows/{id}/publish`` 发布新版本；
- ``POST /workflows/{id}/run`` **运行 Workflow**（``Accept: text/event-stream`` → SSE 流；
  显式排除 SSE / ``mode=QUEUED`` → 统一响应壳）；
- ``GET /workflows/{id}/runs/{run_id}`` 运行详情（重放快照，``I-P2-06``）；
- ``POST /workflows/{id}/runs/{run_id}/cancel`` 取消运行。

Router **只**做校验 → 调用 ``AppServices.workflow`` → 映射响应 / 建立 SSE（N-8）；
**不** import ``astra_workflow`` / ``astra_runtime`` / ORM；事件订阅落在
:mod:`astra_api.sse.stream`（``StreamDeps`` 复用，``encoder.py`` 不改）。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_application.dto import (
    UserDTO,
    WorkflowDTO,
    WorkflowNodeRunDTO,
    WorkflowRunDTO,
    WorkflowVersionDTO,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    CreateWorkflowRequest,
    PublishWorkflowRequest,
    RunWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowNodeRunResponse,
    WorkflowReplayResponse,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowVersionResponse,
)
from astra_api.sse.stream import StreamDeps, stream_run

router = APIRouter(prefix="/workflows", tags=["workflows"])

#: 运行形态字面值（与 ``astra_workflow.run`` 常量同口径；Router 不 import 能力包）。
_MODE_INLINE = "INLINE"
_MODE_QUEUED = "QUEUED"


# -- 映射辅助 ---------------------------------------------------------------


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_workflow_response(dto: WorkflowDTO) -> WorkflowResponse:
    """Workflow DTO → 响应。"""
    return WorkflowResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        workspace_id=dto.workspace_id,
        name=dto.name,
        description=dto.description,
        status=dto.status,
        current_version_id=dto.current_version_id,
        created_by=dto.created_by,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )


def _to_version_response(dto: WorkflowVersionDTO) -> WorkflowVersionResponse:
    """WorkflowVersion DTO → 响应。"""
    return WorkflowVersionResponse(
        id=dto.id,
        workflow_id=dto.workflow_id,
        version=dto.version,
        status=dto.status,
        definition=dict(dto.definition or {}),
        created_by=dto.created_by,
        created_at=dto.created_at,
    )


def _to_run_response(dto: WorkflowRunDTO) -> WorkflowRunResponse:
    """WorkflowRun DTO → 响应。"""
    return WorkflowRunResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        workflow_version_id=dto.workflow_version_id,
        trigger=dto.trigger,
        status=dto.status,
        task_id=dto.task_id,
        input=dict(dto.input or {}),
        output=dict(dto.output) if dto.output is not None else None,
        started_at=dto.started_at,
        completed_at=dto.completed_at,
        error=dto.error,
    )


def _to_node_run_response(dto: WorkflowNodeRunDTO) -> WorkflowNodeRunResponse:
    """WorkflowNodeRun DTO → 响应。"""
    return WorkflowNodeRunResponse(
        id=dto.id,
        workflow_run_id=dto.workflow_run_id,
        node_key=dto.node_key,
        status=dto.status,
        attempt=dto.attempt,
        agent_run_id=dto.agent_run_id,
        tool_call_id=dto.tool_call_id,
        approval_id=dto.approval_id,
        input=dict(dto.input or {}),
        output=dict(dto.output or {}),
        started_at=dto.started_at,
        completed_at=dto.completed_at,
    )


def _definition_from(payload: PublishWorkflowRequest) -> dict[str, Any]:
    """由请求体构造**完整图快照** ``workflow_version.definition``。"""
    return {
        "nodes": [
            {
                "key": node.key,
                "type": node.type,
                "config": dict(node.config or {}),
                "position": dict(node.position or {}),
            }
            for node in payload.nodes
        ],
        "edges": [
            {
                "from": edge.from_node,
                "to": edge.to_node,
                "condition": edge.condition,
            }
            for edge in payload.edges
        ],
        "entry": payload.entry,
    }


# -- Workflow CRUD ----------------------------------------------------------


@router.post("", response_model=WorkflowResponse, status_code=201, summary="创建 Workflow")
def create_workflow(
    payload: CreateWorkflowRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowResponse:
    """创建 Workflow（``DRAFT``，无当前版本）。"""
    dto = services.workflow.create(
        tenant_id=_tenant_id(user),
        name=payload.name,
        created_by=user.id,
        description=payload.description,
        workspace_id=payload.workspace_id,
    )
    return _to_workflow_response(dto)


@router.get("", response_model=list[WorkflowResponse], summary="Workflow 列表")
def list_workflows(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[WorkflowResponse]:
    """列出当前租户下的全部 Workflow。"""
    dtos = services.workflow.list_workflows(tenant_id=_tenant_id(user))
    return [_to_workflow_response(dto) for dto in dtos]


@router.get("/{workflow_id}", response_model=WorkflowResponse, summary="Workflow 详情")
def get_workflow(
    workflow_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowResponse:
    """按 id 获取 Workflow（跨租户 / 不存在 → 404）。"""
    return _to_workflow_response(services.workflow.get(workflow_id, tenant_id=_tenant_id(user)))


@router.put("/{workflow_id}", response_model=WorkflowResponse, summary="更新 Workflow")
def update_workflow(
    workflow_id: str,
    payload: UpdateWorkflowRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowResponse:
    """更新 Workflow 名称 / 描述 / 状态（缺省字段不变）。"""
    dto = services.workflow.update(
        workflow_id,
        tenant_id=_tenant_id(user),
        name=payload.name,
        description=payload.description,
        status=payload.status,
    )
    return _to_workflow_response(dto)


@router.delete("/{workflow_id}", status_code=204, summary="删除 Workflow")
def delete_workflow(
    workflow_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """删除 Workflow（跨租户 / 不存在 → 404）。"""
    services.workflow.delete(workflow_id, tenant_id=_tenant_id(user))
    return Response(status_code=204)


# -- 版本 / 发布 ------------------------------------------------------------


@router.get(
    "/{workflow_id}/versions",
    response_model=list[WorkflowVersionResponse],
    summary="Workflow 版本列表",
)
def list_versions(
    workflow_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[WorkflowVersionResponse]:
    """列出某 Workflow 的全部版本（**不可变快照**）。"""
    dtos = services.workflow.list_versions(workflow_id, tenant_id=_tenant_id(user))
    return [_to_version_response(dto) for dto in dtos]


@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowVersionResponse,
    status_code=201,
    summary="发布 WorkflowVersion",
)
def publish_workflow(
    workflow_id: str,
    payload: PublishWorkflowRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowVersionResponse:
    """发布一个新版本（一次发布 = 一个新 ``workflow_version``）并把 Workflow 置 ``ACTIVE``。"""
    dto = services.workflow.publish(
        workflow_id,
        tenant_id=_tenant_id(user),
        created_by=user.id,
        definition=_definition_from(payload),
        version=payload.version,
    )
    return _to_version_response(dto)


# -- 运行（SSE / JSON 降级） ------------------------------------------------


@router.post("/{workflow_id}/run", summary="运行 Workflow（SSE 流式 / JSON 降级）")
def run_workflow(
    workflow_id: str,
    payload: RunWorkflowRequest,
    request: Request,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """运行一次 Workflow。

    - ``Accept: text/event-stream``（或缺省 / ``*/*``）→ **SSE 流**（复用既有
      ``workflow.*`` / ``approval.*`` 通道 + 心跳）；
    - ``mode=QUEUED`` 或显式排除 SSE（如 ``application/json``）→ 统一响应壳。

    W8-3 / A38：本路由为**同步** ``def``（体内无 ``await``）——FastAPI 将同步路由置于外部
    线程池执行，使「建运行 / 建任务」等同步 DB I/O **不再阻塞事件循环**（对齐 ``agents.py``）。
    """
    tenant_id = _tenant_id(user)
    mode = payload.execution_mode or _MODE_INLINE
    if mode == _MODE_QUEUED:
        dto = services.workflow.run(
            workflow_id,
            tenant_id=tenant_id,
            execution_mode=_MODE_QUEUED,
            run_input=payload.input,
            trigger=payload.trigger,
            user_id=user.id,
        )
        return _json_run_digest(dto)

    created = services.workflow.open_run(
        workflow_id,
        tenant_id=tenant_id,
        execution_mode=_MODE_INLINE,
        run_input=payload.input,
        trigger=payload.trigger,
        user_id=user.id,
    )
    return _respond(request, services, created, start_execution=True)


@router.get(
    "/{workflow_id}/runs/{run_id}",
    response_model=WorkflowReplayResponse,
    summary="Workflow 运行详情（重放快照）",
)
def get_workflow_run(
    workflow_id: str,
    run_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowReplayResponse:
    """返回一次运行的**重放快照**（``workflow_run`` + ``workflow_node_run``，``I-P2-06``）。"""
    # ``workflow_id`` 参与路径语义；运行归属经租户隔离在服务层校验。
    services.workflow.get(workflow_id, tenant_id=_tenant_id(user))
    return WorkflowReplayResponse.model_validate(services.workflow.replay(run_id))


@router.post(
    "/{workflow_id}/runs/{run_id}/cancel",
    response_model=WorkflowRunResponse,
    summary="取消 Workflow 运行",
)
def cancel_workflow_run(
    workflow_id: str,
    run_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> WorkflowRunResponse:
    """取消一次运行（置终态 ``CANCELLED``）。"""
    services.workflow.get(workflow_id, tenant_id=_tenant_id(user))
    return _to_run_response(services.workflow.cancel(run_id))


# -- 内部辅助 ---------------------------------------------------------------


def _wants_sse(accept: str | None) -> bool:
    """``Accept`` 协商：含 ``text/event-stream`` 或缺省 / ``*/*`` → SSE（§2.3）。"""
    if not accept:
        return True
    lowered = accept.lower()
    return "text/event-stream" in lowered or "*/*" in lowered


def _stream_deps(services: AppServices) -> StreamDeps:
    """由 ``AppServices`` 抽取 SSE 流依赖（复用 ``WorkflowService`` 四回调）。"""
    workflow = services.workflow
    return StreamDeps(
        event_bus=services.providers.event_bus,
        execute=workflow.execute,
        list_events=workflow.list_events,
        cancel=workflow.cancel,
        run_status=workflow.status,
    )


def _respond(
    request: Request,
    services: AppServices,
    run: WorkflowRunDTO,
    *,
    start_execution: bool,
) -> Response:
    """依 ``Accept`` 返回 SSE 流或 JSON 降级响应。"""
    if _wants_sse(request.headers.get("accept")):
        deps = _stream_deps(services)
        generator = stream_run(
            deps=deps,
            run_id=run.id,
            heartbeat_seconds=float(services.providers.settings.sse_heartbeat_seconds),
            start_execution=start_execution,
        )
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(generator, media_type="text/event-stream", headers=headers)

    if start_execution:
        services.workflow.execute(run.id)
    final = services.workflow.get_run(run.id)
    return _json_run_digest(final)


def _json_run_digest(dto: WorkflowRunDTO) -> Response:
    """构造 JSON 降级响应（``data`` 为运行摘要）。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content={
            "run_id": dto.id,
            "workflow_version_id": dto.workflow_version_id,
            "status": dto.status,
            "task_id": dto.task_id,
            "error": dto.error,
        }
    )
