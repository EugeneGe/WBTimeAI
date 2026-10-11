"""``ModelCredentialBinder``——模型 Provider ↔ 凭证绑定服务（W6 / T1-30；§2.3.5 / C-07）。

**零 ORM / 零 Web**（``astra_model`` 属抽象包，F22 保绿）：经**依赖注入的领域 Protocol**
``ModelProviderRepository`` 读写 ``model_provider.credential_id``。

🔴 **仅存引用**：绑定**只写** ``model_provider.credential_id``（指向 ``credential.id``），
   **不复制密文**、**不建** ``model_credential`` 表（C-07 / Q8）。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode
from astra_domain import ModelProvider, ModelProviderRepository

__all__ = ["ModelCredentialBinder"]


class ModelCredentialBinder:
    """模型 Provider 凭证绑定器（DI 注入领域 Protocol 仓储）。"""

    def __init__(self, *, provider_repository: ModelProviderRepository) -> None:
        self._providers = provider_repository

    def bind(self, *, tenant_id: str, provider_id: str, credential_id: str) -> ModelProvider:
        """把 ``credential_id`` 绑定到某 Provider（仅写引用，不复制密文）。

        Raises:
            DomainError: Provider 不存在 / 跨租户（``NOT_FOUND``）；``credential_id`` 为空
                （``VALIDATION_ERROR``）。
        """
        if not credential_id:
            raise DomainError(
                "credential_id 不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "credential_id"},
            )
        provider = self._require(provider_id, tenant_id=tenant_id)
        provider.credential_id = credential_id
        provider.touch()
        return self._providers.update(provider)

    def unbind(self, *, tenant_id: str, provider_id: str) -> ModelProvider:
        """解除某 Provider 的凭证绑定（``credential_id = None``）。"""
        provider = self._require(provider_id, tenant_id=tenant_id)
        provider.credential_id = None
        provider.touch()
        return self._providers.update(provider)

    def _require(self, provider_id: str, *, tenant_id: str) -> ModelProvider:
        provider = self._providers.get(provider_id)
        if provider is None or provider.tenant_id != tenant_id:
            raise DomainError(
                "提供方不存在",
                code=ErrorCode.NOT_FOUND,
                data={"provider_id": provider_id},
            )
        return provider
