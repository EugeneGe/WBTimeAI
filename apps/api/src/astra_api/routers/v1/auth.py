"""``/api/v1/auth`` 路由（T0-18：注册 / 登录 / 登出 / 刷新）。

🔴 Router **不直调 DB / ORM**；仅解析请求 → 调用 :class:`~astra_application.AuthService`
→ 映射 DTO 为 schema。
"""

from __future__ import annotations

from typing import Annotated

from astra_application.dto import AuthResultDTO
from fastapi import APIRouter, Depends, Request

from astra_api.dependencies.auth import AccessToken
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_context(request: Request) -> dict[str, str | None]:
    """从请求提取客户端上下文（IP / User-Agent）。"""
    ip_address = request.client.host if request.client is not None else None
    user_agent = request.headers.get("user-agent")
    return {"ip_address": ip_address, "user_agent": user_agent}


def _token_response(result: AuthResultDTO) -> TokenResponse:
    """由认证结果构造令牌响应。"""
    tokens = result.tokens
    if tokens is None:  # pragma: no cover - 注册 / 登录必返回令牌
        raise RuntimeError("认证结果缺少令牌组")
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/register", response_model=TokenResponse, status_code=201, summary="注册")
def register(
    payload: RegisterRequest,
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TokenResponse:
    """注册新用户并返回令牌组（自动登录）。"""
    context = _client_context(request)
    result = services.auth.register(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        ip_address=context["ip_address"],
        user_agent=context["user_agent"],
    )
    return _token_response(result)


@router.post("/login", response_model=TokenResponse, summary="登录")
def login(
    payload: LoginRequest,
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TokenResponse:
    """登录并返回令牌组（连续失败 → 423）。"""
    context = _client_context(request)
    result = services.auth.login(
        username=payload.username,
        password=payload.password,
        ip_address=context["ip_address"],
        user_agent=context["user_agent"],
    )
    return _token_response(result)


@router.post("/logout", response_model=MessageResponse, summary="登出")
def logout(
    access_token: AccessToken,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MessageResponse:
    """登出：撤销当前会话（旧 refresh 随之失效）。"""
    services.auth.logout(access_token=access_token)
    return MessageResponse(message="已登出")


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌")
def refresh(
    payload: RefreshRequest,
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> TokenResponse:
    """以 refresh token 换取新令牌组（旧 refresh 撤销后 → 401）。"""
    context = _client_context(request)
    result = services.auth.refresh(
        payload.refresh_token,
        ip_address=context["ip_address"],
        user_agent=context["user_agent"],
    )
    return _token_response(result)
