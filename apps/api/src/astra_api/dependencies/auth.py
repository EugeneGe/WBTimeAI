"""认证 / 鉴权依赖（统一放此模块，§2S.0.1）。

- :data:`CurrentUser`：Bearer access token → :class:`UserDTO`（失败 401）；
- :func:`require_permission`：最小 RBAC 守卫（失败 403，``admin = *`` 通配放行）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from astra_application.dto import UserDTO
from astra_core import PermissionDeniedError, UnauthorizedError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .services import AppServices, get_app_services

__all__ = [
    "get_access_token",
    "get_current_user",
    "require_permission",
    "AccessToken",
    "CurrentUser",
    "bearer_scheme",
]

#: Bearer 方案（``auto_error=False``：缺失时返回 ``None``，由本模块统一转 401）。
bearer_scheme = HTTPBearer(auto_error=False)


def get_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """取出 Bearer access token 明文。

    Raises:
        UnauthorizedError: 无 token / 格式错（HTTP 401）。
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError(
            "缺少访问令牌（需 Authorization: Bearer <access_token>）",
        )
    return credentials.credentials


#: 访问令牌依赖类型别名。
AccessToken = Annotated[str, Depends(get_access_token)]


def get_current_user(
    access_token: AccessToken,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> UserDTO:
    """解析 ``Authorization: Bearer <access>`` 并鉴权。

    Returns:
        :class:`UserDTO`。

    Raises:
        UnauthorizedError: 无 token / 格式错（HTTP 401）。
        DomainError: token 过期 / 篡改 / 用户不存在（``AUTH_*`` / ``UNAUTHORIZED``，HTTP 401）。
    """
    return services.auth.authenticate(access_token)


#: 当前用户依赖类型别名。
CurrentUser = Annotated[UserDTO, Depends(get_current_user)]


def require_permission(code: str) -> Callable[..., UserDTO]:
    """构造「要求指定权限码」的 FastAPI 依赖。

    Args:
        code: 权限码（如 ``workspace:create``）。

    Returns:
        依赖函数：通过返回 :class:`UserDTO`，否则抛 403。
    """

    def dependency(
        user: CurrentUser,
        services: Annotated[AppServices, Depends(get_app_services)],
    ) -> UserDTO:
        if not services.identity.authorization.has_permission(user.id, code):
            raise PermissionDeniedError(
                f"缺少权限：{code}",
                data={"permission": code},
            )
        return user

    return dependency
