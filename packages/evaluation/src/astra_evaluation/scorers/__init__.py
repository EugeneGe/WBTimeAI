"""``astra_evaluation`` scorer 注册（W9 裁定 R6 / §5.4）。

首批**确定性** scorer（仅 deterministic；LLM Judge 不属本阶段）：
:data:`~astra_evaluation.scorers.deterministic.SCORER_EXACT_MATCH` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_JSON_SCHEMA` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_FIELD_ASSERT` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_CONTAINS` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_NOT_CONTAINS` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_NUMERIC_RANGE` /
:data:`~astra_evaluation.scorers.deterministic.SCORER_TOOL_CALL_SEQUENCE`。
"""

from __future__ import annotations

from .deterministic import (
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
    "SCORER_EXACT_MATCH",
    "SCORER_JSON_SCHEMA",
    "SCORER_FIELD_ASSERT",
    "SCORER_CONTAINS",
    "SCORER_NOT_CONTAINS",
    "SCORER_NUMERIC_RANGE",
    "SCORER_TOOL_CALL_SEQUENCE",
    "KNOWN_SCORERS",
    "CaseScore",
    "validate_assertions",
    "score_case",
]
