"""JWT 令牌服务（决策 D1：access + refresh）。

Claims 约定：``sub``（用户 ID）/ ``tenant_id`` / ``type``（``access`` | ``refresh``）/
``exp`` / ``iat`` / ``jti``（唯一标识）/ ``sid``（会话 ID）。

过期 / 篡改映射为统一 ``AUTH_*`` 错误码，便于 API 层（T0-08）映射 401。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode, generate_id

from .constants import ensure_secret_key_length

__all__ = ["TokenType", "TokenClaims", "TokenService"]

ACCESS = "access"
REFRESH = "refresh"


class TokenType:
    """令牌类型常量。"""

    ACCESS = ACCESS
    REFRESH = REFRESH


@dataclass
class TokenClaims:
    """解码后的令牌声明。

    Attributes:
        sub: 主体（用户 ID）。
        tenant_id: 租户 ID。
        type: 令牌类型（``access`` | ``refresh``）。
        jti: 令牌唯一标识。
        sid: 会话 ID。
        exp: 过期时间（UTC）。
        raw: 原始声明字典。
    """

    sub: str
    tenant_id: str | None = None
    type: str = ACCESS
    jti: str | None = None
    sid: str | None = None
    exp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class TokenService:
    """JWT 签发 / 解码服务（HS256）。"""

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "HS256",
        access_ttl_seconds: int = 900,
        refresh_ttl_seconds: int = 1_209_600,
        issuer: str = "astra-ai",
    ) -> None:
        ensure_secret_key_length(secret, name="ASTRA_SECRET_KEY")
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds
        self._issuer = issuer

    # -- 签发 ---------------------------------------------------------------

    def create_access_token(
        self,
        subject: str,
        *,
        tenant_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """签发 access token。"""
        return self._encode(subject, ACCESS, self._access_ttl, tenant_id, session_id)

    def create_refresh_token(
        self,
        subject: str,
        *,
        tenant_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """签发 refresh token。"""
        return self._encode(subject, REFRESH, self._refresh_ttl, tenant_id, session_id)

    def _encode(
        self,
        subject: str,
        token_type: str,
        ttl_seconds: int,
        tenant_id: str | None,
        session_id: str | None,
    ) -> str:
        now = utcnow()
        payload: dict[str, Any] = {
            "sub": subject,
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "jti": generate_id(),
            "iss": self._issuer,
        }
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if session_id is not None:
            payload["sid"] = session_id
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    # -- 解码 ---------------------------------------------------------------

    def decode(self, token: str, *, expected_type: str | None = None) -> TokenClaims:
        """解码并校验令牌。

        Args:
            token: 令牌字符串。
            expected_type: 期望令牌类型（``access`` / ``refresh``）；为 ``None`` 时不校验。

        Returns:
            :class:`TokenClaims`。

        Raises:
            DomainError: 过期 → ``AUTH_TOKEN_EXPIRED``；篡改 / 非法 → ``AUTH_TOKEN_INVALID``；
                类型不符 → ``AUTH_TOKEN_INVALID``。
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise DomainError("令牌已过期", code=ErrorCode.AUTH_TOKEN_EXPIRED) from exc
        except jwt.InvalidTokenError as exc:
            raise DomainError("令牌非法", code=ErrorCode.AUTH_TOKEN_INVALID) from exc

        token_type = str(payload.get("type", ACCESS))
        if expected_type is not None and token_type != expected_type:
            raise DomainError(
                f"令牌类型不符：期望 {expected_type}，实际 {token_type}",
                code=ErrorCode.AUTH_TOKEN_INVALID,
            )

        exp_value = payload.get("exp")
        exp_dt = (
            datetime.fromtimestamp(int(exp_value), tz=UTC)
            if isinstance(exp_value, (int, float))
            else None
        )
        return TokenClaims(
            sub=str(payload["sub"]),
            tenant_id=payload.get("tenant_id"),
            type=token_type,
            jti=payload.get("jti"),
            sid=payload.get("sid"),
            exp=exp_dt,
            raw=dict(payload),
        )
