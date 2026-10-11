"""Evaluation DTO（W9 / T2-47；设计 §2.13.2 / 裁定 R6）。

纯 dataclass（无框架依赖）；承载 Evaluation 出入参，字段与前端冻结契约**逐字一致**
（snake_case）：

- :class:`EvaluationDatasetDTO` / :class:`EvaluationCaseDTO` / :class:`EvaluationRunDTO` /
  :class:`EvaluationResultDTO`（四实体视图）；
- :class:`EvaluationMetricDeltaDTO` / :class:`EvaluationFailsDTO` /
  :class:`EvaluationCompareReportDTO`（回归对比报告，缺失指标为 ``None`` ＝ ``N/A``）。

🔴 命名加 ``Evaluation`` 前缀：与既有 ``dto/run.py`` 的 ``RunDTO`` **零冲突**（同包异构资源）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_evaluation import (
    CompareReport,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    FailsBreakdown,
    MetricDelta,
)

from .base import DTO

__all__ = [
    "EvaluationDatasetDTO",
    "EvaluationCaseDTO",
    "EvaluationRunDTO",
    "EvaluationResultDTO",
    "EvaluationMetricDeltaDTO",
    "EvaluationFailsDTO",
    "EvaluationCompareReportDTO",
]


@dataclass
class EvaluationDatasetDTO(DTO):
    """任务集视图（``DatasetOut``）。"""

    id: str = ""
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    version: int = 1
    parent_dataset_id: str | None = None
    status: str = "DRAFT"
    description: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: EvaluationDataset) -> EvaluationDatasetDTO:
        """由领域实体构造。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            organization_id=entity.organization_id,
            workspace_id=entity.workspace_id,
            name=entity.name,
            version=int(entity.version),
            parent_dataset_id=entity.parent_dataset_id,
            status=entity.status,
            description=entity.description,
            created_by=entity.created_by,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass
class EvaluationCaseDTO(DTO):
    """用例视图（``CaseOut``；亦作导入用例的输入载体）。"""

    id: str = ""
    dataset_id: str = ""
    case_key: str = ""
    input: Any = None
    expected: Any = None
    assertions: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] | None = None
    position: int = 0

    @classmethod
    def from_entity(cls, entity: EvaluationCase) -> EvaluationCaseDTO:
        """由领域实体构造。"""
        return cls(
            id=entity.id,
            dataset_id=entity.dataset_id,
            case_key=entity.case_key,
            input=entity.input,
            expected=entity.expected,
            assertions=list(entity.assertions),
            tags=list(entity.tags) if entity.tags is not None else None,
            position=int(entity.position),
        )


@dataclass
class EvaluationResultDTO(DTO):
    """逐 case 结果视图（``ResultOut``）。"""

    id: str = ""
    evaluation_run_id: str = ""
    case_id: str = ""
    agent_run_id: str | None = None
    status: str = ""
    score: float | None = None
    assertion_results: list[dict[str, Any]] | None = None
    duration_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    cost: float | None = None
    error_type: str | None = None

    @classmethod
    def from_entity(cls, entity: EvaluationResult) -> EvaluationResultDTO:
        """由领域实体构造。"""
        return cls(
            id=entity.id,
            evaluation_run_id=entity.evaluation_run_id,
            case_id=entity.case_id,
            agent_run_id=entity.agent_run_id,
            status=entity.status,
            score=entity.score,
            assertion_results=(
                list(entity.assertion_results) if entity.assertion_results is not None else None
            ),
            duration_ms=entity.duration_ms,
            token_usage=dict(entity.token_usage) if entity.token_usage is not None else None,
            cost=entity.cost,
            error_type=entity.error_type,
        )


@dataclass
class EvaluationRunDTO(DTO):
    """评测视图（``RunOut``；``results`` 为逐 case 分数，供前端展示）。"""

    id: str = ""
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    dataset_id: str = ""
    agent_id: str = ""
    agent_version_id: str = ""
    status: str = "QUEUED"
    idempotency_key: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    results: list[EvaluationResultDTO] = field(default_factory=list)

    @classmethod
    def from_entity(cls, entity: EvaluationRun) -> EvaluationRunDTO:
        """由领域实体构造（``results`` 默认空，由用例按需填充）。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            organization_id=entity.organization_id,
            workspace_id=entity.workspace_id,
            dataset_id=entity.dataset_id,
            agent_id=entity.agent_id,
            agent_version_id=entity.agent_version_id,
            status=entity.status,
            idempotency_key=entity.idempotency_key,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            summary=dict(entity.summary) if entity.summary is not None else None,
            created_by=entity.created_by,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass
class EvaluationMetricDeltaDTO(DTO):
    """单指标对比 ``{a, b, delta}``（缺失为 ``None`` ＝ ``N/A``）。"""

    a: float | None = None
    b: float | None = None
    delta: float | None = None

    @classmethod
    def from_metric(cls, metric: MetricDelta) -> EvaluationMetricDeltaDTO:
        """由领域对比指标构造。"""
        return cls(a=metric.a, b=metric.b, delta=metric.delta)


@dataclass
class EvaluationFailsDTO(DTO):
    """失败 case 分解（按 ``case_key``）。"""

    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)
    both: list[str] = field(default_factory=list)

    @classmethod
    def from_breakdown(cls, fails: FailsBreakdown) -> EvaluationFailsDTO:
        """由领域失败分解构造。"""
        return cls(
            only_a=list(fails.only_a),
            only_b=list(fails.only_b),
            both=list(fails.both),
        )


@dataclass
class EvaluationCompareReportDTO(DTO):
    """回归对比报告（``CompareReport``）。"""

    dataset_id: str = ""
    dataset_version: int = 1
    agent_version_a: str = ""
    agent_version_b: str = ""
    pass_rate: EvaluationMetricDeltaDTO = field(default_factory=EvaluationMetricDeltaDTO)
    mean_score: EvaluationMetricDeltaDTO = field(default_factory=EvaluationMetricDeltaDTO)
    fails: EvaluationFailsDTO = field(default_factory=EvaluationFailsDTO)
    duration_ms: EvaluationMetricDeltaDTO = field(default_factory=EvaluationMetricDeltaDTO)
    token_usage: EvaluationMetricDeltaDTO = field(default_factory=EvaluationMetricDeltaDTO)
    cost: EvaluationMetricDeltaDTO = field(default_factory=EvaluationMetricDeltaDTO)

    @classmethod
    def from_report(cls, report: CompareReport) -> EvaluationCompareReportDTO:
        """由领域对比报告构造。"""
        return cls(
            dataset_id=report.dataset_id,
            dataset_version=int(report.dataset_version),
            agent_version_a=report.agent_version_a,
            agent_version_b=report.agent_version_b,
            pass_rate=EvaluationMetricDeltaDTO.from_metric(report.pass_rate),
            mean_score=EvaluationMetricDeltaDTO.from_metric(report.mean_score),
            fails=EvaluationFailsDTO.from_breakdown(report.fails),
            duration_ms=EvaluationMetricDeltaDTO.from_metric(report.duration_ms),
            token_usage=EvaluationMetricDeltaDTO.from_metric(report.token_usage),
            cost=EvaluationMetricDeltaDTO.from_metric(report.cost),
        )
