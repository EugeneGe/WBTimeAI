"""``astra_evaluation`` 组合工厂（供**组合根**装配；W9 / T2-45）。

- :class:`EvaluationRepositories`：四仓储集合（组合根装配产物）；
- :func:`build_evaluation_repositories`：装配 SQL 仓储（能力包显式 ORM 落点）。

🔴 本模块为**组合工厂**（``factory.py`` 是能力包显式允许的 ORM 落点）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from .repositories import (
    SqlEvaluationCaseRepository,
    SqlEvaluationDatasetRepository,
    SqlEvaluationResultRepository,
    SqlEvaluationRunRepository,
)

__all__ = ["EvaluationRepositories", "build_evaluation_repositories"]


@dataclass
class EvaluationRepositories:
    """Evaluation 四仓储集合（组合根装配产物）。

    Attributes:
        datasets: ``evaluation_dataset`` 仓储。
        cases: ``evaluation_case`` 仓储。
        runs: ``evaluation_run`` 仓储。
        results: ``evaluation_result`` 仓储。
    """

    datasets: SqlEvaluationDatasetRepository
    cases: SqlEvaluationCaseRepository
    runs: SqlEvaluationRunRepository
    results: SqlEvaluationResultRepository


def build_evaluation_repositories(
    session_factory: sessionmaker[Session],
) -> EvaluationRepositories:
    """装配 Evaluation 四 SQL 仓储（共享同一 ``session_factory``；单例安全）。"""
    return EvaluationRepositories(
        datasets=SqlEvaluationDatasetRepository(session_factory),
        cases=SqlEvaluationCaseRepository(session_factory),
        runs=SqlEvaluationRunRepository(session_factory),
        results=SqlEvaluationResultRepository(session_factory),
    )
