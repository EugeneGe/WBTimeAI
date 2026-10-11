"""``astra_evaluation`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.13.2 / W9 裁定 §4.1）。

- :class:`EvaluationDatasetRepository`：任务集仓储（L1 租户资源根；``ScopeFilter`` 过滤）；
- :class:`EvaluationCaseRepository`：用例仓储（子资源；经 ``dataset_id`` 推导）；
- :class:`EvaluationRunRepository`：评测仓储（L1 租户资源根；``idempotency_key`` 幂等去重）；
- :class:`EvaluationResultRepository`：结果仓储（子资源；经 ``evaluation_run_id`` 推导）。

SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py``
   ``test_evaluation_package_domain_has_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

import builtins
from typing import Any, Protocol, runtime_checkable

from astra_domain import ScopeFilter

from .entities import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)

__all__ = [
    "EvaluationDatasetRepository",
    "EvaluationCaseRepository",
    "EvaluationRunRepository",
    "EvaluationResultRepository",
]


@runtime_checkable
class EvaluationDatasetRepository(Protocol):
    """``evaluation_dataset`` 仓储接口（L1 租户资源根；``ScopeFilter`` 过滤）。"""

    def get(self, dataset_id: str) -> EvaluationDataset | None:
        """按主键获取任务集，不存在返回 ``None``。"""
        ...

    def add(self, entity: EvaluationDataset) -> EvaluationDataset:
        """新增任务集并返回。"""
        ...

    def update(self, entity: EvaluationDataset) -> EvaluationDataset:
        """更新任务集并返回。"""
        ...

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[EvaluationDataset]:
        """按等值条件列出任务集（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        ...


@runtime_checkable
class EvaluationCaseRepository(Protocol):
    """``evaluation_case`` 仓储接口（子资源；经父推导，无组织列）。"""

    def get(self, case_id: str) -> EvaluationCase | None:
        """按主键获取用例，不存在返回 ``None``。"""
        ...

    def add(self, entity: EvaluationCase) -> EvaluationCase:
        """新增用例并返回。"""
        ...

    def update(self, entity: EvaluationCase) -> EvaluationCase:
        """更新用例并返回。"""
        ...

    def list(self, **filters: Any) -> builtins.list[EvaluationCase]:
        """按等值条件列出用例。"""
        ...

    def list_by_dataset(self, dataset_id: str) -> builtins.list[EvaluationCase]:
        """列出某任务集的全部用例（按 ``position`` 升序）。"""
        ...

    def get_by_key(self, dataset_id: str, case_key: str) -> EvaluationCase | None:
        """按唯一键 ``(dataset_id, case_key)`` 获取用例（无 → ``None``）。"""
        ...


@runtime_checkable
class EvaluationRunRepository(Protocol):
    """``evaluation_run`` 仓储接口（L1 租户资源根；幂等去重）。"""

    def get(self, run_id: str) -> EvaluationRun | None:
        """按主键获取评测，不存在返回 ``None``。"""
        ...

    def add(self, entity: EvaluationRun) -> EvaluationRun:
        """新增评测并返回。"""
        ...

    def update(self, entity: EvaluationRun) -> EvaluationRun:
        """更新评测并返回。"""
        ...

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[EvaluationRun]:
        """按等值条件列出评测（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        ...

    def get_by_idempotency_key(self, idempotency_key: str) -> EvaluationRun | None:
        """按 ``idempotency_key`` 获取评测（**幂等去重**；无 → ``None``）。"""
        ...


@runtime_checkable
class EvaluationResultRepository(Protocol):
    """``evaluation_result`` 仓储接口（子资源；每 case 每 Run 恰一条）。"""

    def get(self, result_id: str) -> EvaluationResult | None:
        """按主键获取结果，不存在返回 ``None``。"""
        ...

    def add(self, entity: EvaluationResult) -> EvaluationResult:
        """新增结果并返回。"""
        ...

    def update(self, entity: EvaluationResult) -> EvaluationResult:
        """更新结果并返回。"""
        ...

    def list(self, **filters: Any) -> builtins.list[EvaluationResult]:
        """按等值条件列出结果。"""
        ...

    def list_by_run(self, evaluation_run_id: str) -> builtins.list[EvaluationResult]:
        """列出某评测的全部结果。"""
        ...

    def get_by_run_case(self, evaluation_run_id: str, case_id: str) -> EvaluationResult | None:
        """按 ``(evaluation_run_id, case_id)`` 获取结果（无 → ``None``）。"""
        ...
