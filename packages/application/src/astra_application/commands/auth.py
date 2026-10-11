"""认证用例（Command / CommandHandler，决策 D1）。

处理器委托 :class:`~astra_application.services.auth_service.AuthService`，
返回应用层 DTO；命令仅承载入参，不含业务逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dto.auth import AuthResultDTO
from ..services.auth_service import AuthService
from .base import Command

__all__ = [
    "RegisterUserCommand",
    "RegisterUserHandler",
    "LoginUserCommand",
    "LoginUserHandler",
    "LogoutUserCommand",
    "LogoutUserHandler",
    "RefreshTokenCommand",
    "RefreshTokenHandler",
]


@dataclass
class RegisterUserCommand(Command):
    """注册用户命令。"""

    username: str = ""
    email: str = ""
    password: str = ""
    display_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    device: str | None = None


class RegisterUserHandler:
    """注册用户命令处理器。"""

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def handle(self, command: RegisterUserCommand) -> AuthResultDTO:
        """执行注册并返回认证结果。"""
        return self._auth.register(
            username=command.username,
            email=command.email,
            password=command.password,
            display_name=command.display_name,
            ip_address=command.ip_address,
            user_agent=command.user_agent,
            device=command.device,
        )


@dataclass
class LoginUserCommand(Command):
    """登录命令。"""

    username: str = ""
    password: str = ""
    ip_address: str | None = None
    user_agent: str | None = None
    device: str | None = None


class LoginUserHandler:
    """登录命令处理器。"""

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def handle(self, command: LoginUserCommand) -> AuthResultDTO:
        """执行登录并返回认证结果。"""
        return self._auth.login(
            username=command.username,
            password=command.password,
            ip_address=command.ip_address,
            user_agent=command.user_agent,
            device=command.device,
        )


@dataclass
class LogoutUserCommand(Command):
    """登出命令（撤销当前会话）。"""

    access_token: str = ""


class LogoutUserHandler:
    """登出命令处理器。"""

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def handle(self, command: LogoutUserCommand) -> None:
        """执行登出（撤销会话）。"""
        self._auth.logout(access_token=command.access_token)


@dataclass
class RefreshTokenCommand(Command):
    """刷新令牌命令。"""

    refresh_token: str = ""
    device: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class RefreshTokenHandler:
    """刷新令牌命令处理器。"""

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def handle(self, command: RefreshTokenCommand) -> AuthResultDTO:
        """执行刷新并返回新的认证结果。"""
        return self._auth.refresh(
            command.refresh_token,
            device=command.device,
            ip_address=command.ip_address,
            user_agent=command.user_agent,
        )
