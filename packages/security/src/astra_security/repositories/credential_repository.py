"""``SqlCredentialRepository``（实现领域 ``CredentialRepository``）。

🔴 复用 ``astra_database.BaseRepository``；**仅存密文**（``encrypted_value``）。
凭证明文**不落库 / 不落日志**。

W3 / T2-15 扩展（**不改既有签名**，F22 回归闸）：

- ``_to_record`` / ``add`` 承载 ``name`` / ``status`` / ``last_used_at`` / ``metadata``；
- 关联表 ``model_provider_credential`` 的读写方法（``add_binding`` / ``remove_binding`` /
  ``list_bindings`` / ``mark_used``）—— 多凭证唯一读取 / 写入来源。
"""

from __future__ import annotations

from datetime import datetime

from astra_database import BaseRepository
from astra_database.models.credential import Credential as OrmCredential
from astra_database.models.credential import (
    ModelProviderCredential as OrmModelProviderCredential,
)
from astra_domain import CredentialRecord, ModelProviderCredentialRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

__all__ = ["SqlCredentialRepository"]


def _to_record(row: OrmCredential) -> CredentialRecord:
    """ORM 行 → 领域记录（仅密文字段，绝无明文）。"""
    return CredentialRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        provider=row.provider,
        key_type=row.key_type,
        encrypted_value=row.encrypted_value,
        created_at=row.created_at,
        name=row.name,
        status=row.status,
        last_used_at=row.last_used_at,
        metadata=dict(row.metadata_ or {}),
    )


def _to_binding(row: OrmModelProviderCredential) -> ModelProviderCredentialRecord:
    """ORM 关联行 → 领域关联记录。"""
    return ModelProviderCredentialRecord(
        id=row.id,
        provider_id=row.provider_id,
        credential_id=row.credential_id,
        weight=row.weight,
        status=row.status,
        created_at=row.created_at,
    )


class SqlCredentialRepository(BaseRepository[OrmCredential]):
    """基于 SQLAlchemy 的凭证仓储（仅密文）。"""

    model = OrmCredential

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmCredential)

    def get(self, credential_id: str) -> CredentialRecord | None:  # type: ignore[override]
        row = super().get(credential_id)
        return _to_record(row) if row is not None else None

    def list_by_tenant(self, tenant_id: str) -> list[CredentialRecord]:
        """列出某租户下的全部凭证记录。"""
        statement = (
            select(OrmCredential)
            .where(OrmCredential.tenant_id == tenant_id)
            .order_by(OrmCredential.created_at.asc())
        )
        rows = self.session.execute(statement).scalars().all()
        return [_to_record(row) for row in rows]

    def add(self, record: CredentialRecord) -> CredentialRecord:  # type: ignore[override]
        row = OrmCredential(
            id=record.id,
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
            provider=record.provider,
            key_type=record.key_type,
            encrypted_value=record.encrypted_value,
            name=record.name,
            status=record.status,
            last_used_at=record.last_used_at,
            metadata_=dict(record.metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return _to_record(row)

    def delete(self, credential_id: str) -> None:  # type: ignore[override]
        row = self.session.get(OrmCredential, credential_id)
        if row is not None:
            super().delete(row)

    # -- 关联表 ``model_provider_credential``（W3 / T2-15） ----------------------

    def add_binding(
        self,
        *,
        provider_id: str,
        credential_id: str,
        weight: int = 1,
        status: str = "ACTIVE",
    ) -> ModelProviderCredentialRecord:
        """新增 / 更新 ``(provider_id, credential_id)`` 关联（**幂等** upsert）。"""
        existing = self._get_binding_row(provider_id, credential_id)
        if existing is not None:
            existing.weight = weight
            existing.status = status
            self.session.flush()
            return _to_binding(existing)
        row = OrmModelProviderCredential(
            provider_id=provider_id,
            credential_id=credential_id,
            weight=weight,
            status=status,
        )
        self.session.add(row)
        self.session.flush()
        return _to_binding(row)

    def remove_binding(self, *, provider_id: str, credential_id: str) -> None:
        """删除关联行（**不删共享 Credential**；不存在则静默）。"""
        row = self._get_binding_row(provider_id, credential_id)
        if row is not None:
            self.session.delete(row)
            self.session.flush()

    def list_bindings(self, provider_id: str) -> list[ModelProviderCredentialRecord]:
        """列出某提供方的全部关联记录（按 ``created_at`` 升序）。"""
        statement = (
            select(OrmModelProviderCredential)
            .where(OrmModelProviderCredential.provider_id == provider_id)
            .order_by(OrmModelProviderCredential.created_at.asc())
        )
        rows = self.session.execute(statement).scalars().all()
        return [_to_binding(row) for row in rows]

    def get_binding(
        self, *, provider_id: str, credential_id: str
    ) -> ModelProviderCredentialRecord | None:
        """按 ``(provider_id, credential_id)`` 取关联记录。"""
        row = self._get_binding_row(provider_id, credential_id)
        return _to_binding(row) if row is not None else None

    def mark_used(self, credential_id: str, *, when: datetime) -> None:
        """更新凭证 ``last_used_at``（不存在则静默）。"""
        row = self.session.get(OrmCredential, credential_id)
        if row is not None:
            row.last_used_at = when
            self.session.flush()

    def _get_binding_row(
        self, provider_id: str, credential_id: str
    ) -> OrmModelProviderCredential | None:
        """按唯一键 ``(provider_id, credential_id)`` 取 ORM 关联行。"""
        statement = select(OrmModelProviderCredential).where(
            OrmModelProviderCredential.provider_id == provider_id,
            OrmModelProviderCredential.credential_id == credential_id,
        )
        return self.session.execute(statement).scalars().first()
