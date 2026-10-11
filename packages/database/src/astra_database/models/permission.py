"""Resource Permission ORM 表（设计 §2.10；W3 裁定 §1）。

- :class:`ResourcePermission`：**权限单一判定链**（§2.10.1）的主体级授权载体
  （``subject（role/user/agent）× resource_type × resource_id? × action → effect``）。

🔴 表结构随迁移 **``0010_phase2_permission_plugin``**（2a）落地；``effect`` **仅**
   ``ALLOW`` / ``DENY``（**无 ``APPROVAL``**，Erratum-G）。

🔴 **类型级（``resource_id IS NULL``）唯一性由应用层 ``upsert`` 保证**（SQL 唯一约束不判重
   NULL，W3 裁定 §1.1）；实例级由 DB 唯一键（6 键）保证。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["ResourcePermission"]

#: 6 键唯一约束名（对齐设计 §2.15.4）。
UQ_RESOURCE_PERMISSION = "uq_resource_permission_subject_resource_action"


class ResourcePermission(Base, TimestampMixin):
    """资源权限条目（主体级授权；设计 §2.10）。"""

    __tablename__ = "resource_permission"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "action",
            name=UQ_RESOURCE_PERMISSION,
        ),
        Index(
            "ix_resource_permission_subject",
            "tenant_id",
            "subject_type",
            "subject_id",
        ),
        Index(
            "ix_resource_permission_resource",
            "tenant_id",
            "resource_type",
            "resource_id",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[str] = mapped_column(GUID(), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    effect: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
