"""model 组合工厂（纯 DI 装配）。

🔴 **不接触** ``session`` / ``session_factory``（W3 架构裁定 Q1 = 方案 B）：
   ``session_factory → SQL 仓储`` 的接线属**组合根**（T1-31 / W6），
   本工厂仅把**已构造的领域 Protocol 仓储**注入服务。
"""

from __future__ import annotations

from astra_domain import ModelProviderRepository, ModelRepository

from .registry import ModelRegistry
from .services import ModelCatalogService

__all__ = ["build_model_catalog_service"]


def build_model_catalog_service(
    *,
    provider_repository: ModelProviderRepository,
    model_repository: ModelRepository,
    registry: ModelRegistry | None = None,
) -> ModelCatalogService:
    """依领域 Protocol 仓储装配 :class:`ModelCatalogService`（DI）。

    Args:
        provider_repository: 领域 ``ModelProviderRepository`` 实现
            （如 ``astra_database.SqlModelProviderRepository``）。
        model_repository: 领域 ``ModelRepository`` 实现
            （如 ``astra_database.SqlModelRepository``）。
        registry: 可选 ``ModelRegistry``（用于运行时 Provider 接线）。

    Returns:
        :class:`~astra_model.services.ModelCatalogService`。
    """
    return ModelCatalogService(
        provider_repository=provider_repository,
        model_repository=model_repository,
        registry=registry,
    )
