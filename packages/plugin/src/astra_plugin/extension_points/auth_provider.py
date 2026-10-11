"""ExtensionPoint ① ``auth_provider``（认证提供者）——签名冻结（W1b 裁定 §1.3①）。

Raises:
    DomainError: 认证失败（``ErrorCode.UNAUTHORIZED``）；配置缺失
        （``ErrorCode.CONFIGURATION_ERROR``）。

🔴 设计原文用词 ``UNAUTHENTICATED`` **不在** ``ErrorCode``——统一改用既有
   ``ErrorCode.UNAUTHORIZED``（裁定 §1.1-4 / F16），**不新增错误码**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import AuthCredential, ExtensionContext, Principal

__all__ = ["AuthProvider", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``；自 W1b 裁定冻结为 ``v1``）。
EXTENSION_POINT_VERSION: str = "auth_provider/v1"


@runtime_checkable
class AuthProvider(Protocol):
    """认证提供者扩展点（外部身份源 → 平台 ``Principal``）。"""

    def supports(self, scheme: str) -> bool:
        """是否支持给定认证方案（如 ``local`` / ``oidc`` / ``saml``）。"""
        ...

    def authenticate(self, credential: AuthCredential, ctx: ExtensionContext) -> Principal:
        """校验凭证并返回主体；失败抛 ``DomainError(UNAUTHORIZED)``。"""
        ...

    def logout(self, principal: Principal) -> None:
        """登出（撤销会话 / 令牌）；幂等。"""
        ...
