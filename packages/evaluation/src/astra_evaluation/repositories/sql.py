"""``astra_evaluation`` SQL 仓储实现（能力包显式 ORM 落点；W9 / T2-45）。

- :class:`SqlEvaluationDatasetRepository`（``evaluation_dataset``；``ScopeFilter`` 过滤）；
- :class:`SqlEvaluationCaseRepository`（``evaluation_case``；经 ``dataset_id`` 推导）；
- :class:`SqlEvaluationRunRepository`（``evaluation_run``；``idempotency_key`` 幂等去重）；
- :class:`SqlEvaluationResultRepository`（``evaluation_result``；经 ``evaluation_run_id`` 推导）。

🔴 落在能力包 ``repositories/``（能力包仅禁 Web，ORM 允许）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import apply_scope, session_scope
from astra_database.models.evaluation import EvaluationCase as OrmCase
from astra_database.models.evaluation import EvaluationDataset as OrmDataset
from astra_database.models.evaluation import EvaluationResult as OrmResult
from astra_database.models.evaluation import EvaluationRun as OrmRun
from astra_domain import ScopeFilter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..domain import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from .mappers import (
    case_to_domain,
    case_to_orm,
    dataset_to_domain,
    dataset_to_orm,
    result_to_domain,
    result_to_orm,
    run_to_domain,
    run_to_orm,
)

__all__ = [
    "SqlEvaluationDatasetRepository",
    "SqlEvaluationCaseRepository",
    "SqlEvaluationRunRepository",
    "SqlEvaluationResultRepository",
]


class SqlEvaluationDatasetRepository:
    """基于 SQLAlchemy 的 ``evaluation_dataset`` 仓储。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, dataset_id: str) -> EvaluationDataset | None:
        """按主键获取任务集，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDataset, dataset_id)
            return dataset_to_domain(row) if row is not None else None

    def add(self, entity: EvaluationDataset) -> EvaluationDataset:
        """新增任务集并返回。"""
        with session_scope(self._session_factory) as session:
            row = dataset_to_orm(entity)
            session.add(row)
            session.flush()
            return dataset_to_domain(row)

    def update(self, entity: EvaluationDataset) -> EvaluationDataset:
        """更新任务集并返回（``tenant_id`` 不可改）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDataset, entity.id)
            if row is None:
                return dataset_to_domain(dataset_to_orm(entity))
            row.organization_id = entity.organization_id
            row.workspace_id = entity.workspace_id
            row.name = entity.name
            row.version = int(entity.version)
            row.parent_dataset_id = entity.parent_dataset_id
            row.status = entity.status
            row.description = entity.description
            row.created_by = entity.created_by
            session.flush()
            return dataset_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[EvaluationDataset]:
        """按等值条件列出任务集（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDataset)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmDataset, field) == value)
            statement = apply_scope(statement, OrmDataset, scope)
            rows = session.execute(statement).scalars().all()
            return [dataset_to_domain(row) for row in rows]


class SqlEvaluationCaseRepository:
    """基于 SQLAlchemy 的 ``evaluation_case`` 仓储。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, case_id: str) -> EvaluationCase | None:
        """按主键获取用例，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmCase, case_id)
            return case_to_domain(row) if row is not None else None

    def add(self, entity: EvaluationCase) -> EvaluationCase:
        """新增用例并返回。"""
        with session_scope(self._session_factory) as session:
            row = case_to_orm(entity)
            session.add(row)
            session.flush()
            return case_to_domain(row)

    def update(self, entity: EvaluationCase) -> EvaluationCase:
        """更新用例并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmCase, entity.id)
            if row is None:
                return case_to_domain(case_to_orm(entity))
            row.dataset_id = entity.dataset_id
            row.case_key = entity.case_key
            row.input = entity.input
            row.expected = entity.expected
            row.assertions = list(entity.assertions) if entity.assertions else None
            row.tags = list(entity.tags) if entity.tags is not None else None
            row.position = int(entity.position)
            session.flush()
            return case_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[EvaluationCase]:
        """按等值条件列出用例（按 ``position`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmCase)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmCase, field) == value)
            statement = statement.order_by(OrmCase.position.asc(), OrmCase.created_at.asc())
            rows = session.execute(statement).scalars().all()
            return [case_to_domain(row) for row in rows]

    def list_by_dataset(self, dataset_id: str) -> builtins.list[EvaluationCase]:
        """列出某任务集的全部用例（按 ``position`` 升序）。"""
        return self.list(dataset_id=dataset_id)

    def get_by_key(self, dataset_id: str, case_key: str) -> EvaluationCase | None:
        """按唯一键 ``(dataset_id, case_key)`` 获取用例（无 → ``None``）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmCase).where(
                OrmCase.dataset_id == dataset_id, OrmCase.case_key == case_key
            )
            row = session.execute(statement).scalars().first()
            return case_to_domain(row) if row is not None else None


