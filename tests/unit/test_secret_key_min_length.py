"""主密钥最小长度校验单测（T1-01 / 设计 §0.3 T01 级必闭合 · P0-05）。

断言：
- ``AesGcmCipher.from_secret`` / ``TokenService`` / ``EnvSecretProvider.get_secret_key``
  对 **<32 字节**密钥抛 ``DomainError(CONFIGURATION_ERROR)``；
- **≥32 字节**密钥通过；
- 校验错误信息**不含密钥明文**（安全纪律：明文不落日志 / 报错）。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_security import (
    MIN_SECRET_KEY_BYTES,
    AesGcmCipher,
    EnvSecretProvider,
    TokenService,
    ensure_secret_key_length,
)

#: 32 字节整（恰好达标的边界密钥）。
_BOUNDARY_OK = "0123456789abcdef0123456789abcdef"
#: 32 字节以上。
_LONG_OK = "a-very-long-and-strong-secret-key-with-enough-bytes"
#: 短密钥（<32 字节）。
_SHORT = "short-secret-key"


def test_min_bytes_constant_is_32() -> None:
    assert MIN_SECRET_KEY_BYTES == 32


def test_ensure_helper_accepts_boundary_and_long() -> None:
    assert len(_BOUNDARY_OK.encode("utf-8")) == 32
    assert ensure_secret_key_length(_BOUNDARY_OK) == _BOUNDARY_OK
    assert ensure_secret_key_length(_LONG_OK) == _LONG_OK


def test_ensure_helper_rejects_empty_and_short() -> None:
    with pytest.raises(DomainError) as empty_exc:
        ensure_secret_key_length("")
    assert empty_exc.value.code is ErrorCode.CONFIGURATION_ERROR

    with pytest.raises(DomainError) as short_exc:
        ensure_secret_key_length(_SHORT, name="ASTRA_SECRET_KEY")
    assert short_exc.value.code is ErrorCode.CONFIGURATION_ERROR


def test_error_message_has_no_plaintext() -> None:
    with pytest.raises(DomainError) as excinfo:
        ensure_secret_key_length(_SHORT)
    assert _SHORT not in excinfo.value.message
    assert str(MIN_SECRET_KEY_BYTES) in excinfo.value.message


def test_cipher_from_secret_rejects_short() -> None:
    with pytest.raises(DomainError) as excinfo:
        AesGcmCipher.from_secret(_SHORT)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_cipher_from_secret_accepts_boundary() -> None:
    cipher = AesGcmCipher.from_secret(_BOUNDARY_OK)
    assert cipher.decrypt(cipher.encrypt("payload")) == "payload"


def test_token_service_rejects_short() -> None:
    with pytest.raises(DomainError) as excinfo:
        TokenService(_SHORT)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_token_service_accepts_boundary() -> None:
    service = TokenService(_BOUNDARY_OK)
    token = service.create_access_token("user-1")
    assert service.decode(token).sub == "user-1"


def test_env_secret_provider_get_secret_key_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = EnvSecretProvider()

    monkeypatch.setenv("ASTRA_SECRET_KEY", _SHORT)
    with pytest.raises(DomainError) as short_exc:
        provider.get_secret_key()
    assert short_exc.value.code is ErrorCode.CONFIGURATION_ERROR

    monkeypatch.setenv("ASTRA_SECRET_KEY", _LONG_OK)
    assert provider.get_secret_key() == _LONG_OK
