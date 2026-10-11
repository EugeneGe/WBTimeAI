"""ORM 行 ↔ 领域 ``ModelProvider`` / ``Model`` 映射。

将 ``astra_database.models.model`` 的 SQLAlchemy 行转换为 ``astra_domain`` 的
:class:`~astra_domain.entities.model.ModelProvider` / :class:`~astra_domain.entities.model.Model`
（及反向），使领域层保持零框架依赖（C-03）。

⚠️ ORM 表（W2 / T1-07）未含时间戳列，故 ``to_domain`` 的时间戳以当前 UTC 回退。
"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_domain import Model, ModelProvider

from ..models.model import Model as OrmModel
from ..models.model import ModelProvider as OrmModelProvider

__all__ = [
    "model_provider_to_domain",
    "model_provider_to_orm",
    "model_to_domain",
    "model_to_orm",
]


def _dt(value: object):
    """归一化时间戳：``None`` 时回退当前 UTC（ORM 无时间戳列）。"""
    return value if value is not None else utcnow()


def model_provider_to_domain(row: OrmModelProvider) -> ModelProvider:
    """ORM 提供方行 → 领域 ``ModelProvider``。"""
    return ModelProvider(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workspace_id=row.workspace_id,
        name=row.name,
        type=row.type,
        endpoint=row.endpoint,
        credential_id=row.credential_id,
        status=row.status,
        config=dict(row.config) if row.config else {},
    )


def model_provider_to_orm(entity: ModelProvider) -> OrmModelProvider:
    """领域 ``ModelProvider`` → ORM 行。"""
    return OrmModelProvider(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        name=entity.name,
        type=entity.type,
        endpoint=entity.endpoint,
        credential_id=entity.credential_id,
        status=entity.status,
        config=dict(entity.config) if entity.config else {},
    )


def model_to_domain(row: OrmModel) -> Model:
    """ORM 模型行 → 领域 ``Model``。"""
    return Model(
        id=row.id,
        tenant_id=getattr(row, "tenant_id", None),
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        provider_id=row.provider_id,
        name=row.name,
        type=row.type,
        context_window=row.context_window,
        capabilities=dict(row.capabilities) if row.capabilities else {},
        status=row.status,
    )


def model_to_orm(entity: Model) -> OrmModel:
    """领域 ``Model`` → ORM 行。"""
    return OrmModel(
        id=entity.id,
        provider_id=entity.provider_id,
        name=entity.name,
        type=entity.type,
        context_window=entity.context_window,
        capabilities=dict(entity.capabilities) if entity.capabilities else {},
        status=entity.status,
    )
