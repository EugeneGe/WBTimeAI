"""``/conversations`` 路由（W6 / T1-29；设计 §2.6 / §2.13）。

端点：

- ``POST /conversations``：创建会话；
- ``GET /conversations``：会话列表（多租户隔离）；
- ``GET /conversations/{id}``：会话详情；
- ``GET /conversations/{id}/messages``：会话消息列表（按创建顺序）。

Router **只**依赖 ``AppServices``（N-8）；**不** import ``astra_database`` /
``sqlalchemy``（A33 收紧）。
"""

from __future__ import annotations

from typing import Annotated

from astra_application.dto import UserDTO
from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    ConversationMessageResponse,
    ConversationResponse,
    CreateConversationRequest,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_conversation_response(conversation: object) -> ConversationResponse:
    """Conversation 实体 → 响应。"""
    return ConversationResponse(
        id=str(getattr(conversation, "id")),  # noqa: B009 - 泛化只读映射（对象可能为任意实体）
        tenant_id=getattr(conversation, "tenant_id", None),
        workspace_id=str(getattr(conversation, "workspace_id", "")),
        agent_id=str(getattr(conversation, "agent_id", "")),
        user_id=str(getattr(conversation, "user_id", "")),
        title=str(getattr(conversation, "title", "")),
        status=str(getattr(conversation, "status", "ACTIVE")),
        created_at=getattr(conversation, "created_at", None),
        updated_at=getattr(conversation, "updated_at", None),
    )


def _to_message_response(message: object) -> ConversationMessageResponse:
    """Message 实体 → 响应。"""
    return ConversationMessageResponse(
        id=str(getattr(message, "id")),  # noqa: B009 - 泛化只读映射（对象可能为任意实体）
        conversation_id=str(getattr(message, "conversation_id", "")),
        run_id=getattr(message, "run_id", None),
        role=str(getattr(message, "role", "user")),
        content=str(getattr(message, "content", "")),
        content_parts=list(getattr(message, "content_parts", []) or []),
        token_count=getattr(message, "token_count", None),
        created_at=getattr(message, "created_at", None),
    )


@router.post("", response_model=ConversationResponse, status_code=201, summary="创建会话")
def create_conversation(
    payload: CreateConversationRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ConversationResponse:
    """创建一个会话（归属当前用户 / 租户）。"""
    conversation = services.conversation.create_conversation(
        tenant_id=_tenant_id(user),
        workspace_id=payload.workspace_id,
        agent_id=payload.agent_id,
        user_id=user.id,
        title=payload.title,
    )
    return _to_conversation_response(conversation)


@router.get("", response_model=list[ConversationResponse], summary="会话列表")
def list_conversations(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ConversationResponse]:
    """列出当前租户下的全部会话。"""
    return [
        _to_conversation_response(conversation)
        for conversation in services.conversation.list_conversations(_tenant_id(user))
    ]


@router.get("/{conversation_id}", response_model=ConversationResponse, summary="会话详情")
def get_conversation(
    conversation_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ConversationResponse:
    """按 id 获取会话（跨租户 / 不存在 → 404）。"""
    conversation = services.conversation.get_conversation(conversation_id)
    if conversation is None or conversation.tenant_id != _tenant_id(user):
        raise DomainError(
            "会话不存在",
            code=ErrorCode.NOT_FOUND,
            data={"conversation_id": conversation_id},
        )
    return _to_conversation_response(conversation)


@router.get(
    "/{conversation_id}/messages",
    response_model=list[ConversationMessageResponse],
    summary="会话消息列表",
)
def list_messages(
    conversation_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ConversationMessageResponse]:
    """按创建顺序列出某会话的全部消息。"""
    conversation = services.conversation.get_conversation(conversation_id)
    if conversation is None or conversation.tenant_id != _tenant_id(user):
        raise DomainError(
            "会话不存在",
            code=ErrorCode.NOT_FOUND,
            data={"conversation_id": conversation_id},
        )
    return [
        _to_message_response(message)
        for message in services.conversation.list_messages(conversation_id)
    ]
