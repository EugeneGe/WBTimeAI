"""Astra AI 认证与密钥安全（``astra_security``）。

- :class:`~astra_security.password.PasswordHasher`：argon2id 密码哈希
- :class:`~astra_security.jwt.TokenService`：JWT（access + refresh，决策 D1）
- :class:`~astra_security.crypto.AesGcmCipher`：AES-256-GCM 凭证加密
- :class:`~astra_security.secret_provider.EnvSecretProvider`：机密提供者（决策 D8）
- :class:`~astra_security.session.SessionService`：可撤销会话
- :class:`~astra_security.login_guard.LoginGuard`：连续失败锁定
- :class:`~astra_security.credential_service.CredentialService`：凭证加密落库（仅密文）
- :data:`~astra_security.constants.MIN_SECRET_KEY_BYTES`：主密钥最小长度（≥32B，P0-05）
"""

from __future__ import annotations

from .constants import MIN_SECRET_KEY_BYTES, ensure_secret_key_length
from .credential_service import (
    CredentialService,
    CredentialServiceDecoder,
    MaskedCredential,
    ModelProviderCredentialView,
    mask_secret,
)
from .crypto import AesGcmCipher
from .jwt import ACCESS, REFRESH, TokenClaims, TokenService, TokenType
from .login_guard import LoginGuard
from .password import PasswordHasher
from .permission import (
    WILDCARD,
    ResourcePermissionChecker,
    capability_is_escalation,
    capability_matches_any,
    denied_capabilities,
    effective_capabilities,
    granted_capabilities,
    match_capability,
    matches_capability_pattern,
)
from .repositories import (
    SqlCredentialRepository,
    SqlLoginAttemptRepository,
    SqlRefreshTokenRepository,
    SqlSessionRepository,
)
from .secret_provider import EnvSecretProvider, SecretProvider
from .session import DeviceSession, SessionService, SessionTokens

__all__ = [
    "PasswordHasher",
    "TokenService",
    "TokenClaims",
    "TokenType",
    "ACCESS",
    "REFRESH",
    "AesGcmCipher",
    "SecretProvider",
    "EnvSecretProvider",
    "MIN_SECRET_KEY_BYTES",
    "ensure_secret_key_length",
    "SessionService",
    "SessionTokens",
    "DeviceSession",
    "LoginGuard",
    "CredentialService",
    "CredentialServiceDecoder",
    "MaskedCredential",
    "ModelProviderCredentialView",
    "mask_secret",
    "SqlSessionRepository",
    "SqlRefreshTokenRepository",
    "SqlLoginAttemptRepository",
    "SqlCredentialRepository",
    # 权限单一判定链（W3 / T2-13 · 裁定 §2）
    "ResourcePermissionChecker",
    # Capability 匹配 / 有效集（W3 / T2-14 · 裁定 §4）
    "WILDCARD",
    "matches_capability_pattern",
    "capability_matches_any",
    "granted_capabilities",
    "denied_capabilities",
    "capability_is_escalation",
    "match_capability",
    "effective_capabilities",
]
