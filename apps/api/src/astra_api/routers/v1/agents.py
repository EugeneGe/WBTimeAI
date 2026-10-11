"""``/agents`` 路由（W6 / T1-28；设计 §2.2 / §2.9 / §2.13）。

端点：

- ``POST /agents`` 创建 Agent；``GET /agents`` 列表；``GET/PUT /agents/{id}`` 详情 / 更新；
- ``GET /agents/{id}/versions`` 版本列表；``POST /agents/{id}/publish`` 发布新版本；
- ``POST /agents/{id}/run`` **运行 Agent**（``Accept: text/event-stream`` → SSE 流；
  显式排除 SSE → 统一响应壳 + 终态 Run）。

Router **只**做校验 → 调用 Application → 映射响应 / 建立 SSE（N-8）；
**不** import ``astra_runtime`` / ``astra_conversation`` / ``astra_agent`` / ``astra_model``
（A33 收紧）；事件订阅落在 :mod:`astra_api.sse.stream`。
"""

from __future__ import annotations

from typing import Annotated

from astra_application import (
    CreateAgentCommand,
    CreateAgentHandler,
    CreateAgentTaskCommand,
    CreateAgentTaskHandler,
    GetAgentHandler,
    GetAgentQuery,
    ListAgentsHandler,
    ListAgentsQuery,
    PublishAgentVersionCommand,
    PublishAgentVersionHandler,
    UpdateAgentCommand,
    UpdateAgentHandler,
)
from astra_application.dto import AgentDTO, AgentVersionDTO, RunDTO, UserDTO
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.idempotency import IdempotencyKey, prepare_idempotency
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    AgentResponse,
    AgentToolBind,
    AgentVersionResponse,
    CreateAgentRequest,
    PublishRequest,
    RunRequest,
    UpdateAgentRequest,
)
from astra_api.sse.stream import StreamDeps, stream_run

router = APIRouter(prefix="/agents", tags=["agents"])


# -- 映射辅助 ---------------------------------------------------------------


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_agent_response(dto: AgentDTO) -> AgentResponse:
    """Agent DTO → 响应。"""
    return AgentResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        name=dto.name,
        workspace_id=dto.workspace_id,
        description=dto.description,
        type=dto.type,
        status=dto.status,
        current_version_id=dto.current_version_id,
        created_by=dto.created_by,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )


def _to_version_response(dto: AgentVersionDTO) -> AgentVersionResponse:
    """AgentVersion DTO → 响应（``model_config`` 以别名对外）。"""
    return AgentVersionResponse(
        id=dto.id,
        agent_id=dto.agent_id,
        version=dto.version,
        system_prompt=dto.system_prompt,
        # 经别名（= schema 字段 ``model_configuration``）传入，规避 pydantic 保留名。
        model_config=dto.model_config,
        runtime_config=dto.runtime_config,
        status=dto.status,
        created_by=dto.created_by,
        created_at=dto.created_at,
    )


def _to_run_response(dto: RunDTO) -> dict[str, object]:
    """Run DTO → 统一响应壳 ``data`` 摘要（JSON 降级用）。"""
    return {
        "run_id": dto.id,
        "agent_id": dto.agent_id,
        "conversation_id": dto.conversation_id,
        "status": dto.status,
        "success": dto.success,
        "error_type": dto.error_type,
        "duration_ms": dto.duration_ms,
    }


# -- Agent CRUD -------------------------------------------------------------


