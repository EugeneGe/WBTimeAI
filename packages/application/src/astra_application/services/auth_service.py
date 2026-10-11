"""``AuthService``——认证应用服务（决策 D1 / §3-#12）。

覆盖注册 / 登录（含 :class:`~astra_security.login_guard.LoginGuard` 锁定）/
登出 / 刷新 / access 鉴权 / 设备列表 / 强制退出。

🔴 不感知 HTTP / Web 框架；令牌与口令细节委托 ``astra_security``。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode
from astra_identity import IdentityServices
from astra_security import (
    ACCESS,
    LoginGuard,
    PasswordHasher,
    SessionService,
    TokenService,
)

from ..dto.auth import AuthResultDTO, TokenPairDTO
from ..dto.identity import UserDTO
from .base import ApplicationService

__all__ = ["AuthService"]


class AuthService(ApplicationService):
    """认证应用服务。"""

    # 依赖由基类 ``ApplicationService.__init__`` 经 ``setattr`` 注入；此处仅作
    # 类级类型声明（无赋值），供静态类型检查识别实例属性，运行时零影响。
    identity: IdentityServices
    password_hasher: PasswordHasher
    token_service: TokenService
    session_service: SessionService
    login_guard: LoginGuard

    def __init__(
        self,
        *,
        identity: IdentityServices,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        session_service: SessionService,
        login_guard: LoginGuard,
        access_token_ttl_seconds: int = 900,
    ) -> None:
        super().__init__(
            identity=identity,
            password_hasher=password_hasher,
            token_service=token_service,
            session_service=session_service,
            login_guard=login_guard,
        )
        self.access_token_ttl_seconds = access_token_ttl_seconds

    # -- 注册 / 登录 --------------------------------------------------------

    def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device: str | None = None,
    ) -> AuthResultDTO:
        """注册新用户（自动登录并授予默认 ``admin`` 角色）。

        Community 默认「一个租户 + admin=* 通配」：注册用户自动成为默认组织成员
        并获得 ``admin`` 角色（Phase 0 体验极简）。

        Raises:
            DomainError: 用户名 / 邮箱已存在（``USER_ALREADY_EXISTS``）。
        """
        tenant = self.identity.tenants.ensure_default()
        if self.identity.users.get_by_username(tenant.id, username) is not None:
            raise DomainError(
                "用户名已存在",
                code=ErrorCode.USER_ALREADY_EXISTS,
                data={"field": "username", "value": username},
            )
        if self.identity.users.get_by_email(tenant.id, email) is not None:
            raise DomainError(
                "邮箱已存在",
                code=ErrorCode.USER_ALREADY_EXISTS,
                data={"field": "email", "value": email},
            )
        password_hash = self.password_hasher.hash(password)
        user = self.identity.users.ensure_user(
            tenant_id=tenant.id,
            username=username,
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        # 授予默认成员关系 + admin 角色（Community 默认 admin=*）。
        bootstrap = self.identity.bootstrap.ensure_default_identity()
        self.identity.bootstrap.ensure_membership(
            tenant_id=tenant.id,
            user_id=user.id,
            organization_id=bootstrap.organization.id,
            role_id=bootstrap.admin_role.id,
        )
        tokens = self._issue_tokens(
            tenant_id=tenant.id,
            user_id=user.id,
            device=device,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return AuthResultDTO(user=UserDTO.from_entity(user), tokens=tokens)

    def login(
        self,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device: str | None = None,
    ) -> AuthResultDTO:
        """登录（含连续失败锁定）。

        Raises:
            DomainError: 已锁定（``AUTH_ACCOUNT_LOCKED``，HTTP 423）或
                凭据无效（``AUTH_INVALID_CREDENTIALS``，HTTP 401）。
        """
        tenant = self.identity.tenants.ensure_default()
        self.login_guard.assert_not_locked(username, tenant_id=tenant.id)
        user = self.identity.users.get_by_username(tenant.id, username)
        if user is None or not self.password_hasher.verify(password, user.password_hash):
            self.login_guard.register_failure(
                username=username, tenant_id=tenant.id, ip_address=ip_address
            )
            raise DomainError("用户名或密码错误", code=ErrorCode.AUTH_INVALID_CREDENTIALS)
        if not user.is_active:
            raise DomainError("账号已停用", code=ErrorCode.AUTH_INVALID_CREDENTIALS)
        self.login_guard.register_success(
            username=username, tenant_id=tenant.id, ip_address=ip_address
        )
        tokens = self._issue_tokens(
            tenant_id=tenant.id,
            user_id=user.id,
            device=device,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return AuthResultDTO(user=UserDTO.from_entity(user), tokens=tokens)

    # -- 登出 / 刷新 / 鉴权 -------------------------------------------------

    def logout(self, *, access_token: str) -> None:
        """登出：撤销 access token 对应的会话（旧 refresh 随之失效）。"""
        claims = self.token_service.decode(access_token, expected_type=ACCESS)
        if claims.sid:
            self.session_service.revoke_session(claims.sid)

    def logout_all(self, user_id: str) -> int:
        """强制退出：撤销某用户全部会话，返回被撤销会话数。"""
        return self.session_service.revoke_all_sessions(user_id)

    def refresh(
        self,
        refresh_token: str,
        *,
        device: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthResultDTO:
        """以 refresh token 换取新的令牌组（旋转：撤销旧会话）。

        Raises:
            DomainError: 令牌无效 / 过期（``AUTH_TOKEN_*``）；已撤销
                （``AUTH_TOKEN_REVOKED``，HTTP 401）。
        """
        record = self.session_service.authenticate_refresh(refresh_token)
        user = self.identity.users.get(record.user_id)
        if user is None or not user.is_active:
            raise DomainError("用户不存在或已停用", code=ErrorCode.UNAUTHORIZED)
        if record.session_id:
            self.session_service.revoke_session(record.session_id)
        tokens = self._issue_tokens(
            tenant_id=record.tenant_id,
            user_id=user.id,
            device=device,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return AuthResultDTO(user=UserDTO.from_entity(user), tokens=tokens)

    def authenticate(self, access_token: str) -> UserDTO:
        """以 access token 鉴权，返回 :class:`UserDTO`。

        Raises:
            DomainError: 无 / 过期 / 篡改（``AUTH_TOKEN_*``）/ 用户不存在
                （``UNAUTHORIZED``）→ HTTP 401。
        """
        claims = self.token_service.decode(access_token, expected_type=ACCESS)
        user = self.identity.users.get(claims.sub)
        if user is None:
            raise DomainError("用户不存在", code=ErrorCode.UNAUTHORIZED)
        if not user.is_active:
            raise DomainError("账号已停用", code=ErrorCode.UNAUTHORIZED)
        return UserDTO.from_entity(user)

    def list_devices(self, user_id: str):
        """列出某用户的全部设备会话。"""
        return self.session_service.list_devices(user_id)

    # -- 内部 --------------------------------------------------------------

    def _issue_tokens(
        self,
        *,
        tenant_id: str,
        user_id: str,
        device: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPairDTO:
        """创建会话并返回令牌组 DTO。"""
        tokens = self.session_service.create_session(
            tenant_id=tenant_id,
            user_id=user_id,
            device=device,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return TokenPairDTO(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=self.access_token_ttl_seconds,
            session_id=tokens.session_id,
        )
