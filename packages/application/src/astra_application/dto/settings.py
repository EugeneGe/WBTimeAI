"""设置相关 DTO（系统 / 个人 / 凭证）。

⚠️ 凭证 DTO **仅承载掩码**（``masked_value``），**永不承载明文 / 密文**；
   系统设置 DTO **不得**包含任何密钥类配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .base import DTO

__all__ = [
    "SystemSettingsDTO",
    "PersonalSettingsDTO",
    "CredentialDTO",
]


@dataclass
class SystemSettingsDTO(DTO):
    """系统设置（**不含密钥类配置**）。

    Attributes:
        mode: 运行模式（``local`` | ``server``）。
        app_name: 应用名称。
        app_version: 应用版本。
    """

    mode: str = "local"
    app_name: str = "Astra AI"
    app_version: str = "0.1.0"


@dataclass
class PersonalSettingsDTO(DTO):
    """个人设置（Phase 0 走既有列 ``user.display_name`` 等）。"""

    user_id: str
    username: str
    email: str
    display_name: str | None = None


@dataclass
class CredentialDTO(DTO):
    """凭证 DTO（**仅掩码**，无明文 / 密文）。"""

    id: str
    provider: str
    key_type: str
    masked_value: str
    workspace_id: str | None = None
    created_at: datetime | None = None
