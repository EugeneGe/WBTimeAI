"""``SecretProvider`` 抽象 + Env 实现（决策 D8）。

Phase 0 从环境变量（``ASTRA_*``）与可选 ``secrets/`` 目录读取机密；
未来切换 Vault / KMS 时**不改业务代码**（仅替换 Provider）。

🔴 机密值**不落库 / 不落日志**；:.meth:`EnvSecretProvider.get` 不做任何打印。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from .constants import ensure_secret_key_length

__all__ = ["SecretProvider", "EnvSecretProvider"]


@runtime_checkable
class SecretProvider(Protocol):
    """机密提供者接口。"""

    def get(self, name: str, default: str | None = None) -> str | None:
        """获取机密；不存在时返回 ``default``。"""
        ...

    def get_required(self, name: str) -> str:
        """获取机密；不存在时抛 ``DomainError``。"""
        ...


class EnvSecretProvider:
    """基于环境变量（+ 可选 ``secrets/`` 目录）的机密提供者。

    Args:
        prefix: 环境变量前缀（默认 ``ASTRA_``）。
        secrets_dir: 可选 ``secrets/`` 目录；目录内文件名（大写）作为机密名回退来源。
    """

    def __init__(
        self,
        *,
        prefix: str = "ASTRA_",
        secrets_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._prefix = prefix
        self._secrets_dir = Path(secrets_dir).expanduser() if secrets_dir is not None else None

    def _env_name(self, name: str) -> str:
        return f"{self._prefix}{name.upper()}"

    def get(self, name: str, default: str | None = None) -> str | None:
        """获取机密。

        查找顺序：环境变量 → ``secrets/`` 文件 → ``default``。

        Args:
            name: 机密名（如 ``SECRET_KEY``）。
            default: 缺省值。

        Returns:
            机密值或 ``default``。
        """
        value = os.environ.get(self._env_name(name))
        if value:
            return value
        if self._secrets_dir is not None:
            candidate = self._secrets_dir / name.upper()
            if candidate.is_file():
                content = candidate.read_text(encoding="utf-8").strip()
                if content:
                    return content
        return default

    def get_required(self, name: str) -> str:
        """获取必需机密。

        Raises:
            DomainError: 机密缺失时（``CONFIGURATION_ERROR``）。
        """
        value = self.get(name)
        if not value:
            raise DomainError(
                f"缺少必需机密：{self._env_name(name)}",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
        return value

    def get_secret_key(self, name: str = "SECRET_KEY") -> str:
        """获取**主密钥**并联动最小长度校验（≥ ``MIN_SECRET_KEY_BYTES``）。

        与 :meth:`get_required` 的区别：本方法在取值后**额外**做长度校验，
        用于 ``ASTRA_SECRET_KEY`` 等要求强随机长度的机密（设计 §2.12 / P0-05）；
        普通机密（如第三方 API Key）不适用固定长度口径，仍用 :meth:`get`。

        Args:
            name: 机密名（默认 ``SECRET_KEY``，即环境变量 ``ASTRA_SECRET_KEY``）。

        Returns:
            校验通过的主密钥字符串。

        Raises:
            DomainError: 缺失（``CONFIGURATION_ERROR``）或长度不足
                （``CONFIGURATION_ERROR``）。错误信息不含密钥明文。
        """
        value = self.get_required(name)
        return ensure_secret_key_length(value, name=self._env_name(name))