class SqlEvaluationRunRepository:
    """基于 SQLAlchemy 的 ``evaluation_run`` 仓储。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, run_id: str) -> EvaluationRun | None:
        """按主键获取评测，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmRun, run_id)
            return run_to_domain(row) if row is not None else None

    def add(self, entity: EvaluationRun) -> EvaluationRun:
        """新增评测并返回。"""
        with session_scope(self._session_factory) as session:
            row = run_to_orm(entity)
            session.add(row)
            session.flush()
            return run_to_domain(row)

    def update(self, entity: EvaluationRun) -> EvaluationRun:
        """更新评测并返回（``tenant_id`` 不可改）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmRun, entity.id)
            if row is None:
                return run_to_domain(run_to_orm(entity))
            row.organization_id = entity.organization_id
            row.workspace_id = entity.workspace_id
            row.dataset_id = entity.dataset_id
            row.agent_id = entity.agent_id
            row.agent_version_id = entity.agent_version_id
            row.status = entity.status
            row.idempotency_key = entity.idempotency_key
            row.started_at = entity.started_at
            row.completed_at = entity.completed_at
            row.summary = dict(entity.summary) if entity.summary is not None else None
            row.created_by = entity.created_by
            session.flush()
            return run_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[EvaluationRun]:
        """按等值条件列出评测（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmRun)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmRun, field) == value)
            statement = apply_scope(statement, OrmRun, scope)
            rows = session.execute(statement).scalars().all()
            return [run_to_domain(row) for row in rows]

    def get_by_idempotency_key(self, idempotency_key: str) -> EvaluationRun | None:
        """按 ``idempotency_key`` 获取评测（**幂等去重**；无 → ``None``）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmRun).where(OrmRun.idempotency_key == idempotency_key)
            row = session.execute(statement).scalars().first()
            return run_to_domain(row) if row is not None else None


class SqlEvaluationResultRepository:
    """基于 SQLAlchemy 的 ``evaluation_result`` 仓储。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, result_id: str) -> EvaluationResult | None:
        """按主键获取结果，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmResult, result_id)
            return result_to_domain(row) if row is not None else None

    def add(self, entity: EvaluationResult) -> EvaluationResult:
        """新增结果并返回。"""
        with session_scope(self._session_factory) as session:
            row = result_to_orm(entity)
            session.add(row)
            session.flush()
            return result_to_domain(row)

    def update(self, entity: EvaluationResult) -> EvaluationResult:
        """更新结果并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmResult, entity.id)
            if row is None:
                return result_to_domain(result_to_orm(entity))
            row.evaluation_run_id = entity.evaluation_run_id
            row.case_id = entity.case_id
            row.agent_run_id = entity.agent_run_id
            row.status = entity.status
            row.score = float(entity.score) if entity.score is not None else None
            row.assertion_results = (
                list(entity.assertion_results) if entity.assertion_results is not None else None
            )
            row.duration_ms = int(entity.duration_ms) if entity.duration_ms is not None else None
            row.token_usage = dict(entity.token_usage) if entity.token_usage is not None else None
            row.cost = float(entity.cost) if entity.cost is not None else None
            row.error_type = entity.error_type
            session.flush()
            return result_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[EvaluationResult]:
        """按等值条件列出结果（按 ``created_at`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmResult)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmResult, field) == value)
            statement = statement.order_by(OrmResult.created_at.asc())
            rows = session.execute(statement).scalars().all()
            return [result_to_domain(row) for row in rows]

    def list_by_run(self, evaluation_run_id: str) -> builtins.list[EvaluationResult]:
        """列出某评测的全部结果。"""
        return self.list(evaluation_run_id=evaluation_run_id)

    def get_by_run_case(self, evaluation_run_id: str, case_id: str) -> EvaluationResult | None:
        """按 ``(evaluation_run_id, case_id)`` 获取结果（无 → ``None``）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmResult).where(
                OrmResult.evaluation_run_id == evaluation_run_id,
                OrmResult.case_id == case_id,
            )
            row = session.execute(statement).scalars().first()
            return result_to_domain(row) if row is not None else None
