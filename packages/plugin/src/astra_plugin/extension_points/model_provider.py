"""ExtensionPoint ⑥ ``model_provider``（模型 Provider 注册）——签名冻结（裁定 §1.3⑥）。

与 ⑤ ``model_gateway`` **正交**：本点**注册 Provider 实现**，⑤ 在 Router 之上做策略。

另含模块级帮助函数 :func:`register_provider_factory`（W1b 裁定 §5.3 / T2-06）：
把 :class:`ModelProviderFactory` 的产物注册进 :class:`astra_model.ModelRegistry`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import ModelCapability, ProviderConfig
from astra_model import ModelProvider, ModelRegistry

__all__ = ["ModelProviderFactory", "EXTENSION_POINT_VERSION", "register_provider_factory"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "model_provider/v1"


@runtime_checkable
class ModelProviderFactory(Protocol):
    """模型 Provider 工厂扩展点。"""

    def provider_type(self) -> str:
        """Provider 类型标识（如 ``openai`` / ``gateway`` / …）。"""
        ...

    def create(self, config: ProviderConfig) -> ModelProvider:
        """按配置创建 :class:`~astra_model.ModelProvider` 实例。"""
        ...

    def capabilities(self) -> list[ModelCapability]:
        """声明该 Provider 支持的能力。"""
        ...


def register_provider_factory(
    registry: ModelRegistry,
    factory: ModelProviderFactory,
    config: ProviderConfig,
) -> None:
    """把 ``factory.create(config)`` 的产物注册进 ``registry``（裁定 §5.3）。

    使 Phase 4 Gateway 可由商业插件注册，而 **Runtime / Router 零改动**（R-26）。

    Args:
        registry: 目标 ``astra_model.ModelRegistry``。
        factory: 模型 Provider 工厂。
        config: 装配配置。
    """
    registry.register(factory.provider_type(), factory.create(config))
