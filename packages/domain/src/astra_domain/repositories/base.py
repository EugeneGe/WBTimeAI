"""仓储接口基类（泛型 Protocol，零 ORM 依赖）。

🔴 ``astra_domain/repositories/`` **只放接口**；SQLAlchemy 实现位于
拥有该聚合的能力包 ``repositories/``（对齐 §2R.0 硬约束）。
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")

__all__ = ["Repository"]


@runtime_checkable
class Repository(Protocol, Generic[T]):
    """通用仓储接口。

    语义与 :class:`astra_database.repository.BaseRepository` 对齐，
    但操作对象为**领域实体**而非 ORM 行。
    """

    def get(self, entity_id: str) -> T | None:
        """按主键获取实体，不存在返回 ``None``。"""
        ...

    def add(self, entity: T) -> T:
        """新增实体并返回（持久化由实现方决定 flush/commit 策略）。"""
        ...

    def list(self, **filters: Any) -> list[T]:
        """按等值条件列出实体。"""
        ...

    def update(self, entity: T) -> T:
        """更新实体并返回。"""
        ...

    def delete(self, entity: T) -> None:
        """删除实体。"""
        ...
