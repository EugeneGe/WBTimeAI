"""密码哈希（argon2id）。

🔴 明文口令**不落库 / 不落日志**：仅存 :meth:`PasswordHasher.hash` 产出的哈希。

`argon2-cffi` 默认即为 **argon2id**；本模块显式声明参数，便于日后调参与重哈希。
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

__all__ = ["PasswordHasher"]


class PasswordHasher:
    """密码哈希器（argon2id）。

    Attributes:
        time_cost: 迭代次数。
        memory_cost: 内存开销（KiB）。
        parallelism: 并行度。
        hash_len: 派生哈希长度。
        salt_len: 盐长度。
    """

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        self.time_cost = time_cost
        self.memory_cost = memory_cost
        self.parallelism = parallelism
        self.hash_len = hash_len
        self.salt_len = salt_len
        self._hasher = _Argon2PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
            type=Type.ID,  # argon2id
        )

    def hash(self, password: str) -> str:
        """计算口令哈希。

        Args:
            password: 明文口令（仅内存中短暂存在，不落库 / 不落日志）。

        Returns:
            argon2id 编码哈希字符串。
        """
        return self._hasher.hash(password)

    def verify(self, password: str, hash_value: str) -> bool:
        """校验口令与哈希是否匹配。

        Args:
            password: 明文口令。
            hash_value: 已存哈希。

        Returns:
            匹配返回 ``True``，不匹配或哈希非法返回 ``False``（不抛异常，避免信息泄露）。
        """
        try:
            return self._hasher.verify(hash_value, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hash_value: str) -> bool:
        """判断既有哈希是否需按当前参数重哈希。"""
        try:
            return self._hasher.check_needs_rehash(hash_value)
        except (VerificationError, InvalidHashError):
            return True
