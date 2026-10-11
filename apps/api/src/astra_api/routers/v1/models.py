"""``/models`` 路由（W6 / T1-29 + T1-30；设计 §2.3 / §2.3.5 / §2.13）。

端点：

- ``/models/providers``：目录 / 注册 / 详情 / 禁用（``DELETE`` = 软禁用）；
- ``/models/providers/{id}/models``：模型目录 / 注册；
- ``/models/providers/{id}/credential``：凭证**绑定 / 解绑**（仅存引用，不复制密文）；
- ``/models/credentials``：复用 ``/settings/credentials`` 语义（**仅掩码**）。

Router **只**依赖 ``AppServices``（N-8）；**不** import ``astra_model`` /
``astra_database`` / ``sqlalchemy``（A33 收紧）；凭证**仅掩码**（C-07）。
"""

from __future__ import annotations

from typing import Annotated

from astra_application.dto import CredentialDTO, UserDTO
from fastapi import APIRouter, Depends, Response

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import (
    BindCredentialRequest,
    CredentialResponse,
    ModelProviderResponse,
    ModelResponse,
    RegisterModelRequest,
    RegisterProviderRequest,
    SaveCredentialRequest,
)

router = APIRouter(prefix="/models", tags=["models"])


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_provider_response(provider: object) -> ModelProviderResponse:
    """ModelProvider 实体 → 响应（``credential_id`` **仅引用**，无密文 / 明文）。"""
    return ModelProviderResponse(
        id=str(getattr(provider, "id")),  # noqa: B009 - 泛化只读映射（对象可能为任意实体）
        tenant_id=getattr(provider, "tenant_id", None),
        workspace_id=getattr(provider, "workspace_id", None),
        name=str(getattr(provider, "name", "")),
        type=str(getattr(provider, "type", "")),
        endpoint=getattr(provider, "endpoint", None),
        credential_id=getattr(provider, "credential_id", None),
        status=str(getattr(provider, "status", "ACTIVE")),
        config=dict(getattr(provider, "config", {}) or {}),
        created_at=getattr(provider, "created_at", None),
    )


def _to_model_response(model: object) -> ModelResponse:
    """Model 实体 → 响应。"""
    return ModelResponse(
        id=str(getattr(model, "id")),  # noqa: B009 - 泛化只读映射（对象可能为任意实体）
        tenant_id=getattr(model, "tenant_id", None),
        provider_id=str(getattr(model, "provider_id", "")),
        name=str(getattr(model, "name", "")),
        type=str(getattr(model, "type", "CHAT")),
        context_window=getattr(model, "context_window", None),
        capabilities=dict(getattr(model, "capabilities", {}) or {}),
        status=str(getattr(model, "status", "ACTIVE")),
        created_at=getattr(model, "created_at", None),
    )


def _to_credential_response(credential: CredentialDTO) -> CredentialResponse:
    """凭证 DTO → 响应（**仅掩码**，无明文 / 密文）。"""
    return CredentialResponse(
        id=credential.id,
        provider=credential.provider,
        key_type=credential.key_type,
        masked_value=credential.masked_value,
        workspace_id=credential.workspace_id,
        created_at=credential.created_at,
    )


# -- Provider 目录 ----------------------------------------------------------


@router.get("/providers", response_model=list[ModelProviderResponse], summary="模型提供方列表")
def list_providers(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ModelProviderResponse]:
    """列出当前租户的全部模型提供方（多租户隔离）。"""
    return [
        _to_provider_response(provider)
        for provider in services.model.list_providers(_tenant_id(user))
    ]


