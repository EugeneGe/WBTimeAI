"""Credential ORM 表（设计 §2.7 / §2.15.1；W3 裁定 §5 / A-10）。

- :class:`Credential`：凭证（模型 / MCP 统一承载，**唯一存储**，不新增平行存储 C-07）；
  W3 / T2-15 补 4 列（``name`` / ``status`` / ``last_used_at`` / ``metadata``）；
- :class:`ModelProviderCredential`：``model_provider`` × ``credential`` 关联表
  （多凭证；唯一键 ``(provider_id, credential_id)``）—— **新读取 / 写入唯一来源**；
  旧列 ``model_provider.credential_id`` **deprecated 保留、不 drop**（W3 裁定 §5.3）。

🔴 禁止明文落库 / 落日志：``encrypted_value`` 仅存密文；``name`` / ``metadata`` **不得含明文密钥**
   （C-07 / Erratum-H）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Credential", "ModelProviderCredential"]


class Credential(Base, TimestampMixin):
    """凭证（模型凭证 / MCP 凭证统一承载，不新增平行存储）。"""

    __tablename__ = "credential"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    key_type: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    # -- W3 / T2-15 补 4 列（A-10） ----------------------------------------
    name: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType(), nullable=False, default=dict
    )


class ModelProviderCredential(Base, TimestampMixin):
    """``model_provider`` × ``credential`` 关联表（多凭证；W3 裁定 §5.2）。"""

    __tablename__ = "model_provider_credential"
    __table_args__ = (
        UniqueConstraint("provider_id", "credential_id", name="uq_model_provider_credential"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    provider_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("model_provider.id"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("credential.id"), nullable=False, index=True
    )
    weight: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
