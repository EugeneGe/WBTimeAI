"""AES-256-GCM 加解密单测（往返 + nonce 随机性 + 篡改检测）。"""

from __future__ import annotations

import pytest
from astra_core import DomainError
from astra_security import AesGcmCipher

#: ≥32 字节的主密钥（T1-01：短于 32B 会被 from_secret 拒绝）。
_MASTER = "unit-master-secret-key-0123456789abcdef"
_KEY_A = "unit-key-a-secret-0123456789abcdefgh"
_KEY_B = "unit-key-b-secret-0123456789abcdefgh"


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = AesGcmCipher.from_secret(_MASTER)
    token = cipher.encrypt("api-key-123")
    assert token != "api-key-123"
    assert cipher.decrypt(token) == "api-key-123"


def test_nonce_randomized() -> None:
    cipher = AesGcmCipher.from_secret(_MASTER)
    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_decrypt_with_wrong_key_fails() -> None:
    token = AesGcmCipher.from_secret(_KEY_A).encrypt("secret")
    with pytest.raises(DomainError):
        AesGcmCipher.from_secret(_KEY_B).decrypt(token)


def test_tampered_ciphertext_fails() -> None:
    cipher = AesGcmCipher.from_secret(_MASTER)
    token = cipher.encrypt("secret")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(DomainError):
        cipher.decrypt(tampered)


def test_empty_secret_rejected() -> None:
    with pytest.raises(DomainError):
        AesGcmCipher.from_secret("")
