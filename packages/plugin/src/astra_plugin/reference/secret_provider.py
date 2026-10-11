"""``secret_provider`` 参考实现：:class:`LocalSecretProvider`（**NON-SECURE**）。

🔴 **零三方依赖 / 零 ORM / 零 ``astra_security``**（F7：``astra_security`` 会拉入 ORM）。
   加解密逻辑由**注入**的 ``cipher`` 可调用对提供；**默认 identity**（原样返回），
   故本实现 **NON-SECURE**，仅用于契约演示。生产加解密实现（AES-GCM）单一归属
   ``astra_security``（Phase 3–4 提供结构化契合的实现）。
"""

from __future__ import annotations

from collections.abc import Callable

from astra_domain import RotationResult

__all__ = ["LocalSecretProvider"]


def _identity(data: bytes) -> bytes:
    """默认恒等变换（**NON-SECURE**：不加密、不混淆）。"""
    return data


class LocalSecretProvider:
    """本地密钥提供者（**NON-SECURE / 仅契约演示**）。

    Args:
        master_key: 主密钥字节（调用方从安全来源注入，**不得落日志**）。
        encrypt: 加密可调用（缺省 identity）。
        decrypt: 解密可调用（缺省 identity）。
    """

    def __init__(
        self,
        master_key: bytes,
        *,
        encrypt: Callable[[bytes], bytes] | None = None,
        decrypt: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._master_key = master_key
        self._encrypt = encrypt or _identity
        self._decrypt = decrypt or _identity

    def master_key(self) -> bytes:
        """返回主密钥（**仅供内部加解密使用**）。"""
        return self._master_key

    def encrypt(self, plaintext: bytes) -> bytes:
        """使用注入的加密可调用（缺省 identity）。"""
        return self._encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """使用注入的解密可调用（缺省 identity）。"""
        return self._decrypt(ciphertext)

    def rotate(self) -> RotationResult:
        """本地参考实现**不支持**轮换（返回 ``rotated=False``）。"""
        return RotationResult(
            rotated=False,
            key_version=None,
            resumed=False,
            message="NON-SECURE 参考实现：不支持密钥轮换（生产归 astra_security）",
        )
