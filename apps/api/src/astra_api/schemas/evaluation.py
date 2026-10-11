"""Evaluation schema（任务集 / 用例 / 评测 / 对比视图；W9 / T2-47；设计 §2.13.2 / 裁定 R6）。

面向 ``/api/v1/evaluation`` 的请求 / 响应模型。**统一响应壳**
``{code, data, message, request_id}`` 由既有中间件注入——此处仅定义 ``data`` 内的模型。

- 请求：:class:`CreateDatasetRequest` / :class:`ImportCasesRequest` / :class:`StartRunRequest`；
- 响应：:class:`DatasetOut` / :class:`CaseOut` / :class:`RunOut`（含逐 case :class:`ResultOut`）
  / :class:`CompareReport`（回归对比；缺失指标 ``N/A``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateDatasetRequest",
    "ImportCasesRequest",
    "StartRunRequest",
    "DatasetOut",
    "CaseIn",
    "CaseOut",
    "ResultOut",
    "RunOut",
    "MetricDeltaOut",
    "FailsOut",
    "CompareReport",
]


# -- 请求 --------------------------------------------------------------------


class CreateDatasetRequest(BaseModel):
    """创建任务集请求。"""

    name: str = Field(..., min_length=1, description="任务集名称")
    description: str | None = Field(default=None, description="描述（可空）")
    workspace_id: str | None = Field(default=None, description="归属工作区（可空）")
    organization_id: str | None = Field(default=None, description="组织归属（可空；A-7）")


class CaseIn(BaseModel):
    """导入用例条目（``input`` / ``expected`` **不得含凭证**）。"""

    case_key: str = Field(..., min_length=1, description="用例键（同任务集内唯一）")
    input: Any = Field(default=None, description="输入（任意 JSON）")
    expected: Any = Field(default=None, description="期望值（可空）")
    assertions: list[dict[str, Any]] = Field(
        default_factory=list, description="断言配置 list[{scorer, weight>0, params}]"
    )
    tags: list[str] | None = Field(default=None, description="标签（可空）")
    position: int = Field(default=0, description="排序位次（默认 0）")


class ImportCasesRequest(BaseModel):
    """导入用例请求（批量）。"""

    cases: list[CaseIn] = Field(default_factory=list, description="待导入用例列表")


class StartRunRequest(BaseModel):
    """启动批量评测请求（固定 dataset / agent 版本）。"""

    dataset_id: str = Field(..., min_length=1, description="目标任务集标识（须 PUBLISHED）")
    agent_id: str = Field(..., min_length=1, description="目标 Agent 标识")
    agent_version_id: str = Field(..., min_length=1, description="目标 Agent 版本标识（可重放）")
    idempotency_key: str | None = Field(default=None, description="幂等键（可空 → 确定性生成）")
    workspace_id: str | None = Field(default=None, description="归属工作区（可空）")
    organization_id: str | None = Field(default=None, description="组织归属（可空）")


# -- 响应 --------------------------------------------------------------------


class DatasetOut(BaseModel):
    """任务集视图。"""

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


class CaseOut(BaseModel):
    """用例视图。"""

    id: str = ""
    dataset_id: str = ""
    case_key: str = ""
    input: Any = None
    expected: Any = None
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] | None = None
    position: int = 0


class ResultOut(BaseModel):
    """逐 case 结果视图（``score`` 为 ``None`` ＝ ``N/A``，**不视为 0**）。"""

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


class RunOut(BaseModel):
    """评测视图（``results`` 为逐 case 分数）。"""

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
    results: list[ResultOut] = Field(default_factory=list)


class MetricDeltaOut(BaseModel):
    """单指标对比 ``{a, b, delta}``（缺失为 ``None`` ＝ ``N/A``）。"""

    a: float | None = None
    b: float | None = None
    delta: float | None = None


class FailsOut(BaseModel):
    """失败 case 分解（按 ``case_key``）。"""

    only_a: list[str] = Field(default_factory=list)
    only_b: list[str] = Field(default_factory=list)
    both: list[str] = Field(default_factory=list)


class CompareReport(BaseModel):
    """回归对比报告（缺失指标 ``N/A``；``delta`` 任一测为空时亦为 ``None``）。"""

    dataset_id: str = ""
    dataset_version: int = 1
    agent_version_a: str = ""
    agent_version_b: str = ""
    pass_rate: MetricDeltaOut = Field(default_factory=MetricDeltaOut)
    mean_score: MetricDeltaOut = Field(default_factory=MetricDeltaOut)
    fails: FailsOut = Field(default_factory=FailsOut)
    duration_ms: MetricDeltaOut = Field(default_factory=MetricDeltaOut)
    token_usage: MetricDeltaOut = Field(default_factory=MetricDeltaOut)
    cost: MetricDeltaOut = Field(default_factory=MetricDeltaOut)
