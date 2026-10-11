"""Astra AI 模型 Provider 接口与实现（``astra_model``）。

Phase 0 定义**接口**（``ModelProvider`` / ``ModelRegistry`` + ``StubModelProvider``）；
Phase 1（W3）扩展**扩展实现**：真实 Provider（``astra_model.providers``）、
起步级 Router（``astra_model.router``）、核心成本计价（``astra_model.pricing``）
与 Provider/Model 目录领域服务（``astra_model.services``）。

🔴 ``astra_model`` 属**抽象包**：零 ORM、零 ``astra_database`` 导入（分层纪律）。
"""

from __future__ import annotations

from .factory import build_model_catalog_service
from .pricing import (
    CORE_PRICE_VERSION,
    CostCalculator,
    CostResult,
    PriceItem,
    PriceProvider,
    StaticPriceCatalog,
    build_default_price_catalog,
)
from .provider import ModelProvider
from .providers import build_model_providers, register_builtin_providers
from .registry import ModelRegistry
from .router import ModelRouter, build_model_router
from .services import (
    MODEL_PROVIDER_TYPES,
    ModelCatalogService,
    ModelCredentialBinder,
    ProviderRuntime,
)
from .stub import StubModelProvider
from .types import ChatMessage, ChatResult, Embedding, ModelInfo, TokenCount

__all__ = [
    # 接口 / DTO（Phase 0，不改）
    "ChatMessage",
    "ChatResult",
    "Embedding",
    "TokenCount",
    "ModelInfo",
    "ModelProvider",
    "ModelRegistry",
    "StubModelProvider",
    # 目录领域服务（T1-10）
    "ModelCatalogService",
    "MODEL_PROVIDER_TYPES",
    "build_model_catalog_service",
    # 凭证复用（W6 / T1-30）
    "ModelCredentialBinder",
    "ProviderRuntime",
    # Router（T1-12）
    "ModelRouter",
    # 装配（W6 / T1-31）
    "build_model_providers",
    "build_model_router",
    "register_builtin_providers",
    # 计价（T1-13）
    "PriceProvider",
    "PriceItem",
    "StaticPriceCatalog",
    "build_default_price_catalog",
    "CORE_PRICE_VERSION",
    "CostCalculator",
    "CostResult",
]
