"""JWT 单测（签发 / 解码 / 过期 / 篡改）。"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_security import TokenService
from astra_security.jwt import ACCESS, REFRESH


@pytest.fixture()
def service() -> TokenService:
    return TokenService(
        "unit-secret-key-0123456789abcdef", access_ttl_seconds=900, refresh_ttl_seconds=3600
    )


def test_roundtrip_access_token(service: TokenService) -> None:
    token = service.create_access_token("user-1", tenant_id="tenant-1", session_id="sid-1")
    claims = service.decode(token, expected_type=ACCESS)
    assert claims.sub == "user-1"
    assert claims.tenant_id == "tenant-1"
    assert claims.sid == "sid-1"
    assert claims.type == ACCESS
    assert claims.jti


def test_refresh_token_type(service: TokenService) -> None:
    token = service.create_refresh_token("user-1")
    claims = service.decode(token, expected_type=REFRESH)
    assert claims.type == REFRESH


def test_type_mismatch_raises_invalid(service: TokenService) -> None:
    token = service.create_access_token("user-1")
    with pytest.raises(DomainError) as excinfo:
        service.decode(token, expected_type=REFRESH)
    assert excinfo.value.code is ErrorCode.AUTH_TOKEN_INVALID


def test_expired_token_raises(service: TokenService) -> None:
    expired = TokenService("unit-secret-key-0123456789abcdef", access_ttl_seconds=-1)
    token = expired.create_access_token("user-1")
    with pytest.raises(DomainError) as excinfo:
        service.decode(token)
    assert excinfo.value.code is ErrorCode.AUTH_TOKEN_EXPIRED


def test_tampered_token_raises_invalid(service: TokenService) -> None:
    token = service.create_access_token("user-1")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(DomainError) as excinfo:
        service.decode(tampered)
    assert excinfo.value.code is ErrorCode.AUTH_TOKEN_INVALID


def test_empty_secret_rejected() -> None:
    with pytest.raises(DomainError) as excinfo:
        TokenService("")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
