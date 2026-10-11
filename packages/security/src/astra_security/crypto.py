"""AES-256-GCM 对称加密（凭证安全，设计 §2.7）。

- 算法：AES-256-GCM（认证加密，防篡改）；
- 密钥：32 字节（由主密钥经 SHA-256 派生；主密钥来源 :class:`SecretProvider`）；
- 随机 nonce（12 字节，每次加密重新生成）；
- 输出：``base64(nonce || ciphertext || tag)``。

🔴 ``encrypted_value`` **仅存密文**；明文不落库 / 不落日志。
"""

from __future__ import annotations

import base64
import hashlib
import os

from astra_core import DomainError, ErrorCode
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .constants import ensure_secret_key_length

__all__ = ["AesGcmCipher"]

_NONCE_BYTES = 12
_KEY_BYTES = 32


class AesGcmCipher:
    """AES-256-GCM 加解密器。"""

    def __init__(self, key: bytes) -> None:
        """以 32 字节密钥构造。

        Args:
            key: 32 字节 AES-256 密钥。

        Raises:
            DomainError: 密钥长度非法时（``CONFIGURATION_ERROR``）。
        """
        if len(key) != _KEY_BYTES:
            raise DomainError(
                f"AES-GCM 需 {_KEY_BYTES} 字节密钥，实际 {len(key)}",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_secret(cls, secret: str) -> AesGcmCipher:
        """由主密钥字符串派生加密器（SHA-256 → 32 字节）。

        Args:
            secret: 主密钥字符串，须 **≥32 字节**（UTF-8）。

        Returns:
            以派生密钥构造的 :class:`AesGcmCipher`。

        Raises:
            DomainError: 主密钥为空或短于 32 字节时（``CONFIGURATION_ERROR``）。
        """
        ensure_secret_key_length(secret, name="ASTRA_SECRET_KEY")
        key = hashlib.sha256(secret.encode("utf-8")).digest()
        return cls(key)

    def encrypt(self, plaintext: str) -> str:
        """加密明文，返回 base64 密文（含随机 nonce）。

        Args:
            plaintext: 待加密明文。

        Returns:
            ``base64(nonce || ciphertext)`` 字符串。
        """
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, token: str) -> str:
        """解密密文。

        Args:
            token: :meth:`encrypt` 产出的 base64 字符串。

        Returns:
            明文。

        Raises:
            DomainError: 密文非法或被篡改时（``VALIDATION_ERROR``）。
        """
        try:
            raw = base64.b64decode(token, validate=True)
        except (ValueError, TypeError) as exc:
            raise DomainError("密文 base64 非法", code=ErrorCode.VALIDATION_ERROR) from exc
        if len(raw) <= _NONCE_BYTES:
            raise DomainError("密文长度非法", code=ErrorCode.VALIDATION_ERROR)
        nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
        except InvalidTag as exc:
            raise DomainError(
                "密文校验失败（可能被篡改）", code=ErrorCode.VALIDATION_ERROR
            ) from exc
