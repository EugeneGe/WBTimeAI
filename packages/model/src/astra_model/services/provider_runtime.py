"""``ProviderRuntime``——Provider 运行时按需解密（W6 / T1-30；§2.3.5 / C-07）。

**零 ORM / 零 Web**（抽象包纪律，F22）：面向**领域 Protocol** ``CredentialDecoder``
（``astra_domain.ports``）解密，**不** import ``astra_security``（其内含 ``astra_database``，F21）。

🔴 **显式且可审计**：:meth:`resolve_secret` 解密后经注入的 ``audit`` 回调写
   ``audit_log(action="model.credential.decrypt", outcome=SUCCESS)``；**明文仅内存**，
   不落库 / 不落日志 / 不回显（C-07）。对外的凭证列表仍**仅掩码**。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import AUDIT_OUTCOME_SUCCESS, CredentialDecoder, ModelProviderRepository

__all__ = ["ProviderRuntime"]

#: 解密审计动作名。
DECRYPT_AUDIT_ACTION = "model.credential.decrypt"


class ProviderRuntime:
    """Provider 运行时：按需解密绑定凭证（可审计，仅在内存）。"""

    def __init__(
        self,
        *,
        provider_repository: ModelProviderRepository,
        decoder: CredentialDecoder,
        audit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._providers = provider_repository
        self._decoder = decoder
        self._audit = audit

    def resolve_secret(
        self,
        provider_id: str,
        *,
        tenant_id: str,
        run_id: str | None = None,
    ) -> str:
        """解析某 Provider 的凭证明文（**仅内存**；解密写入审计）。

        Args:
            provider_id: Provider 标识。
            tenant_id: 租户标识（跨租户 → ``NOT_FOUND``）。
            run_id: 关联 Run 标识（可空，供审计）。

        Returns:
            凭证明文（调用方**不得**落库 / 落日志 / 回显）。

        Raises:
            DomainError: Provider 不存在 / 跨租户（``NOT_FOUND``）；未绑定凭证
                （``CONFIGURATION_ERROR``）。
        """
        provider = self._providers.get(provider_id)
        if provider is None or provider.tenant_id != tenant_id:
            raise DomainError(
                "提供方不存在",
                code=ErrorCode.NOT_FOUND,
                data={"provider_id": provider_id},
            )
        if not provider.credential_id:
            raise DomainError(
                "提供方未绑定凭证",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"provider_id": provider_id},
            )
        secret = self._decoder.decrypt(provider.credential_id)
        self._record_audit(provider_id=provider_id, tenant_id=tenant_id, run_id=run_id)
        return secret

    def _record_audit(self, *, provider_id: str, tenant_id: str, run_id: str | None) -> None:
        """写解密审计（回调缺失 / 失败均**不阻断**解密流程）。"""
        if self._audit is None:
            return
        try:
            self._audit(
                {
                    "tenant_id": tenant_id,
                    "action": DECRYPT_AUDIT_ACTION,
                    "outcome": AUDIT_OUTCOME_SUCCESS,
                    "resource_type": "model_provider",
                    "resource_id": provider_id,
                    "run_id": run_id,
                    "metadata": {"provider_id": provider_id},
                }
            )
        except Exception:  # noqa: BLE001 - 审计失败不阻断运行时解密
            pass
