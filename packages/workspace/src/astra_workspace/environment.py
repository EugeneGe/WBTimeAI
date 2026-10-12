"""Workspace Environment 用例（``env_vars`` 仅非敏感 + 敏感值引用注入；W7 / T2-38）。

设计要点（§3.2 / §2.8）：

- ``env_vars`` **仅承载非敏感项**（明文标量），落库；
- **敏感值**（Token / 密码 / 密钥…）**只存引用**，形如 ``{"$ref": "credential:<id>"}``
  或 ``{"$ref": "secret:<NAME>"}``；真实明文**仅在需要时**（注入沙箱前）**内存解析**，
  **绝不落库**（🔴 沙箱内不得落 Host 真实密钥）；
- 对被判定为敏感的 **键名**（``*TOKEN*`` / ``*SECRET*`` / ``*PASSWORD*`` / ``*KEY*`` …），
  若提供了**明文标量** → 拒绝（``VALIDATION_ERROR``），强制走引用。

依赖经注入：:class:`CredentialResolver`（结构化满足 ``astra_security.CredentialServiceDecoder``）
与 :class:`SecretProvider`（结构化满足 ``astra_security.SecretProvider``）——本模块**不 import**
``astra_security`` 运行时对象，保持能力包零硬依赖。
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from sqlalchemy.orm import Session, sessionmaker

from .domain import WorkspaceEnvironment
from .repositories import SqlWorkspaceEnvironmentRepository

__all__ = [
    "EnvironmentService",
    "CredentialResolver",
    "SecretResolver",
    "SENSITIVE_KEY_PATTERN",
    "REF_KEY",
    "REF_PREFIX_CREDENTIAL",
    "REF_PREFIX_SECRET",
]

#: 引用对象保留键（``{"$ref": "<prefix>:<name>"}``）。
REF_KEY = "$ref"

#: 引用前缀。
REF_PREFIX_CREDENTIAL = "credential:"
REF_PREFIX_SECRET = "secret:"

#: 敏感键名模式（命中且为明文标量 → 拒绝，强制走引用）。
#: R5 补全轮（R5A-06）：增补 ``AUTHORIZATION`` / ``BEARER``（HTTP ``Authorization: Bearer``
#: 头键名同源敏感；``re.IGNORECASE`` 已具备，大小写不敏感）。
SENSITIVE_KEY_PATTERN = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|"
    r"CREDENTIAL|AUTHORIZATION|BEARER)",
    re.IGNORECASE,
)


@runtime_checkable
class CredentialResolver(Protocol):
    """凭证解密器（结构化满足 ``astra_security.CredentialServiceDecoder``）。"""

    def decrypt(self, credential_id: str) -> str:
        """按 ``credential_id`` 解密为明文（仅内存）。"""
        ...


@runtime_checkable
class SecretResolver(Protocol):
    """机密读取器（结构化满足 ``astra_security.SecretProvider``）。"""

    def get(self, name: str, default: str | None = None) -> str | None:
        """按名读取机密（缺省返回 ``default``）。"""
        ...


class EnvironmentService:
    """工作区运行环境用例（非敏感明文 + 敏感引用）。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        credential_resolver: CredentialResolver | None = None,
        secret_provider: SecretResolver | None = None,
    ) -> None:
        """构造。

        Args:
            session_factory: SQLAlchemy 会话工厂。
            credential_resolver: 凭证解密器（可选；解析 ``credential:`` 引用）。
            secret_provider: 机密读取器（可选；解析 ``secret:`` 引用）。
        """
        self._session_factory = session_factory
        self._credential_resolver = credential_resolver
        self._secret_provider = secret_provider

    # -- 写 / 读 ------------------------------------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        env_vars: dict[str, Any] | None = None,
        runtime: dict[str, Any] | None = None,
    ) -> WorkspaceEnvironment:
        """创建运行环境（``env_vars`` 经校验/规范化，仅存非敏感明文与引用）。

        Raises:
            DomainError: 名称为空、键名为敏感却给明文、或引用结构非法（``VALIDATION_ERROR``）。
        """
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise DomainError(
                "环境名称不能为空", code=ErrorCode.VALIDATION_ERROR, data={"field": "name"}
            )
        safe_env = self._normalize_env_vars(env_vars or {})
        with session_scope(self._session_factory) as session:
            return SqlWorkspaceEnvironmentRepository(session).add(
                WorkspaceEnvironment(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    name=normalized_name,
                    env_vars=safe_env,
                    runtime=dict(runtime) if runtime else {},
                )
            )

    def get(self, environment_id: str, *, tenant_id: str) -> WorkspaceEnvironment:
        """按 id 获取环境（**校验租户归属**）。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``）。
        """
        with session_scope(self._session_factory) as session:
            environment = SqlWorkspaceEnvironmentRepository(session).get(environment_id)
            if environment is None or environment.tenant_id != tenant_id:
                raise DomainError(
                    "运行环境不存在",
                    code=ErrorCode.NOT_FOUND,
                    data={"environment_id": environment_id},
                )
            return environment

    def list_for_workspace(
        self, workspace_id: str, *, tenant_id: str
    ) -> list[WorkspaceEnvironment]:
        """列出某工作区下的全部环境（**仅返回同租户**）。"""
        with session_scope(self._session_factory) as session:
            environments = SqlWorkspaceEnvironmentRepository(session).list_by_workspace(
                workspace_id
            )
        return [env for env in environments if env.tenant_id == tenant_id]

    def get_by_name(
        self, workspace_id: str, name: str, *, tenant_id: str
    ) -> WorkspaceEnvironment | None:
        """按 ``(workspace_id, name)`` 获取环境（唯一键语义；租户校验）。"""
        with session_scope(self._session_factory) as session:
            environment = SqlWorkspaceEnvironmentRepository(session).get_by_name(workspace_id, name)
        if environment is None or environment.tenant_id != tenant_id:
            return None
        return environment

    # -- 解析（仅内存，注入沙箱前调用） ------------------------------------

    def resolve_env(self, environment: WorkspaceEnvironment) -> dict[str, str]:
        """把环境定义解析为**可注入沙箱的** ``{name: value}``（敏感明文**仅内存**）。

        🔴 返回字典含敏感明文 → **不得**落库 / 落日志 / 回显；仅供注入 Sandbox 使用。

        Raises:
            DomainError: 引用了未注入的解析器（``CONFIGURATION_ERROR``）或引用结构非法
                （``VALIDATION_ERROR``）。
        """
        resolved: dict[str, str] = {}
        for key, value in (environment.env_vars or {}).items():
            if isinstance(value, dict):
                resolved[key] = self._resolve_ref(value.get(REF_KEY))
            else:
                resolved[key] = str(value)
        return resolved

    # -- 内部：校验 / 解析 --------------------------------------------------

    def _normalize_env_vars(self, env_vars: dict[str, Any]) -> dict[str, Any]:
        """校验并规范化 ``env_vars``（返回**可安全落库**的结构）。

        Raises:
            DomainError: 结构非法或敏感键给明文（``VALIDATION_ERROR``）。
        """
        if not isinstance(env_vars, dict):
            raise DomainError(
                "env_vars 必须为对象", code=ErrorCode.VALIDATION_ERROR, data={"field": "env_vars"}
            )
        normalized: dict[str, Any] = {}
        for key, value in env_vars.items():
            name = str(key)
            if isinstance(value, dict):
                ref = value.get(REF_KEY)
                self._validate_ref(ref, name=name)
                normalized[name] = {REF_KEY: ref}
                continue
            if isinstance(value, (str, int, float, bool)):
                if SENSITIVE_KEY_PATTERN.search(name):
                    raise DomainError(
                        "敏感环境变量必须以引用注入（禁用明文）",
                        code=ErrorCode.VALIDATION_ERROR,
                        data={"field": "env_vars", "name": name},
                    )
                normalized[name] = value
                continue
            raise DomainError(
                "env_vars 的值必须为标量或引用对象",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "env_vars", "name": name},
            )
        return normalized

    @staticmethod
    def _validate_ref(ref: Any, *, name: str) -> None:
        """校验引用对象：必须为 ``credential:<id>`` 或 ``secret:<NAME>`` 字符串。"""
        if not isinstance(ref, str) or not ref.strip():
            raise DomainError(
                "环境变量引用格式非法",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "env_vars", "name": name},
            )
        if not (ref.startswith(REF_PREFIX_CREDENTIAL) or ref.startswith(REF_PREFIX_SECRET)):
            raise DomainError(
                "环境变量引用前缀非法（仅支持 credential: / secret:）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "env_vars", "name": name},
            )

    def _resolve_ref(self, ref: Any) -> str:
        """把引用解析为明文（**仅内存**）。"""
        if not isinstance(ref, str):
            raise DomainError(
                "环境变量引用格式非法", code=ErrorCode.VALIDATION_ERROR, data={"field": REF_KEY}
            )
        if ref.startswith(REF_PREFIX_CREDENTIAL):
            if self._credential_resolver is None:
                raise DomainError(
                    "未注入凭证解析器，无法解析 credential: 引用",
                    code=ErrorCode.CONFIGURATION_ERROR,
                )
            return self._credential_resolver.decrypt(ref[len(REF_PREFIX_CREDENTIAL) :])
        if ref.startswith(REF_PREFIX_SECRET):
            if self._secret_provider is None:
                raise DomainError(
                    "未注入机密读取器，无法解析 secret: 引用",
                    code=ErrorCode.CONFIGURATION_ERROR,
                )
            value = self._secret_provider.get(ref[len(REF_PREFIX_SECRET) :])
            if value is None:
                raise DomainError(
                    "机密不存在",
                    code=ErrorCode.CONFIGURATION_ERROR,
                    data={"field": "env_vars", "ref": ref},
                )
            return value
        raise DomainError(
            "环境变量引用前缀非法（仅支持 credential: / secret:）",
            code=ErrorCode.VALIDATION_ERROR,
            data={"field": "env_vars", "ref": ref},
        )
