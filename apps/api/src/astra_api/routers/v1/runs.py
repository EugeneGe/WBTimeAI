"""``/runs`` 路由（W6 / T1-28；设计 §2.6 / §2.9）。

端点：

- ``GET /runs/{id}``：Run 详情（统一响应壳）；
- ``GET /runs/{id}/events``：事件**回放 / 续传**（``Last-Event-ID`` 头优先，``?after_seq``
  回退）；``Accept: text/event-stream`` → SSE（回放 + 接续实时），否则 JSON 列表；
- ``POST /runs/{id}/cancel``：取消一次 Run（置取消信号 + 终态 ``CANCELLED`` + 沙箱回收）。

Router **只**依赖 ``AppServices``（N-8）；**不** import ``astra_runtime`` /
``astra_conversation`` / ``astra_agent`` / ``astra_model``（A33 收紧）。
"""

from __future__ import annotations

from typing import Annotated

from astra_application import CancelAgentRunCommand, CancelAgentRunHandler
from astra_application.dto import RunDTO, RunEventDTO, UserDTO
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import RunEventResponse, RunResponse
from astra_api.sse.stream import StreamDeps, stream_run

router = APIRouter(prefix="/runs", tags=["runs"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_run_response(dto: RunDTO) -> RunResponse:
    """Run DTO → 响应。"""
    return RunResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        agent_id=dto.agent_id,
        agent_version_id=dto.agent_version_id,
        conversation_id=dto.conversation_id,
        user_id=dto.user_id,
        task_id=dto.task_id,
        trigger=dto.trigger,
        run_mode=dto.run_mode,
        status=dto.status,
        trace_id=dto.trace_id,
        started_at=dto.started_at,
        completed_at=dto.completed_at,
        duration_ms=dto.duration_ms,
        success=dto.success,
        error_type=dto.error_type,
        token_usage=dto.token_usage,
        cost=float(dto.cost) if dto.cost is not None else None,
        cost_status=dto.cost_status,
        error=dto.error,
    )


def _to_event_response(dto: RunEventDTO) -> RunEventResponse:
    """事件 DTO → 响应。"""
    return RunEventResponse(
        seq=dto.seq,
        type=dto.type,
        payload=dto.payload,
        trace_id=dto.trace_id,
        span_id=dto.span_id,
        created_at=dto.created_at,
    )


def _history_id(last_event_id: str | None, after_seq: int | None) -> int | None:
    """解析续传起点：``Last-Event-ID`` 头优先，``?after_seq`` 回退。"""
    if last_event_id:
        try:
            return int(last_event_id)
        except (TypeError, ValueError):
            return None
    return after_seq


def _wants_sse(accept: str | None) -> bool:
    """``Accept`` 协商（含 ``text/event-stream`` 或缺省 / ``*/*`` → SSE）。"""
    if not accept:
        return True
    lowered = accept.lower()
    return "text/event-stream" in lowered or "*/*" in lowered


def _stream_deps(services: AppServices) -> StreamDeps:
    """由 ``AppServices`` 抽取 SSE 流依赖。"""
    agent_run = services.agent_run
    return StreamDeps(
        event_bus=services.providers.event_bus,
        execute=agent_run.execute,
        list_events=agent_run.list_events,
        cancel=agent_run.cancel,
        run_status=agent_run.status,
    )


@router.get("/{run_id}", response_model=RunResponse, summary="Run 详情")
def get_run(
    run_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> RunResponse:
    """按 id 获取 Run 详情（不存在 → 404）。"""
    return _to_run_response(services.agent_run.get_run(run_id))


@router.get("/{run_id}/events", summary="Run 事件（回放 / 续传）")
def list_run_events(
    run_id: str,
    request: Request,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after_seq: Annotated[int | None, Query()] = None,
) -> Response:
    """返回 ``seq > last_event_id`` 的事件（``seq`` 升序，无重复无遗漏）。

    - ``Accept: text/event-stream`` → **SSE**（回放持久化事件；Run 仍活跃则接续实时）；
    - 否则 → JSON ``list[RunEventResponse]``。

    ``Last-Event-ID`` 头**优先**，``?after_seq`` **回退**（§2.4）；两者缺省 → 从头回放。
    **续传不走幂等键**（只读）。
    """
    start = _history_id(last_event_id, after_seq)
    if _wants_sse(request.headers.get("accept")):
        deps = _stream_deps(services)
        generator = stream_run(
            deps=deps,
            run_id=run_id,
            last_event_id=start,
            heartbeat_seconds=float(services.providers.settings.sse_heartbeat_seconds),
            start_execution=False,
        )
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(generator, media_type="text/event-stream", headers=headers)

    events = services.agent_run.list_events(run_id, start)
    return _json_events(events)


def _json_events(events: list[RunEventDTO]) -> Response:
    """事件 DTO 列表 → JSON 数组响应（由响应壳统一包裹）。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(content=[_to_event_response(dto).model_dump(mode="json") for dto in events])


@router.post("/{run_id}/cancel", response_model=RunResponse, summary="取消 Run")
def cancel_run(
    run_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> RunResponse:
    """取消一次 Run（置取消信号 + 终态 ``CANCELLED`` + 同步 ``task`` + 沙箱回收）。"""
    handler = CancelAgentRunHandler(services.agent_run)
    dto = handler.handle(CancelAgentRunCommand(run_id=run_id, tenant_id=_tenant_id(user)))
    return _to_run_response(dto)
