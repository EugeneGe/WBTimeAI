"""``/api/v1/settings`` 路由（T0-18：系统 / 个人 / 凭证，含 API Key 入口）。

🔴 凭证响应**仅掩码**；明文不落库 / 不落日志 / 不回显（§2S.0.2）。
"""

from __future__ import annotations

from typing import Annotated

from astra_application.dto import UserDTO
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser, require_permission
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    CredentialResponse,
    FeatureFlagsResponse,
    PersonalSettingsResponse,
    SaveCredentialRequest,
    SystemSettingsResponse,
    UpdatePersonalSettingsRequest,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


@router.get("/system", response_model=SystemSettingsResponse, summary="系统设置")
def get_system_settings(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SystemSettingsResponse:
    """返回系统设置（**不含任何密钥类配置**）。"""
    system = services.settings.system_settings()
    return SystemSettingsResponse(
        mode=system.mode,
        app_name=system.app_name,
        app_version=system.app_version,
    )


@router.get("/personal", response_model=PersonalSettingsResponse, summary="个人设置")
def get_personal_settings(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PersonalSettingsResponse:
    """返回个人设置。"""
    personal = services.settings.personal_settings(user)
    return PersonalSettingsResponse(
        user_id=personal.user_id,
        username=personal.username,
        email=personal.email,
        display_name=personal.display_name,
    )


@router.put("/personal", response_model=PersonalSettingsResponse, summary="更新个人设置")
def update_personal_settings(
    payload: UpdatePersonalSettingsRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PersonalSettingsResponse:
    """更新个人设置（Phase 0 仅 ``display_name``）。"""
    personal = services.settings.update_personal(user.id, display_name=payload.display_name)
    return PersonalSettingsResponse(
        user_id=personal.user_id,
        username=personal.username,
        email=personal.email,
        display_name=personal.display_name,
    )


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=201,
    summary="保存凭证（API Key）",
)
def save_credential(
    payload: SaveCredentialRequest,
    user: Annotated[UserDTO, Depends(require_permission("settings:update"))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> CredentialResponse:
    """保存凭证：AES-256-GCM 加密落库，**仅返回掩码**。"""
    credential = services.settings.save_credential(
        tenant_id=_tenant_id(user),
        provider=payload.provider,
        key_type=payload.key_type,
        value=payload.value,
        workspace_id=payload.workspace_id,
    )
    return CredentialResponse(
        id=credential.id,
        provider=credential.provider,
        key_type=credential.key_type,
        masked_value=credential.masked_value,
        workspace_id=credential.workspace_id,
        created_at=credential.created_at,
    )


@router.get("/credentials", response_model=list[CredentialResponse], summary="凭证列表（掩码）")
def list_credentials(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[CredentialResponse]:
    """列出当前租户的全部凭证（**仅掩码**）。"""
    return [
        CredentialResponse(
            id=credential.id,
            provider=credential.provider,
            key_type=credential.key_type,
            masked_value=credential.masked_value,
            workspace_id=credential.workspace_id,
            created_at=credential.created_at,
        )
        for credential in services.settings.list_credentials(_tenant_id(user))
    ]


@router.get("/features", response_model=FeatureFlagsResponse, summary="Feature Flag 观测（只读）")
def get_feature_flags(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> FeatureFlagsResponse:
    """返回当前全部 Feature Flag 取值（**只读**，验收 §3-#14 的 API 观测面）。

    纯附加端点，**不改既有契约行**、无副作用；flag **不**影响模块 / 路由装配。
    """
    return FeatureFlagsResponse(flags=services.feature_flags.all())
