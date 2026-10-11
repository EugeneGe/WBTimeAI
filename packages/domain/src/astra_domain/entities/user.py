"""User 实体。

⚠️ 本实体仅承载 ``password_hash`` **字段**，不含哈希逻辑
（哈希实现属 T0-12 ``astra_security``），确保领域层零框架 / 零加密依赖。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import AggregateRoot

__all__ = ["User"]


@dataclass
class User(AggregateRoot):
    """用户。"""

    username: str = ""
    email: str = ""
    password_hash: str = ""
    display_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False
