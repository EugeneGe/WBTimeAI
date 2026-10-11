"""``CredentialDecoder``——凭证解密领域 Protocol（W6 / T1-30；设计 §2.3.5 / C-07）。

**零框架**（受 ``test_domain_has_no_framework_dependencies`` 覆盖）。

作用：把「凭证解密」抽象为**领域层 Protocol**，使抽象包 ``astra_model`` 面向该 Protocol
解密，而**不传递依赖** ``astra_security``（其内含 ``astra_database``，F21）——
adapter 由 ``astra_security`` 提供（如 ``CredentialServiceDecoder``），组合根装配注入。

🔴 **明文仅内存**：``decrypt`` 返回值**绝不**落库 / 落日志 / 回显（C-07）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["CredentialDecoder"]


@runtime_checkable
class CredentialDecoder(Protocol):
    """凭证解码器接口（按 ``credential_id`` 解密为明文，仅内存）。"""

    def decrypt(self, credential_id: str) -> str:
        """解密指定凭证为明文。

        Args:
            credential_id: 凭证标识（``credential.id``）。

        Returns:
            明文（**仅内存使用，绝不落库 / 落日志 / 回显**）。

        Raises:
            DomainError: 凭证不存在或跨租户（``CREDENTIAL_NOT_FOUND``）；
                密文非法 / 被篡改（``VALIDATION_ERROR``）。
        """
        ...
