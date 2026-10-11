"""``astra_evaluation`` 领域子模块（实体 / 常量 / 仓储接口；W9 / T2-45）。

本子模块**零 Web / ORM**（受 ``test_layering.py``
``test_evaluation_package_domain_has_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from .entities import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from .kinds import (
    CANCELLED_ERROR_TYPE,
    DATASET_STATUS_ARCHIVED,
    DATASET_STATUS_DRAFT,
    DATASET_STATUS_PUBLISHED,
    DEFAULT_DATASET_VERSION,
    RESULT_STATUS_CANCELLED,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_SUCCESS,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_FAILED,
    RUN_STATUS_QUEUED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    DatasetStatus,
    ResultStatus,
    RunStatus,
    assert_dataset_status,
    assert_result_status,
    assert_run_status,
)
from .repository import (
    EvaluationCaseRepository,
    EvaluationDatasetRepository,
    EvaluationResultRepository,
    EvaluationRunRepository,
)

__all__ = [
    # 实体
    "EvaluationDataset",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationResult",
    # 常量 · DatasetStatus
    "DATASET_STATUS_DRAFT",
    "DATASET_STATUS_PUBLISHED",
    "DATASET_STATUS_ARCHIVED",
    # 常量 · RunStatus
    "RUN_STATUS_QUEUED",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_CANCELLED",
    # 常量 · ResultStatus
    "RESULT_STATUS_SUCCESS",
    "RESULT_STATUS_FAILED",
    "RESULT_STATUS_CANCELLED",
    # 常量 · 通用
    "DEFAULT_DATASET_VERSION",
    "CANCELLED_ERROR_TYPE",
    # 枚举
    "DatasetStatus",
    "RunStatus",
    "ResultStatus",
    # 校验
    "assert_dataset_status",
    "assert_run_status",
    "assert_result_status",
    # 仓储接口
    "EvaluationDatasetRepository",
    "EvaluationCaseRepository",
    "EvaluationRunRepository",
    "EvaluationResultRepository",
]
