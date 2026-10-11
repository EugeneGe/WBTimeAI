"""``auth_provider`` 参考实现：:class:`AllowAllAuthProvider`（**仅开发用**）。

🔴 **NON-SECURE**：放行一切、不做任何校验——**仅用于契约演示 / 本地开发**，
   生产环境**禁止**启用（真实 OIDC / SAML 归 Phase 3–4）。
"""

from __future__ import annotations

from astra_domain import AuthCredential, ExtensionContext, Principal

__all__ = ["AllowAllAuthProvider"]


class AllowAllAuthProvider:
    """放行一切的认证提供者（**NON-SECURE / 仅契约演示**）。"""

    def supports(self, scheme: str) -> bool:
        """声明支持任意方案。"""
        return True

    def authenticate(self, credential: AuthCredential, ctx: ExtensionContext) -> Principal:
        """不校验，直接构造 ``Principal``（subject 取自凭证 payload，缺省空串）。"""
        subject_id = str(credential.payload.get("subject_id", ""))
        return Principal(
            subject_id=subject_id,
            tenant_id=ctx.tenant_id,
            kind="user",
            roles=(),
            claims={"scheme": credential.scheme, "non_secure": True},
        )

    def logout(self, principal: Principal) -> None:
        """无状态，登出为幂等空操作。"""
        return None
