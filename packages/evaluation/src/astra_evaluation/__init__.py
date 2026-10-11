"""Astra AI Evaluation 能力包（``astra_evaluation``；设计 §2.13.2 / W9 裁定 R1）。

- 领域实体 / 常量 / 仓储接口：``astra_evaluation.domain``（``EvaluationDataset`` /
  ``EvaluationCase`` / ``EvaluationRun`` / ``EvaluationResult`` / ``DatasetStatus`` /
  ``RunStatus`` / ``ResultStatus``）；
- SQL 仓储：``astra_evaluation.repositories``（能力包 ORM 落点）；
- 组合工厂：``astra_evaluation.factory``（供组合根装配）；
- 批量执行：``astra_evaluation.runner``（:class:`EvaluationRunner`）+ ``astra_evaluation.launcher``
  （``AgentRunLauncher`` 注入端口）+ ``astra_evaluation.cancel``（A-9 取消传播）；
- 确定性 scorer：``astra_evaluation.scorers``；回归对比：``astra_evaluation.compare``。

包性质：能力包（**仅禁 Web**；SQL 仓储留本包 ``repositories/``；**不 import
``astra_runtime`` / ``astra_agent``**）——创建 ``agent_run`` 经**注入 Protocol**
``AgentRunLauncher``（端口在包内，真实 bridge 由组合根装配）。
"""

from __future__ import annotations

from .cancel import EvaluationCancellation, result_status_for_outcome
from .compare import CompareReport, FailsBreakdown, MetricDelta, compare_runs
from .domain import (
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
    EvaluationCase,
    EvaluationCaseRepository,
    EvaluationDataset,
    EvaluationDatasetRepository,
    EvaluationResult,
    EvaluationResultRepository,
    EvaluationRun,
    EvaluationRunRepository,
    ResultStatus,
    RunStatus,
    assert_dataset_status,
    assert_result_status,
    assert_run_status,
)
from .factory import EvaluationRepositories, build_evaluation_repositories
from .launcher import (
    AgentRunLauncher,
    RunHandle,
    RunOutcome,
    ToolCallView,
    count_tool_denials,
    count_tool_errors,
)
from .repositories import (
    SqlEvaluationCaseRepository,
    SqlEvaluationDatasetRepository,
    SqlEvaluationResultRepository,
    SqlEvaluationRunRepository,
)
from .runner import DEFAULT_MAX_PARALLEL, EvaluationRunner
from .scorers import (
    KNOWN_SCORERS,
    SCORER_CONTAINS,
    SCORER_EXACT_MATCH,
    SCORER_FIELD_ASSERT,
    SCORER_JSON_SCHEMA,
    SCORER_NOT_CONTAINS,
    SCORER_NUMERIC_RANGE,
    SCORER_TOOL_CALL_SEQUENCE,
    CaseScore,
    score_case,
    validate_assertions,
)

__all__ = [
    # 实体
    "EvaluationDataset",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationResult",
    # 枚举
    "DatasetStatus",
    "RunStatus",
    "ResultStatus",
    # 常量
    "DATASET_STATUS_DRAFT",
    "DATASET_STATUS_PUBLISHED",
    "DATASET_STATUS_ARCHIVED",
    "RUN_STATUS_QUEUED",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_CANCELLED",
    "RESULT_STATUS_SUCCESS",
    "RESULT_STATUS_FAILED",
    "RESULT_STATUS_CANCELLED",
    "DEFAULT_DATASET_VERSION",
    "CANCELLED_ERROR_TYPE",
    # 校验
    "assert_dataset_status",
    "assert_run_status",
    "assert_result_status",
    # 仓储接口
    "EvaluationDatasetRepository",
    "EvaluationCaseRepository",
    "EvaluationRunRepository",
    "EvaluationResultRepository",
    # SQL 仓储
    "SqlEvaluationDatasetRepository",
    "SqlEvaluationCaseRepository",
    "SqlEvaluationRunRepository",
    "SqlEvaluationResultRepository",
    # 组合工厂
    "EvaluationRepositories",
    "build_evaluation_repositories",
    # 端口 / 批量执行 / 取消
    "AgentRunLauncher",
    "RunHandle",
    "RunOutcome",
    "ToolCallView",
    "count_tool_errors",
    "count_tool_denials",
    "EvaluationCancellation",
    "result_status_for_outcome",
    "EvaluationRunner",
    "DEFAULT_MAX_PARALLEL",
    # scorer
    "SCORER_EXACT_MATCH",
    "SCORER_JSON_SCHEMA",
    "SCORER_FIELD_ASSERT",
    "SCORER_CONTAINS",
    "SCORER_NOT_CONTAINS",
    "SCORER_NUMERIC_RANGE",
    "SCORER_TOOL_CALL_SEQUENCE",
    "KNOWN_SCORERS",
    "CaseScore",
    "score_case",
    "validate_assertions",
    # 回归对比
    "MetricDelta",
    "FailsBreakdown",
    "CompareReport",
    "compare_runs",
]
