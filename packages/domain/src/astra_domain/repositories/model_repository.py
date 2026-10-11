"""Model 组仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``model_provider`` / ``model``。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.model import Model, ModelProvider
from .base import Repository

__all__ = ["ModelProviderRepository", "ModelRepository"]


@runtime_checkable
class ModelProviderRepository(Repository[ModelProvider], Protocol):
    """模型提供方仓储接口。"""

    def list_by_tenant(self, tenant_id: str) -> list[ModelProvider]:
        """列出某租户下的全部提供方。"""
        ...


@runtime_checkable
class ModelRepository(Repository[Model], Protocol):
    """模型目录仓储接口。"""

    def list_by_provider(self, provider_id: str) -> list[Model]:
        """列出某提供方下的全部模型。"""
        ...
