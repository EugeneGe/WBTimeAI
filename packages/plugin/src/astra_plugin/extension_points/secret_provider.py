"""ExtensionPoint ④ ``secret_provider``（密钥管理）——签名冻结（W1b 裁定 §1.3④）。

🔴 **命名冲突处置（C1 / F6）**：本 Protocol 类名保留设计原名 ``SecretProvider``，
   与 Phase-1 ``astra_security.SecretProvider``（``get`` / ``get_required``）
   **同名异义**：

   - Phase-1 ``astra_security.SecretProvider`` ＝ **secret-source**（密钥来源）；
   - 本扩展点 ``SecretProvider`` ＝ **key-management**（Vault / KMS 加解密钥匙管理）。

   二者**命名空间不同、语义正交**，**禁止**跨包 re-export / 别名 / 互相继承。
   加解密实现（AES-GCM）**单一归属** ``astra_security``（生产实现由其在 Phase 3–4 提供）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import RotationResult

__all__ = ["SecretProvider", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "secret_provider/v1"


@runtime_checkable
class SecretProvider(Protocol):
    """密钥管理扩展点（加解密钥匙；非 secret-source）。"""

    def master_key(self) -> bytes:
        """返回当前主密钥（**仅供内部加解密使用，不得落日志**）。"""
        ...

    def encrypt(self, plaintext: bytes) -> bytes:
        """使用主密钥加密。"""
        ...

    def decrypt(self, ciphertext: bytes) -> bytes:
        """使用主密钥解密。"""
        ...

    def rotate(self) -> RotationResult:
        """轮换主密钥（须支持中断恢复，QA-45）。"""
        ...
