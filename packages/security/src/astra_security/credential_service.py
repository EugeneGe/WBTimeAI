"""``CredentialService``——凭证安全服务（设计 §2.7 / §2S.0.2）。

以 :class:`~astra_security.crypto.AesGcmCipher` 加密明文后落库，**仅存密文**：

- :meth:`store`：加密 → 落 ``credential`` 表 → 返回**掩码**视图；
- :meth:`list_masked`：返回掩码视图（**永不返回明文 / 密文**）；
- :meth:`delete`：删除凭证。

🔴 明文**不落库 / 不落日志 / 不回显**；对外一律仅返回 ``masked_value``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_domain import CredentialRecord, ModelProviderCredentialRecord
from sqlalchemy.orm import Session, sessionmaker

from .crypto import AesGcmCipher
from .repositories import SqlCredentialRepository

__all__ = [
    "MaskedCredential",
    "ModelProviderCredentialView",
    "CredentialService",
    "CredentialServiceDecoder",
    "mask_secret",
]

#: 掩码固定占位长度（短密钥）。
_MASK_PLACEHOLDER = "********"


def mask_secret(value: str) -> str:
    """生成明文的最小暴露掩码（仅保留首 4 / 末 4 字符，中间以 ``...``）。

    Args:
        value: 明文。

    Returns:
        掩码字符串；明文过短时返回固定占位。
    """
    if not value:
        return ""
    if len(value) <= 8:
        return _MASK_PLACEHOLDER
    return f"{value[:4]}...{value[-4:]}"


@dataclass
class MaskedCredential:
    """凭证的掩码视图（对外安全表示，**不含明文 / 密文**）。

    Attributes:
        id: 凭证标识。
        tenant_id: 所属租户标识。
        workspace_id: 所属工作区标识（可空）。
        provider: 提供方。
        key_type: 键类型。
        masked_value: 掩码值（如 ``sk-1...cdef``）。
        created_at: 创建时间（UTC）。
        name: 人类可读名（W3 / T2-15；可空）。
        status: 状态（``ACTIVE`` / ``DISABLED``）。
        last_used_at: 最近使用时间（UTC，可空）。
    """

    id: str
    tenant_id: str
    provider: str
    key_type: str
    masked_value: str
    workspace_id: str | None = None
    created_at: datetime | None = None
    name: str | None = None
    status: str = "ACTIVE"
    last_used_at: datetime | None = None


@dataclass
class ModelProviderCredentialView:
    """``model_provider`` × ``credential`` 关联视图（对外安全表示，仅掩码；W3 / T2-15）。

    Attributes:
        provider_id: 模型提供方标识。
        credential_id: 凭证标识。
        weight: 加权轮询权重。
        status: 关联状态。
        masked_value: 凭证掩码值（**永不含明文 / 密文**）。
        name: 凭证人类可读名（可空）。
        last_used_at: 最近使用时间（UTC，可空）。
    """

    provider_id: str
    credential_id: str
    weight: int
    status: str
    masked_value: str
    name: str | None = None
    last_used_at: datetime | None = None


class CredentialService:
    """凭证安全服务（AES-256-GCM 加密落库，仅返回掩码）。"""

    def __init__(self, session_factory: sessionmaker[Session], cipher: AesGcmCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        # 平滑加权轮询的进程内游标（``provider_id`` → ``credential_id`` → current_weight）。
        self._rr_cursors: dict[str, dict[str, int]] = {}

    def store(
        self,
        *,
        tenant_id: str,
        provider: str,
        key_type: str,
        plaintext: str,
        workspace_id: str | None = None,
    ) -> MaskedCredential:
        """加密并存贮凭证，返回掩码视图。

        Args:
            tenant_id: 所属租户标识。
            provider: 提供方（如 ``openai``）。
            key_type: 键类型（如 ``api_key``）。
            plaintext: 明文密钥（**仅内存**，不落库 / 不落日志）。
            workspace_id: 所属工作区标识（可空）。

        Returns:
            :class:`MaskedCredential`（仅含 ``masked_value``）。

        Raises:
            DomainError: 明文为空（``VALIDATION_ERROR``）。
        """
        if not plaintext:
            raise DomainError(
                "凭证明文不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "value"},
            )
        encrypted = self._cipher.encrypt(plaintext)
        masked = mask_secret(plaintext)
        with session_scope(self._session_factory) as session:
            record = SqlCredentialRepository(session).add(
                CredentialRecord(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    provider=provider,
                    key_type=key_type,
                    encrypted_value=encrypted,
                )
            )
        return MaskedCredential(
            id=record.id,
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
            provider=record.provider,
            key_type=record.key_type,
            masked_value=masked,
            created_at=record.created_at,
        )

    def list_masked(self, tenant_id: str) -> list[MaskedCredential]:
        """列出某租户的全部凭证掩码视图（**永不返回明文 / 密文**）。"""
        with session_scope(self._session_factory) as session:
            records = SqlCredentialRepository(session).list_by_tenant(tenant_id)
            return [self._to_masked(record) for record in records]

    def get(self, credential_id: str) -> CredentialRecord | None:
        """按 id 获取凭证记录（密文；仅供内部服务使用，不对外暴露）。"""
        with session_scope(self._session_factory) as session:
            return SqlCredentialRepository(session).get(credential_id)

    def delete(self, credential_id: str, *, tenant_id: str) -> None:
        """删除凭证（租户校验）。

        Raises:
            DomainError: 不存在或跨租户（``CREDENTIAL_NOT_FOUND``）。
        """
        with session_scope(self._session_factory) as session:
            repo = SqlCredentialRepository(session)
            record = repo.get(credential_id)
            if record is None or record.tenant_id != tenant_id:
                raise DomainError(
                    "凭证不存在",
                    code=ErrorCode.CREDENTIAL_NOT_FOUND,
                    data={"credential_id": credential_id},
                )
            repo.delete(credential_id)

    def _to_masked(self, record: CredentialRecord) -> MaskedCredential:
        """由记录（密文）构造掩码视图：内部解密仅用于派生掩码，**绝不外泄明文**。"""
        try:
            masked = mask_secret(self._cipher.decrypt(record.encrypted_value))
        except DomainError:
            masked = _MASK_PLACEHOLDER
        return MaskedCredential(
            id=record.id,
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
            provider=record.provider,
            key_type=record.key_type,
            masked_value=masked,
            created_at=record.created_at,
            name=record.name,
            status=record.status,
            last_used_at=record.last_used_at,
        )

    # -- W3 / T2-15：多凭证（**新增，不改既有**） -------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        provider: str,
        key_type: str,
        plaintext: str,
        name: str | None = None,
        workspace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MaskedCredential:
        """加密并存贮凭证（含可读名 / 元数据），返回掩码视图。

        与 :meth:`store` 的差异仅在**新增可选字段**；明文纪律不变（C-07）：
        ``plaintext`` 仅内存，仅落 ``encrypted_value``（AES-GCM）；
        ``name`` / ``metadata`` **不得含明文密钥**（服务层校验）。

        Args:
            tenant_id: 所属租户标识。
            provider: 提供方。
            key_type: 键类型。
            plaintext: 明文密钥（**仅内存**）。
            name: 人类可读名（可空；**不得含明文**）。
            workspace_id: 所属工作区标识（可空）。
            metadata: 非敏感元数据（可空；**不得含明文**）。

        Returns:
            :class:`MaskedCredential`（仅含 ``masked_value``，无明文 / 密文）。

        Raises:
            DomainError: 明文为空或 ``name`` / ``metadata`` 含明文（``VALIDATION_ERROR``）。
        """
        if not plaintext:
            raise DomainError(
                "凭证明文不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "value"},
            )
        safe_metadata = dict(metadata or {})
        self._assert_no_plaintext(plaintext, name=name, metadata=safe_metadata)
        encrypted = self._cipher.encrypt(plaintext)
        with session_scope(self._session_factory) as session:
            record = SqlCredentialRepository(session).add(
                CredentialRecord(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    provider=provider,
                    key_type=key_type,
                    encrypted_value=encrypted,
                    name=name,
                    status="ACTIVE",
                    metadata=safe_metadata,
                )
            )
        return self._to_masked(record)

    def bind_to_provider(
        self,
        *,
        provider_id: str,
        credential_id: str,
        weight: int = 1,
        status: str = "ACTIVE",
    ) -> None:
        """把 ``credential_id`` 绑定到 ``provider_id``（**幂等** upsert；仅写关联行）。

        Raises:
            DomainError: ``weight`` 非法（``VALIDATION_ERROR``）。
        """
        if weight < 0:
            raise DomainError(
                "权重不能为负",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "weight", "value": weight},
            )
        with session_scope(self._session_factory) as session:
            SqlCredentialRepository(session).add_binding(
                provider_id=provider_id,
                credential_id=credential_id,
                weight=weight,
                status=status,
            )

    def unbind_from_provider(self, *, provider_id: str, credential_id: str) -> None:
        """解除 ``provider_id`` 与 ``credential_id`` 的关联（**只删关联行**）。

        🔴 **不删除共享 Credential**（同一凭证可被多个 Provider / 用途复用；C-07）。
        """
        with session_scope(self._session_factory) as session:
            SqlCredentialRepository(session).remove_binding(
                provider_id=provider_id, credential_id=credential_id
            )

    def credentials_for_provider(self, provider_id: str) -> list[ModelProviderCredentialView]:
        """列出某 Provider 的全部关联凭证视图（仅掩码，**永不含明文 / 密文**）。"""
        with session_scope(self._session_factory) as session:
            repo = SqlCredentialRepository(session)
            bindings = repo.list_bindings(provider_id)
            return [self._to_view(repo, binding) for binding in bindings]

    def select_for_provider(self, provider_id: str) -> ModelProviderCredentialView:
        """按**平滑加权轮询**选取一个可用关联（仅 ``status=="ACTIVE"`` 且 ``weight>0``）。

        Returns:
            :class:`ModelProviderCredentialView`（仅掩码）。

        Raises:
            DomainError: 无可用关联（``CONFIGURATION_ERROR``）。
        """
        with session_scope(self._session_factory) as session:
            repo = SqlCredentialRepository(session)
            bindings = repo.list_bindings(provider_id)
            active = [
                binding for binding in bindings if binding.status == "ACTIVE" and binding.weight > 0
            ]
            if not active:
                raise DomainError(
                    "无可用凭证关联",
                    code=ErrorCode.CONFIGURATION_ERROR,
                    data={"provider_id": provider_id},
                )
            chosen = self._swrr_select(provider_id, active)
            return self._to_view(repo, chosen)

    def mark_used(self, credential_id: str) -> None:
        """更新凭证 ``last_used_at`` 为当前时间（不存在则静默）。"""
        with session_scope(self._session_factory) as session:
            SqlCredentialRepository(session).mark_used(credential_id, when=utcnow())

    def _to_view(
        self, repo: SqlCredentialRepository, binding: ModelProviderCredentialRecord
    ) -> ModelProviderCredentialView:
        """把关联记录 + 凭证记录组合为掩码视图。"""
        record = repo.get(binding.credential_id)
        if record is None:
            masked = _MASK_PLACEHOLDER
            name: str | None = None
            last_used_at: datetime | None = None
        else:
            masked = self._masked_value(record)
            name = record.name
            last_used_at = record.last_used_at
        return ModelProviderCredentialView(
            provider_id=binding.provider_id,
            credential_id=binding.credential_id,
            weight=binding.weight,
            status=binding.status,
            masked_value=masked,
            name=name,
            last_used_at=last_used_at,
        )

    def _masked_value(self, record: CredentialRecord) -> str:
        """由记录（密文）派生掩码（绝不外泄明文）。"""
        try:
            return mask_secret(self._cipher.decrypt(record.encrypted_value))
        except DomainError:
            return _MASK_PLACEHOLDER

    def _swrr_select(
        self, provider_id: str, active: list[ModelProviderCredentialRecord]
    ) -> ModelProviderCredentialRecord:
        """平滑加权轮询（nginx 风格）：进程内游标保证权重占比 ``weight/Σweight``。

        仅参与项为**已过滤**的 ``active``（``ACTIVE`` 且 ``weight>0``）；权重相等时退化为
        普通轮询。
        """
        cursors = self._rr_cursors.setdefault(provider_id, {})
        total = sum(binding.weight for binding in active)
        for binding in active:
            cursors[binding.credential_id] = cursors.get(binding.credential_id, 0) + binding.weight
        chosen = max(active, key=lambda binding: cursors[binding.credential_id])
        cursors[chosen.credential_id] -= total
        # 清理已不在集合中的历史游标，避免无界增长。
        active_ids = {binding.credential_id for binding in active}
        for stale in [key for key in cursors if key not in active_ids]:
            del cursors[stale]
        return chosen

    def _assert_no_plaintext(
        self,
        plaintext: str,
        *,
        name: str | None,
        metadata: dict[str, Any],
    ) -> None:
        """校验 ``name`` / ``metadata`` 不含明文密钥（C-07 / Erratum-H）。

        Raises:
            DomainError: 检出明文（``VALIDATION_ERROR``）。
        """
        haystacks: list[str] = []
        if name:
            haystacks.append(name)
        for value in metadata.values():
            haystacks.append(value if isinstance(value, str) else repr(value))
        for haystack in haystacks:
            if plaintext in haystack:
                raise DomainError(
                    "可读名 / 元数据不得包含明文密钥",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={"field": "plaintext_leak"},
                )


class CredentialServiceDecoder:
    """``astra_domain.CredentialDecoder`` Protocol 的 adapter（W6 / T1-30）。

    把 :class:`CredentialService`（仅存密文）+ :class:`AesGcmCipher` 组合为**显式解密**能力，
    供抽象包 ``astra_model`` 面向领域 Protocol 解密（避免 ``astra_model`` 传递依赖
    ``astra_security``，F21）。**明文仅内存**，不落库 / 不落日志 / 不回显（C-07）。

    本 adapter **结构化满足** :class:`~astra_domain.CredentialDecoder`（无需显式继承）。
    """

    def __init__(self, credential_service: CredentialService, cipher: AesGcmCipher) -> None:
        self._service = credential_service
        self._cipher = cipher

    def decrypt(self, credential_id: str) -> str:
        """按 ``credential_id`` 解密为明文（仅内存）。

        Raises:
            DomainError: 凭证不存在（``CREDENTIAL_NOT_FOUND``）或密文非法（``VALIDATION_ERROR``）。
        """
        record = self._service.get(credential_id)
        if record is None:
            raise DomainError(
                "凭证不存在",
                code=ErrorCode.CREDENTIAL_NOT_FOUND,
                data={"credential_id": credential_id},
            )
        return self._cipher.decrypt(record.encrypted_value)
