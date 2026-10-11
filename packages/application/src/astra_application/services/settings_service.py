"""``SettingsService``——设置应用服务（§2S.0.2 / §3-#10）。

- 系统设置：**不含任何密钥类配置**；
- 个人设置：走既有列（``user.display_name``），**不新增列 / 不新增迁移**；
- 凭证：委托 :class:`~astra_security.credential_service.CredentialService`
  （AES-256-GCM 加密落库），对外**仅返回掩码**。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode
from astra_identity import UserService
from astra_security import CredentialService, MaskedCredential

from ..dto.identity import UserDTO
from ..dto.settings import CredentialDTO, PersonalSettingsDTO, SystemSettingsDTO
from .base import ApplicationService

__all__ = ["SettingsService"]


class SettingsService(ApplicationService):
    """设置应用服务（系统 / 个人 / 凭证）。"""

    # 依赖由基类 ``ApplicationService.__init__`` 经 ``setattr`` 注入；此处仅作
    # 类级类型声明（无赋值），供静态类型检查识别实例属性，运行时零影响。
    system: SystemSettingsDTO
    users: UserService
    credentials: CredentialService | None

    def __init__(
        self,
        *,
        system: SystemSettingsDTO,
        users: UserService,
        credentials: CredentialService | None,
    ) -> None:
        super().__init__(system=system, users=users, credentials=credentials)

    # -- 系统设置 ----------------------------------------------------------

    def system_settings(self) -> SystemSettingsDTO:
        """返回系统设置（**不含密钥**）。"""
        return self.system

    # -- 个人设置 ----------------------------------------------------------

    def personal_settings(self, user: UserDTO) -> PersonalSettingsDTO:
        """返回个人设置。"""
        return PersonalSettingsDTO(
            user_id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
        )

    def update_personal(self, user_id: str, *, display_name: str | None) -> PersonalSettingsDTO:
        """更新个人设置（Phase 0 仅 ``display_name``）。"""
        user = self.users.update_profile(user_id, display_name=display_name)
        return PersonalSettingsDTO(
            user_id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
        )

    # -- 凭证（API Key 入口） ----------------------------------------------

    def _require_credentials(self) -> CredentialService:
        """返回凭证服务；未装配时抛 ``CONFIGURATION_ERROR``。"""
        if self.credentials is None:
            raise DomainError(
                "凭证服务未装配（缺少 ASTRA_SECRET_KEY 或凭证 Provider）",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
        return self.credentials

    def save_credential(
        self,
        *,
        tenant_id: str,
        provider: str,
        key_type: str,
        value: str,
        workspace_id: str | None = None,
    ) -> CredentialDTO:
        """保存凭证（加密落库），返回**掩码** DTO（无明文）。"""
        masked: MaskedCredential = self._require_credentials().store(
            tenant_id=tenant_id,
            provider=provider,
            key_type=key_type,
            plaintext=value,
            workspace_id=workspace_id,
        )
        return self._to_dto(masked)

    def list_credentials(self, tenant_id: str) -> list[CredentialDTO]:
        """列出某租户的全部凭证（**仅掩码**）。"""
        return [self._to_dto(item) for item in self._require_credentials().list_masked(tenant_id)]

    def delete_credential(self, credential_id: str, *, tenant_id: str) -> None:
        """删除凭证。"""
        self._require_credentials().delete(credential_id, tenant_id=tenant_id)

    @staticmethod
    def _to_dto(masked: MaskedCredential) -> CredentialDTO:
        """掩码视图 → DTO（**绝不含明文 / 密文**）。"""
        return CredentialDTO(
            id=masked.id,
            provider=masked.provider,
            key_type=masked.key_type,
            masked_value=masked.masked_value,
            workspace_id=masked.workspace_id,
            created_at=masked.created_at,
        )
