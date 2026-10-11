"""``ModelCatalogService``——Model Provider / Model 目录领域服务（设计 §2.3 / §2.16）。

**零 ORM、零 ``astra_database``**：经 **依赖注入** 领域 Protocol 仓储
（``astra_domain.ModelProviderRepository`` / ``astra_domain.ModelRepository``）
操作目录；SQL 实现落 ``astra_database.repositories``（W3 架构裁定 Q1 = 方案 B）。

- Provider 目录：注册 / 列表 / 详情 / 禁用（``status ∈ {ACTIVE, DISABLED}``）；
- 模型目录：注册 / 列表 / 详情 / 禁用；
- **多租户隔离**：跨租户访问一律 ``NOT_FOUND``；
- 可选把**运行时 Provider**（``ModelProvider`` 实现）登记进 ``ModelRegistry``，
  使「目录 Provider 名」与「运行时可查询的 Provider」对齐（验收口径 ④）。

凭证**复用** ``credential`` 表：``credential_id`` 仅存引用（C-07；不建 ``model_credential``）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import (
    MODEL_PROVIDER_STATUS_ACTIVE,
    MODEL_PROVIDER_STATUS_DISABLED,
    MODEL_STATUS_ACTIVE,
    MODEL_STATUS_DISABLED,
    MODEL_TYPE_CHAT,
    Model,
    ModelProvider,
    ModelProviderRepository,
    ModelRepository,
)

from ..provider import ModelProvider as RuntimeModelProvider
from ..registry import ModelRegistry

__all__ = ["ModelCatalogService", "MODEL_PROVIDER_TYPES"]

#: 合法 Provider 类型（对齐设计 §2.15.1 `model_provider.type`）。
MODEL_PROVIDER_TYPES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "qwen",
    "ollama",
    "openai_compatible",
)


class ModelCatalogService:
    """模型目录领域服务（DI 注入领域 Protocol 仓储）。"""

    def __init__(
        self,
        *,
        provider_repository: ModelProviderRepository,
        model_repository: ModelRepository,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._providers = provider_repository
        self._models = model_repository
        self._registry = registry

    # -- Provider 目录 -------------------------------------------------------

    def register_provider(
        self,
        *,
        tenant_id: str,
        name: str,
        provider_type: str,
        endpoint: str | None = None,
        credential_id: str | None = None,
        config: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> ModelProvider:
        """注册一个模型提供方（目录项）。

        Args:
            tenant_id: 所属租户标识。
            name: 提供方名称（唯一标识；注册进 ``ModelRegistry`` 时用作键）。
            provider_type: 提供方类型（见 :data:`MODEL_PROVIDER_TYPES`）。
            endpoint: 自定义端点（可空）。
            credential_id: 凭证标识（**仅存引用** ``credential.id``，可空）。
            config: 附加配置（JSON 结构）。
            workspace_id: 归属工作区标识（可空）。

        Returns:
            新建的 :class:`~astra_domain.entities.model.ModelProvider`。

        Raises:
            DomainError: 名称为空或类型非法（``VALIDATION_ERROR``）。
        """
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise DomainError(
                "提供方名称不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        normalized_type = (provider_type or "").strip()
        if normalized_type not in MODEL_PROVIDER_TYPES:
            raise DomainError(
                f"提供方类型非法：{provider_type!r}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "type", "allowed": list(MODEL_PROVIDER_TYPES)},
            )
        return self._providers.add(
            ModelProvider(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=normalized_name,
                type=normalized_type,
                endpoint=endpoint,
                credential_id=credential_id,
                status=MODEL_PROVIDER_STATUS_ACTIVE,
                config=dict(config) if config else {},
            )
        )

    def get_provider(self, provider_id: str, *, tenant_id: str) -> ModelProvider:
        """按 id 获取提供方（**校验租户归属**）。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``）。
        """
        return self._require_provider(provider_id, tenant_id=tenant_id)

    def list_providers(self, tenant_id: str) -> list[ModelProvider]:
        """列出某租户下的全部提供方（多租户隔离）。"""
        return self._providers.list_by_tenant(tenant_id)

    def disable_provider(self, provider_id: str, *, tenant_id: str) -> ModelProvider:
        """禁用一个提供方（``status = DISABLED``）。"""
        provider = self._require_provider(provider_id, tenant_id=tenant_id)
        provider.status = MODEL_PROVIDER_STATUS_DISABLED
        provider.touch()
        return self._providers.update(provider)

    # -- 模型目录 ------------------------------------------------------------

    def register_model(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        name: str,
        model_type: str = MODEL_TYPE_CHAT,
        context_window: int | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> Model:
        """在指定提供方下注册一个模型。

        Raises:
            DomainError: 名称为空（``VALIDATION_ERROR``）或提供方不存在 / 跨租户（``NOT_FOUND``）。
        """
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise DomainError(
                "模型名称不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        self._require_provider(provider_id, tenant_id=tenant_id)
        return self._models.add(
            Model(
                tenant_id=tenant_id,
                provider_id=provider_id,
                name=normalized_name,
                type=model_type,
                context_window=context_window,
                capabilities=dict(capabilities) if capabilities else {},
                status=MODEL_STATUS_ACTIVE,
            )
        )

    def list_models(self, provider_id: str, *, tenant_id: str) -> list[Model]:
        """列出某提供方下的全部模型（**校验租户归属**）。"""
        self._require_provider(provider_id, tenant_id=tenant_id)
        return self._models.list_by_provider(provider_id)

    def get_model(self, model_id: str, *, tenant_id: str) -> Model:
        """按 id 获取模型（经其提供方**校验租户归属**）。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``）。
        """
        model = self._models.get(model_id)
        if model is None:
            raise DomainError(
                "模型不存在",
                code=ErrorCode.NOT_FOUND,
                data={"model_id": model_id},
            )
        self._require_provider(model.provider_id, tenant_id=tenant_id)
        return model

    def disable_model(self, model_id: str, *, tenant_id: str) -> Model:
        """禁用一个模型（``status = DISABLED``）。"""
        model = self.get_model(model_id, tenant_id=tenant_id)
        model.status = MODEL_STATUS_DISABLED
        model.touch()
        return self._models.update(model)

    # -- 运行时 Provider 接线（验收口径 ④） ----------------------------------

    def register_runtime_provider(self, name: str, provider: RuntimeModelProvider) -> None:
        """把运行时 Provider 实现登记进 :class:`~astra_model.registry.ModelRegistry`。

        使「目录 Provider 名」可在运行时按名解析（Router 前置）。

        Raises:
            DomainError: 未配置 ``registry``（``CONFIGURATION_ERROR``）。
        """
        if self._registry is None:
            raise DomainError(
                "未配置 ModelRegistry，无法登记运行时 Provider",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"name": name},
            )
        self._registry.register(name, provider)

    # -- 内部 ----------------------------------------------------------------

    def _require_provider(self, provider_id: str, *, tenant_id: str) -> ModelProvider:
        provider = self._providers.get(provider_id)
        if provider is None or provider.tenant_id != tenant_id:
            raise DomainError(
                "提供方不存在",
                code=ErrorCode.NOT_FOUND,
                data={"provider_id": provider_id},
            )
        return provider
