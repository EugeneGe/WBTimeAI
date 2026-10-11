"""Repository 基类（方言无关的 CRUD 骨架）+ ``ScopeFilter`` 接入。

上层的具体仓储继承 :class:`BaseRepository`，仅需声明 ``model``。
不区分 SQLite / PostgreSQL —— 差异由 SQLAlchemy 与 :mod:`astra_database.types` 吸收。

🔴 **``ScopeFilter`` 加性接入（Phase 2 · W7 / T2-40；W7 裁定 §6.2 / R13）**：

- ``scope: ScopeFilter | None = None`` —— **加性形参**，缺省 ``None`` ＝ **行为与现状完全一致**
  （仅维持既有 ``tenant_id`` 硬过滤，不额外过滤）；
- ``_apply_scope`` 把 ``tenant_id``（硬隔离，I-1/I-2）**恒加**，``organization_id`` /
  ``workspace_id`` **可选叠加**（缺省不过滤）；
- ``organization_id`` 的**硬隔离**由 **Phase 3a** 启用（本波**只提供契约**，不得在本波强制）。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from astra_domain import ScopeFilter
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .base import Base

ModelT = TypeVar("ModelT", bound=Base)

__all__ = ["BaseRepository", "apply_scope"]


def apply_scope(statement: Select[Any], model: type[Any], scope: ScopeFilter | None) -> Select[Any]:
    """把 ``scope`` 的租户 / 组织 / 工作区谓词**叠加**到 ``statement``。

    供**两类仓储风格**共用（W7 裁定 §6.3，F8）：

    - 风格①（:class:`BaseRepository` 子类）经 :meth:`BaseRepository._apply_scope` 复用；
    - 风格②（自持 ``sessionmaker`` + ``session_scope`` 的仓储）在 ``list`` 等方法**显式调用**。

    语义（W7 裁定 §6.2 / §6.4）：

    - ``scope is None`` → 原样返回（缺省不额外过滤，R13 向后兼容）；
    - ``tenant_id``：模型含该列时**恒加**（硬隔离 I-1/I-2，叠加而非替代）；
    - ``organization_id`` / ``workspace_id``：仅当 ``scope`` 提供该值**且**模型含对应列时叠加
      （``hasattr`` 缺列保护，L2/L3 表无列时不加谓词）。

    Args:
        statement: 已构造的 ``SELECT`` 语句。
        model: ORM 模型类（用于 ``hasattr`` 缺列保护）。
        scope: 查询范围过滤；``None`` 表示不额外过滤。

    Returns:
        叠加过滤后的 ``SELECT`` 语句（``scope is None`` 时为原语句）。
    """
    if scope is None:
        return statement
    if hasattr(model, "tenant_id"):
        statement = statement.where(model.tenant_id == scope.tenant_id)
    if scope.organization_id is not None and hasattr(model, "organization_id"):
        statement = statement.where(model.organization_id == scope.organization_id)
    if scope.workspace_id is not None and hasattr(model, "workspace_id"):
        statement = statement.where(model.workspace_id == scope.workspace_id)
    return statement


class BaseRepository(Generic[ModelT]):
    """通用仓储基类。

    Attributes:
        model: 绑定的 ORM 模型类（子类必须设置，或在构造时传入）。
        session: 当前数据库会话。
        scope: 缺省查询范围（可空）；``list`` 未显式传 ``scope`` 时回退使用。
    """

    model: type[ModelT]

    def __init__(
        self,
        session: Session,
        model: type[ModelT] | None = None,
        scope: ScopeFilter | None = None,
    ) -> None:
        self.session = session
        if model is not None:
            self.model = model
        self.scope = scope

    def add(self, entity: ModelT) -> ModelT:
        """新增实体并 flush（不提交事务）。"""
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: Any) -> ModelT | None:
        """按主键获取实体，不存在返回 ``None``。"""
        return self.session.get(self.model, entity_id)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> list[ModelT]:
        """按等值条件列出实体，并叠加 ``scope`` 过滤。

        Args:
            scope: 查询范围过滤；``None`` 时回退使用构造时的 ``self.scope``
                （二者都为空则仅维持既有行为，不额外过滤）。
            **filters: 等值过滤条件（``列 == 值``）。
        """
        statement = select(self.model)
        for field, value in filters.items():
            statement = statement.where(getattr(self.model, field) == value)
        statement = self._apply_scope(statement, self.scope if scope is None else scope)
        return list(self.session.execute(statement).scalars().all())

    def _apply_scope(self, statement: Select[Any], scope: ScopeFilter | None) -> Select[Any]:
        """把 ``scope`` 谓词叠加到 ``statement``（见 :func:`apply_scope`）。"""
        return apply_scope(statement, self.model, scope)

    def update(self, entity: ModelT) -> ModelT:
        """更新实体（merge + flush）。"""
        merged = self.session.merge(entity)
        self.session.flush()
        return merged

    def delete(self, entity: ModelT) -> None:
        """删除实体并 flush。"""
        self.session.delete(entity)
        self.session.flush()
