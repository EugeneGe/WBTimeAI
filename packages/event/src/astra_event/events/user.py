"""用户相关 Phase 0 事件（继承 ``astra_core.events.DomainEvent``）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["UserRegistered", "UserLoggedIn", "UserLoggedOut"]


@dataclass
class UserRegistered(DomainEvent):
    """用户注册事件（``user.registered``）。"""

    type: ClassVar[str] = "user.registered"

    @classmethod
    def create(
        cls, *, user_id: str, tenant_id: str | None = None, username: str | None = None
    ) -> UserRegistered:
        """便捷构造。"""
        payload: dict[str, Any] = {"user_id": user_id}
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if username is not None:
            payload["username"] = username
        return cls(payload=payload)


@dataclass
class UserLoggedIn(DomainEvent):
    """用户登录事件（``user.logged_in``）。"""

    type: ClassVar[str] = "user.logged_in"

    @classmethod
    def create(cls, *, user_id: str, session_id: str | None = None) -> UserLoggedIn:
        """便捷构造。"""
        payload: dict[str, Any] = {"user_id": user_id}
        if session_id is not None:
            payload["session_id"] = session_id
        return cls(payload=payload)


@dataclass
class UserLoggedOut(DomainEvent):
    """用户登出事件（``user.logged_out``）。"""

    type: ClassVar[str] = "user.logged_out"

    @classmethod
    def create(cls, *, user_id: str, session_id: str | None = None) -> UserLoggedOut:
        """便捷构造。"""
        payload: dict[str, Any] = {"user_id": user_id}
        if session_id is not None:
            payload["session_id"] = session_id
        return cls(payload=payload)
