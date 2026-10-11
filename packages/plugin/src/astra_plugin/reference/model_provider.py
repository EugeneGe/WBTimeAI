"""``model_provider`` 参考实现：:class:`EchoModelProviderFactory`。

``create`` 返回 ``astra_model.StubModelProvider`` 结构（确定性回显），
**零三方依赖 / 零 ORM**。
"""

from __future__ import annotations

from astra_domain import ModelCapability, ProviderConfig
from astra_model import ModelProvider, StubModelProvider

__all__ = ["EchoModelProviderFactory"]


class EchoModelProviderFactory:
    """回显 Provider 工厂（参考实现）。"""

    def provider_type(self) -> str:
        """类型标识 ``echo``。"""
        return "echo"

    def create(self, config: ProviderConfig) -> ModelProvider:
        """返回按配置命名的 :class:`~astra_model.StubModelProvider`。"""
        return StubModelProvider(name=config.name or "echo")

    def capabilities(self) -> list[ModelCapability]:
        """声明支持 CHAT / STREAM / COUNT_TOKENS。"""
        return [ModelCapability.CHAT, ModelCapability.STREAM, ModelCapability.COUNT_TOKENS]