@router.post("", response_model=AgentResponse, status_code=201, summary="创建 Agent")
def create_agent(
    payload: CreateAgentRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> AgentResponse:
    """创建 Agent（``DRAFT``，无当前版本）。"""
    handler = CreateAgentHandler(services.agent)
    dto = handler.handle(
        CreateAgentCommand(
            tenant_id=_tenant_id(user),
            name=payload.name,
            created_by=user.id,
            type=payload.type,
            workspace_id=payload.workspace_id,
            description=payload.description,
        )
    )
    return _to_agent_response(dto)


@router.get("", response_model=list[AgentResponse], summary="Agent 列表")
def list_agents(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    page: int = 1,
    page_size: int = 20,
) -> list[AgentResponse]:
    """列出当前租户下的全部 Agent（分页：``?page=&page_size=``，默认 20，上限 100）。"""
    handler = ListAgentsHandler(services.agent_repository)
    dtos = handler.handle(ListAgentsQuery(tenant_id=_tenant_id(user)))
    return [_to_agent_response(dto) for dto in _paginate(dtos, page, page_size)]


@router.get("/{agent_id}", response_model=AgentResponse, summary="Agent 详情")
def get_agent(
    agent_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> AgentResponse:
    """按 id 获取 Agent（跨租户 / 不存在 → 404）。"""
    handler = GetAgentHandler(services.agent_repository)
    dto = handler.handle(GetAgentQuery(agent_id=agent_id, tenant_id=_tenant_id(user)))
    return _to_agent_response(dto)


@router.put("/{agent_id}", response_model=AgentResponse, summary="更新 Agent")
def update_agent(
    agent_id: str,
    payload: UpdateAgentRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> AgentResponse:
    """更新 Agent 名称 / 描述 / 状态（缺省字段不变）。"""
    handler = UpdateAgentHandler(services.agent_repository)
    dto = handler.handle(
        UpdateAgentCommand(
            agent_id=agent_id,
            tenant_id=_tenant_id(user),
            name=payload.name,
            description=payload.description,
            status=payload.status,
        )
    )
    return _to_agent_response(dto)


# -- 版本 / 发布 ------------------------------------------------------------


@router.get(
    "/{agent_id}/versions",
    response_model=list[AgentVersionResponse],
    summary="Agent 版本列表",
)
def list_versions(
    agent_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[AgentVersionResponse]:
    """列出某 Agent 的全部版本（**不可变快照**）。"""
    versions = services.agent.list_versions(agent_id)
    return [_to_version_response(AgentVersionDTO.from_entity(v)) for v in versions]


@router.post(
    "/{agent_id}/publish",
    response_model=AgentVersionResponse,
    status_code=201,
    summary="发布 AgentVersion",
)
def publish_agent(
    agent_id: str,
    payload: PublishRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> AgentVersionResponse:
    """发布一个新版本（一次发布 = 一个新版本）并按需绑定 Tool。"""
    handler = PublishAgentVersionHandler(services.agent)
    dto = handler.handle(
        PublishAgentVersionCommand(
            agent_id=agent_id,
            tenant_id=_tenant_id(user),
            system_prompt=payload.system_prompt,
            model_config=payload.model_configuration,
            runtime_config=payload.runtime_config,
            created_by=user.id,
            version=payload.version,
            tools=[_tool_bind_dict(binding) for binding in payload.tools],
        )
    )
    return _to_version_response(dto)


# -- 运行（SSE / JSON 降级） ------------------------------------------------


@router.post("/{agent_id}/run", summary="运行 Agent（SSE 流式 / JSON 降级）")
def run_agent(
    agent_id: str,
    payload: RunRequest,
    request: Request,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    idempotency_key: IdempotencyKey = None,
) -> Response:
    """运行一次 Agent。

    - ``Accept: text/event-stream``（或缺省 / ``*/*``）→ **SSE 流**（9 通道 + 心跳）；
    - 显式排除 SSE（如 ``application/json``）→ 同步执行至终态并返回统一响应壳；
    - ``Idempotency-Key``**同键同体** → 复用首次 Run（不重复执行）；同键不同体 → 409。

    W8-3 / A38：本路由为**同步** ``def``（体内无 ``await``）——FastAPI 将同步路由置于外部
    线程池执行，使「幂等读 / 建会话 / 建 Run + 任务」等同步 DB I/O **不再阻塞事件循环**
    （对齐同仓 ``runs.py`` 路由形态）。
    """
    tenant_id = _tenant_id(user)
    key, fingerprint, reuse = prepare_idempotency(
        services=services,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        user_id=user.id,
        agent_id=agent_id,
        conversation_id=payload.conversation_id or "",
        input=payload.message,
    )
    if reuse is not None:
        # 幂等命中：直接复用首次响应（**不**重复建会话 / 不重复执行）。
        return _respond(request, services, reuse, start_execution=False)

    if payload.conversation_id:
        # 续聊：不新建会话；可省略 workspace_id（自既有会话派生，F-4 / R-R1R5-E1）。
        conversation_id = payload.conversation_id
        workspace_id = _continuation_workspace_id(services, payload)
    else:
        # 新建会话：缺 workspace_id → create_conversation 守卫抛 422（不再 PG 500）。
        conversation_id = _create_conversation(services, user, agent_id, payload)
        workspace_id = payload.workspace_id
    created = CreateAgentTaskHandler(services.agent_run).handle(
        CreateAgentTaskCommand(
            tenant_id=tenant_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user.id,
            user_message=payload.message,
            workspace_id=workspace_id,
            run_mode=payload.run_mode,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        )
    )
    return _respond(request, services, created, start_execution=True)


# -- 内部辅助 ---------------------------------------------------------------


def _tool_bind_dict(binding: AgentToolBind) -> dict[str, object]:
    """``AgentToolBind`` → 命令期望的 dict。"""
    return {
        "tool_id": binding.tool_id,
        "permission_scope": binding.permission_scope,
        "enabled": binding.enabled,
    }


def _paginate(items: list[AgentDTO], page: int, page_size: int) -> list[AgentDTO]:
    """按 ``page`` / ``page_size`` 分页（``page_size`` 上限 100）。"""
    size = max(1, min(int(page_size), 100))
    index = max(1, int(page))
    start = (index - 1) * size
    return items[start : start + size]


def _wants_sse(accept: str | None) -> bool:
    """``Accept`` 协商：含 ``text/event-stream`` 或缺省 / ``*/*`` → SSE（§2.3）。"""
    if not accept:
        return True
    lowered = accept.lower()
    return "text/event-stream" in lowered or "*/*" in lowered


def _stream_deps(services: AppServices) -> StreamDeps:
    """由 ``AppServices`` 抽取 SSE 流依赖（事件订阅落 ``astra_api/sse/``）。"""
    agent_run = services.agent_run
    return StreamDeps(
        event_bus=services.providers.event_bus,
        execute=agent_run.execute,
        list_events=agent_run.list_events,
        cancel=agent_run.cancel,
        run_status=agent_run.status,
    )


def _respond(
    request: Request,
    services: AppServices,
    run: RunDTO,
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
        services.agent_run.execute(run.id)
    final = services.agent_run.get_run(run.id)
    return _json_run_digest(final)


def _json_run_digest(dto: RunDTO) -> Response:
    """构造 JSON 降级响应（``data`` 为 Run 摘要）。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(content=_to_run_response(dto))


def _create_conversation(
    services: AppServices,
    user: UserDTO,
    agent_id: str,
    payload: RunRequest,
) -> str:
    """未提供 ``conversation_id`` 时就地创建会话并返回其标识。

    🔴 **不**静默 coercion 缺失 ``workspace_id``（F-4 / Erratum ``R-R1R5-E1``）：直接透传请求值，
    由 :meth:`ConversationService.create_conversation` **唯一守卫**——缺失 / 空 → ``422``
    ``VALIDATION_ERROR``（PG 权威面不再 500）。
    """
    conversation = services.conversation.create_conversation(
        tenant_id=_tenant_id(user),
        workspace_id=payload.workspace_id,
        agent_id=agent_id,
        user_id=user.id,
        title=(payload.message or "New conversation")[:120],
    )
    return conversation.id


def _continuation_workspace_id(services: AppServices, payload: RunRequest) -> str | None:
    """续聊分支派生 ``workspace_id``（F-4 / Erratum ``R-R1R5-E1``）。

    续聊（携带 ``conversation_id``）**不**新建会话，故可省略 ``workspace_id``：请求缺省时
    自**既有会话**派生；请求显式给出时以请求为准。
    """
    if payload.workspace_id:
        return payload.workspace_id
    conversation_id = payload.conversation_id
    if not conversation_id:
        return None
    conversation = services.conversation.get_conversation(conversation_id)
    if conversation is None:
        return None
    derived = getattr(conversation, "workspace_id", None)
    return str(derived) if derived else None
