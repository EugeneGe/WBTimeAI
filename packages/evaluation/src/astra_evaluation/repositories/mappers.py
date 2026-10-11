"""ORM 行 ↔ 领域实体映射（``EvaluationDataset`` / ``EvaluationCase`` / ``EvaluationRun`` /
``EvaluationResult``）。

将 ``astra_database.models.evaluation`` 的 SQLAlchemy 行与领域实体互转。

🔴 可空时间戳映射用 :func:`_opt_dt`（``None`` 保持 ``None``，禁误填）。
🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import ensure_utc, utcnow
from astra_database.models.evaluation import EvaluationCase as OrmCase
from astra_database.models.evaluation import EvaluationDataset as OrmDataset
from astra_database.models.evaluation import EvaluationResult as OrmResult
from astra_database.models.evaluation import EvaluationRun as OrmRun

from ..domain import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)

__all__ = [
    "dataset_to_domain",
    "dataset_to_orm",
    "case_to_domain",
    "case_to_orm",
    "run_to_domain",
    "run_to_orm",
    "result_to_domain",
    "result_to_orm",
]


def _opt_dt(value: datetime | None) -> datetime | None:
    """归一化**可空**时间戳：``None`` 保持 ``None``，否则转 UTC（禁误填）。"""
    return ensure_utc(value) if value is not None else None


def _dt(value: datetime | None) -> datetime:
    """归一化**非空**时间戳：``None`` 时回退当前 UTC（仅用于非空列 / 基类字段）。"""
    return ensure_utc(value) if value is not None else utcnow()


# -- EvaluationDataset ------------------------------------------------------


def dataset_to_domain(row: OrmDataset) -> EvaluationDataset:
    """ORM ``evaluation_dataset`` 行 → 领域 :class:`~astra_evaluation.domain.EvaluationDataset`。"""
    return EvaluationDataset(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        name=row.name,
        version=int(row.version),
        parent_dataset_id=row.parent_dataset_id,
        status=row.status,
        description=row.description,
        created_by=row.created_by,
    )


def dataset_to_orm(entity: EvaluationDataset) -> OrmDataset:
    """领域 :class:`~astra_evaluation.domain.EvaluationDataset` → ORM ``evaluation_dataset`` 行。"""
    return OrmDataset(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        organization_id=entity.organization_id,
        workspace_id=entity.workspace_id,
        name=entity.name,
        version=int(entity.version),
        parent_dataset_id=entity.parent_dataset_id,
        status=entity.status,
        description=entity.description,
        created_by=entity.created_by,
    )


# -- EvaluationCase ---------------------------------------------------------


def case_to_domain(row: OrmCase) -> EvaluationCase:
    """ORM ``evaluation_case`` 行 → 领域 :class:`~astra_evaluation.domain.EvaluationCase`。"""
    created_at = _dt(getattr(row, "created_at", None))
    return EvaluationCase(
        id=row.id,
        tenant_id=None,
        created_at=created_at,
        updated_at=created_at,
        dataset_id=row.dataset_id,
        case_key=row.case_key,
        input=row.input,
        expected=row.expected,
        assertions=list(row.assertions) if row.assertions else [],
        tags=list(row.tags) if row.tags else None,
        position=int(row.position),
    )


def case_to_orm(entity: EvaluationCase) -> OrmCase:
    """领域 :class:`~astra_evaluation.domain.EvaluationCase` → ORM ``evaluation_case`` 行。"""
    return OrmCase(
        id=entity.id,
        dataset_id=entity.dataset_id,
        case_key=entity.case_key,
        input=entity.input,
        expected=entity.expected,
        assertions=list(entity.assertions) if entity.assertions else None,
        tags=list(entity.tags) if entity.tags is not None else None,
        position=int(entity.position),
        created_at=_dt(entity.created_at),
    )


# -- EvaluationRun ----------------------------------------------------------


def run_to_domain(row: OrmRun) -> EvaluationRun:
    """ORM ``evaluation_run`` 行 → 领域 :class:`~astra_evaluation.domain.EvaluationRun`。"""
    return EvaluationRun(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        dataset_id=row.dataset_id,
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        status=row.status,
        idempotency_key=row.idempotency_key,
        started_at=_opt_dt(row.started_at),
        completed_at=_opt_dt(row.completed_at),
        summary=dict(row.summary) if row.summary else None,
        created_by=row.created_by,
    )


def run_to_orm(entity: EvaluationRun) -> OrmRun:
    """领域 :class:`~astra_evaluation.domain.EvaluationRun` → ORM ``evaluation_run`` 行。"""
    return OrmRun(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        organization_id=entity.organization_id,
        workspace_id=entity.workspace_id,
        dataset_id=entity.dataset_id,
        agent_id=entity.agent_id,
        agent_version_id=entity.agent_version_id,
        status=entity.status,
        idempotency_key=entity.idempotency_key,
        started_at=_opt_dt(entity.started_at),
        completed_at=_opt_dt(entity.completed_at),
        summary=dict(entity.summary) if entity.summary is not None else None,
        created_by=entity.created_by,
    )


# -- EvaluationResult -------------------------------------------------------


def result_to_domain(row: OrmResult) -> EvaluationResult:
    """ORM ``evaluation_result`` 行 → 领域 :class:`~astra_evaluation.domain.EvaluationResult`。"""
    created_at = _dt(getattr(row, "created_at", None))
    return EvaluationResult(
        id=row.id,
        tenant_id=None,
        created_at=created_at,
        updated_at=created_at,
        evaluation_run_id=row.evaluation_run_id,
        case_id=row.case_id,
        agent_run_id=row.agent_run_id,
        status=row.status,
        score=float(row.score) if row.score is not None else None,
        assertion_results=(list(row.assertion_results) if row.assertion_results else None),
        duration_ms=int(row.duration_ms) if row.duration_ms is not None else None,
        token_usage=dict(row.token_usage) if row.token_usage else None,
        cost=float(row.cost) if row.cost is not None else None,
        error_type=row.error_type,
    )


def result_to_orm(entity: EvaluationResult) -> OrmResult:
    """领域 :class:`~astra_evaluation.domain.EvaluationResult` → ORM ``evaluation_result`` 行。"""
    return OrmResult(
        id=entity.id,
        evaluation_run_id=entity.evaluation_run_id,
        case_id=entity.case_id,
        agent_run_id=entity.agent_run_id,
        status=entity.status,
        score=float(entity.score) if entity.score is not None else None,
        assertion_results=(
            list(entity.assertion_results) if entity.assertion_results is not None else None
        ),
        duration_ms=int(entity.duration_ms) if entity.duration_ms is not None else None,
        token_usage=dict(entity.token_usage) if entity.token_usage is not None else None,
        cost=float(entity.cost) if entity.cost is not None else None,
        error_type=entity.error_type,
        created_at=_dt(entity.created_at),
    )
