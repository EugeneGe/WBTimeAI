"""回归对比报告（设计 §2.13.2 / W9 裁定 §5.5，**冻结**）。

同 ``dataset_version`` 下对比两个明确 ``agent_version``（A＝baseline，B＝candidate）：

- 通过率、平均分、失败 case（仅 A 失败 / 仅 B 失败 / 两者失败）、平均耗时、平均 Token、平均成本；
- 每项指标 = ``{a, b, delta}``（``delta = b - a``）；
- 🔴 **缺失指标显示 ``N/A``（``None``），不得视为 0**；``delta`` 在任一测为空时亦为 ``None``；
- **不自动改 Agent 配置、不阻断运行时请求**。

🔴 本模块**零 Web / ORM**。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

from .domain import (
    RESULT_STATUS_SUCCESS,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)

__all__ = [
    "MetricDelta",
    "FailsBreakdown",
    "CompareReport",
    "compare_runs",
]


@dataclass
class MetricDelta:
    """单指标对比 ``{a, b, delta}``（缺失为 ``None`` ＝ ``N/A``）。"""

    a: float | None = None
    b: float | None = None
    delta: float | None = None

    @classmethod
    def of(cls, a: float | None, b: float | None) -> MetricDelta:
        """由两侧值构造（任一为空 → ``delta`` 为 ``None``）。"""
        delta = (b - a) if (a is not None and b is not None) else None
        return cls(a=a, b=b, delta=delta)


@dataclass
class FailsBreakdown:
    """失败 case 分解（按 ``case_key``）。"""

    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)
    both: list[str] = field(default_factory=list)


@dataclass
class CompareReport:
    """回归对比报告（§5.5）。"""

    dataset_id: str = ""
    dataset_version: int = 1
    agent_version_a: str = ""
    agent_version_b: str = ""
    pass_rate: MetricDelta = field(default_factory=MetricDelta)
    mean_score: MetricDelta = field(default_factory=MetricDelta)
    fails: FailsBreakdown = field(default_factory=FailsBreakdown)
    duration_ms: MetricDelta = field(default_factory=MetricDelta)
    token_usage: MetricDelta = field(default_factory=MetricDelta)
    cost: MetricDelta = field(default_factory=MetricDelta)


def _token_total(token_usage: dict[str, Any] | None) -> float | None:
    """把 ``token_usage`` JSON 归一为数值总量（无数值 → ``None``）。"""
    if not token_usage:
        return None
    total = 0.0
    found = False
    for value in token_usage.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += float(value)
            found = True
    return total if found else None


def _mean(values: Sequence[float]) -> float | None:
    """均值（空序列 → ``None``）。"""
    return (sum(values) / len(values)) if values else None


def _metric_for(
    results: Sequence[EvaluationResult],
    extractor: Any,
) -> float | None:
    """由一组结果计算某指标的均值（无数据 → ``None``）。"""
    values: list[float] = []
    for result in results:
        value = extractor(result)
        if value is not None:
            values.append(float(value))
    return _mean(values)


def compare_runs(
    *,
    dataset: EvaluationDataset,
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    baseline_results: Sequence[EvaluationResult],
    candidate_results: Sequence[EvaluationResult],
    cases: Sequence[EvaluationCase],
) -> CompareReport:
    """构造回归对比报告（A＝baseline，B＝candidate；同 ``dataset_version``）。

    Args:
        dataset: 比对所用任务集（提供 ``version``）。
        baseline: 基线评测（A）。
        candidate: 候选评测（B）。
        baseline_results / candidate_results: 两侧逐 case 结果。
        cases: 任务集用例（提供 ``case_key`` 与整体分母）。

    Returns:
        :class:`CompareReport`。

    Raises:
        DomainError: 两评测不属于同一任务集（``VALIDATION_ERROR``）。
    """
    if baseline.dataset_id != candidate.dataset_id:
        raise DomainError(
            "两次 Evaluation Run 不属于同一任务集，无法对比",
            code=ErrorCode.VALIDATION_ERROR,
            data={
                "baseline_dataset_id": baseline.dataset_id,
                "candidate_dataset_id": candidate.dataset_id,
            },
        )

    baseline_map = {result.case_id: result for result in baseline_results}
    candidate_map = {result.case_id: result for result in candidate_results}

    def _is_failed(mapping: dict[str, EvaluationResult], case_id: str) -> bool:
        result = mapping.get(case_id)
        return result is None or result.status != RESULT_STATUS_SUCCESS

    only_a: list[str] = []
    only_b: list[str] = []
    both: list[str] = []
    for case in cases:
        failed_a = _is_failed(baseline_map, case.id)
        failed_b = _is_failed(candidate_map, case.id)
        if failed_a and failed_b:
            both.append(case.case_key)
        elif failed_a:
            only_a.append(case.case_key)
        elif failed_b:
            only_b.append(case.case_key)

    total = len(cases)
    pass_rate_a = (
        sum(1 for result in baseline_results if result.status == RESULT_STATUS_SUCCESS) / total
        if total
        else None
    )
    pass_rate_b = (
        sum(1 for result in candidate_results if result.status == RESULT_STATUS_SUCCESS) / total
        if total
        else None
    )

    return CompareReport(
        dataset_id=dataset.id,
        dataset_version=int(dataset.version),
        agent_version_a=baseline.agent_version_id,
        agent_version_b=candidate.agent_version_id,
        pass_rate=MetricDelta.of(pass_rate_a, pass_rate_b),
        mean_score=MetricDelta.of(
            _metric_for(baseline_results, lambda r: r.score),
            _metric_for(candidate_results, lambda r: r.score),
        ),
        fails=FailsBreakdown(only_a=only_a, only_b=only_b, both=both),
        duration_ms=MetricDelta.of(
            _metric_for(baseline_results, lambda r: r.duration_ms),
            _metric_for(candidate_results, lambda r: r.duration_ms),
        ),
        token_usage=MetricDelta.of(
            _metric_for(baseline_results, lambda r: _token_total(r.token_usage)),
            _metric_for(candidate_results, lambda r: _token_total(r.token_usage)),
        ),
        cost=MetricDelta.of(
            _metric_for(baseline_results, lambda r: r.cost),
            _metric_for(candidate_results, lambda r: r.cost),
        ),
    )
