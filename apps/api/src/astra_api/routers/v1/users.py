"""``/api/v1/users`` 路由（T0-18：本人信息 / 更新 / 设备 / 强制退出）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    DeviceResponse,
    MessageResponse,
    UpdateUserRequest,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])


def _user_response(user) -> UserResponse:
    """由领域用户构造响应。"""
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserResponse, summary="读取本人信息")
def read_me(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> UserResponse:
    """读取当前登录用户信息。"""
    current = services.identity.users.get(user.id)
    if current is None:  # pragma: no cover - 鉴权已保证存在
        return _user_response(user)
    return _user_response(current)


@router.put("/me", response_model=UserResponse, summary="更新本人信息")
def update_me(
    payload: UpdateUserRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> UserResponse:
    """更新本人信息（Phase 0 仅 ``display_name``）。"""
    services.settings.update_personal(user.id, display_name=payload.display_name)
    current = services.identity.users.get(user.id)
    if current is None:  # pragma: no cover - 鉴权已保证存在
        return _user_response(user)
    return _user_response(current)


@router.get("/me/devices", response_model=list[DeviceResponse], summary="设备列表")
def list_devices(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[DeviceResponse]:
    """列出当前用户的全部设备会话。"""
    return [
        DeviceResponse(
            id=device.id,
            device=device.device,
            ip_address=device.ip_address,
            user_agent=device.user_agent,
            created_at=device.created_at,
            expires_at=device.expires_at,
            revoked_at=device.revoked_at,
        )
        for device in services.auth.list_devices(user.id)
    ]


@router.post("/me/logout-all", response_model=MessageResponse, summary="全端退出")
def logout_all(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> MessageResponse:
    """强制退出：撤销当前用户全部会话。"""
    count = services.auth.logout_all(user.id)
    return MessageResponse(message=f"已撤销 {count} 个会话")
