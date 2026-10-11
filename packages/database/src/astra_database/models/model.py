"""Model 组 ORM 表（设计 §2.15.1 Model 组 / §2.15.2）。

- :class:`ModelProvider`：模型提供方（``credential_id`` **复用** ``credential`` 表，
  **不建** ``model_credential`` 平行存储，C-07）。
- :class:`Model`：模型目录（能力 / 上下文窗口）。

⚠️ 仅表结构；真实 Provider 实现属 W3，本轮不实现。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import GUID, JSONType

__all__ = ["ModelProvider", "Model"]


class ModelProvider(Base):
    """模型提供方（凭证复用 ``credential``，不新增平行存储）。"""

    __tablename__ = "model_provider"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("credential.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)


class Model(Base):
    """模型目录（能力 / 上下文窗口）。"""

    __tablename__ = "model"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    provider_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("model_provider.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