@router.post(
    "/providers",
    response_model=ModelProviderResponse,
    status_code=201,
    summary="注册模型提供方",
)
def register_provider(
    payload: RegisterProviderRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelProviderResponse:
    """注册一个模型提供方（``credential_id`` **仅存引用**）。"""
    provider = services.model.register_provider(
        tenant_id=_tenant_id(user),
        name=payload.name,
        provider_type=payload.provider_type,
        endpoint=payload.endpoint,
        credential_id=payload.credential_id,
        config=payload.config,
        workspace_id=payload.workspace_id,
    )
    return _to_provider_response(provider)


@router.get(
    "/providers/{provider_id}",
    response_model=ModelProviderResponse,
    summary="模型提供方详情",
)
def get_provider(
    provider_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelProviderResponse:
    """按 id 获取模型提供方（跨租户 / 不存在 → 404）。"""
    provider = services.model.get_provider(provider_id, tenant_id=_tenant_id(user))
    return _to_provider_response(provider)


@router.delete(
    "/providers/{provider_id}",
    response_model=ModelProviderResponse,
    summary="禁用模型提供方",
)
def disable_provider(
    provider_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelProviderResponse:
    """禁用模型提供方（软删除：``status = DISABLED``）。"""
    provider = services.model.disable_provider(provider_id, tenant_id=_tenant_id(user))
    return _to_provider_response(provider)


# -- 模型目录 ---------------------------------------------------------------


@router.get(
    "/providers/{provider_id}/models",
    response_model=list[ModelResponse],
    summary="模型列表",
)
def list_models(
    provider_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[ModelResponse]:
    """列出某提供方下的全部模型（校验租户归属）。"""
    return [
        _to_model_response(model)
        for model in services.model.list_models(provider_id, tenant_id=_tenant_id(user))
    ]


@router.post(
    "/providers/{provider_id}/models",
    response_model=ModelResponse,
    status_code=201,
    summary="注册模型",
)
def register_model(
    provider_id: str,
    payload: RegisterModelRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelResponse:
    """在某提供方下注册一个模型。"""
    model = services.model.register_model(
        tenant_id=_tenant_id(user),
        provider_id=provider_id,
        name=payload.name,
        model_type=payload.model_type,
        context_window=payload.context_window,
        capabilities=payload.capabilities,
    )
    return _to_model_response(model)


# -- 凭证绑定 / 解绑（仅存引用） --------------------------------------------


@router.post(
    "/providers/{provider_id}/credential",
    response_model=ModelProviderResponse,
    summary="绑定凭证到提供方",
)
def bind_credential(
    provider_id: str,
    payload: BindCredentialRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelProviderResponse:
    """把 ``credential_id`` 绑定到某提供方（**仅写引用**，不复制密文）。"""
    provider = services.model_credentials.bind(
        tenant_id=_tenant_id(user),
        provider_id=provider_id,
        credential_id=payload.credential_id,
    )
    return _to_provider_response(provider)


@router.delete(
    "/providers/{provider_id}/credential",
    response_model=ModelProviderResponse,
    summary="解绑提供方凭证",
)
def unbind_credential(
    provider_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelProviderResponse:
    """解除某提供方的凭证绑定（``credential_id = None``）。"""
    provider = services.model_credentials.unbind(
        tenant_id=_tenant_id(user), provider_id=provider_id
    )
    return _to_provider_response(provider)


# -- 凭证（复用 /settings/credentials 语义，仅掩码） ------------------------


@router.get("/credentials", response_model=list[CredentialResponse], summary="凭证列表（掩码）")
def list_credentials(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[CredentialResponse]:
    """列出当前租户的全部凭证（**仅掩码**）。"""
    return [
        _to_credential_response(credential)
        for credential in services.settings.list_credentials(_tenant_id(user))
    ]


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=201,
    summary="保存凭证（API Key）",
)
def save_credential(
    payload: SaveCredentialRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> CredentialResponse:
    """保存模型凭证：AES-256-GCM 加密落库，**仅返回掩码**（C-07）。"""
    credential = services.settings.save_credential(
        tenant_id=_tenant_id(user),
        provider=payload.provider,
        key_type=payload.key_type,
        value=payload.value,
        workspace_id=payload.workspace_id,
    )
    return _to_credential_response(credential)


@router.delete("/credentials/{credential_id}", status_code=204, summary="删除凭证")
def delete_credential(
    credential_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """删除凭证（幂等：不存在不报错）。"""
    services.settings.delete_credential(credential_id, tenant_id=_tenant_id(user))
    return Response(status_code=204)
