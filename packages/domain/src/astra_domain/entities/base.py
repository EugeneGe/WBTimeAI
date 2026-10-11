"""领域实体基类（纯 dataclass，零框架依赖）。

约定（设计 §2.3.1 / 决策 D2）：

- 所有实体主键 ``id`` 默认经 :func:`astra_core.generate_id`（UUIDv7）生成；
- 统一携带 ``created_at`` / ``updated_at``（UTC，timezone-aware）；
- ``tenant_id`` 承载多租户归属（Tenant-ready），对不需要归属的实体为 ``None``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from astra_common.time import utcnow
from astra_core import generate_id

__all__ = ["Entity", "AggregateRoot"]


@dataclass
class Entity:
    """领域实体基类。

    Attributes:
        id: 实体唯一标识（UUIDv7 字符串，默认经 ``generate_id`` 生成）。
        tenant_id: 所属租户标识（Tenant-ready；不适用时为 ``None``）。
        created_at: 创建时间（UTC）。
        updated_at: 最近更新时间（UTC）。
    """

    id: str = field(default_factory=generate_id)
    tenant_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def touch(self) -> None:
        """将 ``updated_at`` 刷新为当前 UTC 时间。"""
        self.updated_at = utcnow()


@dataclass
class AggregateRoot(Entity):
    """聚合根标记基类。

    用于标识需要通过仓储整体读写的聚合边界；Phase 0 语义从简，
    仅作为类型与意图标记。
    """
