"""首批**确定性** scorer（设计 §2.13.2 / W9 裁定 R6 / §5.4，**冻结**）。

五类 scorer（**仅确定性；不做 LLM Judge**）：

1. :data:`SCORER_EXACT_MATCH`：输出与 ``expected`` 精确相等（规范化后）→ 1/0；
2. :data:`SCORER_JSON_SCHEMA` / :data:`SCORER_FIELD_ASSERT`：输出可解析 JSON 且满足
   schema / 字段断言 → 1/0（``field_assert`` 可分子项比例）；
3. :data:`SCORER_CONTAINS` / :data:`SCORER_NOT_CONTAINS`：输出包含 / 不包含指定子串
   （列表逐项）→ 命中比；
4. :data:`SCORER_NUMERIC_RANGE`：数值落在 ``[min,max]`` 区间 → **二值 1/0**（R6）；
5. :data:`SCORER_TOOL_CALL_SEQUENCE`：``tool_call`` 名称序列匹配期望序列 → 1/0（可 LCS 比例）。

权重归一化：case 分 = ``Σ(weight_i × score_i) / Σ(weight_i)``，**clamp 到 0–1**；
**无断言 → ``score=None``（N/A，不视为 0）**。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core``）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

from ..launcher import ToolCallView

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

SCORER_EXACT_MATCH = "exact_match"
SCORER_JSON_SCHEMA = "json_schema"
SCORER_FIELD_ASSERT = "field_assert"
SCORER_CONTAINS = "contains"
SCORER_NOT_CONTAINS = "not_contains"
SCORER_NUMERIC_RANGE = "numeric_range"
SCORER_TOOL_CALL_SEQUENCE = "tool_call_sequence"

#: 首批确定性 scorer 冻结清单（§5.4）。
KNOWN_SCORERS: tuple[str, ...] = (
    SCORER_EXACT_MATCH,
    SCORER_JSON_SCHEMA,
    SCORER_FIELD_ASSERT,
    SCORER_CONTAINS,
    SCORER_NOT_CONTAINS,
    SCORER_NUMERIC_RANGE,
    SCORER_TOOL_CALL_SEQUENCE,
)

#: ``json_schema`` / ``field_assert`` 支持的 JSON 值类型名。
_JSON_TYPE_NAMES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
    "null": (type(None),),
}


@dataclass
class CaseScore:
    """逐 case 评分结果。

    Attributes:
        score: case 分（0–1；**无断言 → ``None``（``N/A``）**）。
        assertions: 逐断言明细 ``list[{scorer, passed, weight, score, detail}]``。
    """

    score: float | None = None
    assertions: list[dict[str, Any]] = field(default_factory=list)


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造 ``DomainError(VALIDATION_ERROR)``（断言配置非法）。"""
    return DomainError(
        message,
        code=ErrorCode.VALIDATION_ERROR,
        data={"reason": "invalid_assertion", **data},
    )


def validate_assertions(assertions: Any) -> None:
    """校验 ``assertions`` schema（``list[{scorer, weight>0, params: dict}]``，R6）。

    Args:
        assertions: 断言配置（``None`` → 通过）。

    Raises:
        DomainError: 非列表 / 非法 scorer / 非法 weight / 非映射 params（``VALIDATION_ERROR``）。
    """
    if assertions is None:
        return
    if not isinstance(assertions, list):
        raise _validation_error("assertions 须为列表", field="assertions")
    for index, item in enumerate(assertions):
        if not isinstance(item, Mapping):
            raise _validation_error("断言项须为映射", index=index)
        scorer = item.get("scorer")
        if scorer not in KNOWN_SCORERS:
            raise _validation_error(
                "未知 scorer", index=index, scorer=str(scorer), known=list(KNOWN_SCORERS)
            )
        weight = item.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise _validation_error("weight 须为正数", index=index, weight=weight)
        params = item.get("params", {})
        if not isinstance(params, Mapping):
            raise _validation_error("params 须为映射", index=index)


def _normalize_text(value: Any) -> str:
    """把任意值归一化为去首尾空白字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _load_json(value: Any) -> Any:
    """尝试把 ``value`` 解析为 JSON（已是容器 → 原样返回；解析失败 → ``_MISSING``）。"""
    if isinstance(value, (dict, list, tuple)):
        return value
    if not isinstance(value, str):
        return _MISSING
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return _MISSING


class _Missing:
    """JSON 解析失败哨兵。"""


_MISSING = _Missing()


def _score_exact_match(output: Any, expected: Any, params: Mapping[str, Any]) -> tuple[float, bool]:
    """``exact_match``：规范化后精确相等（非字符串 ``expected`` 走结构化比较）。"""
    if isinstance(expected, bool):
        passed = _normalize_text(output).lower() == ("true" if expected else "false")
    elif isinstance(expected, (dict, list, tuple, int, float)):
        parsed = _load_json(output)
        passed = parsed is not _MISSING and parsed == expected
    else:
        left = _normalize_text(output)
        right = _normalize_text(expected)
        if params.get("case_sensitive") is False:
            left, right = left.lower(), right.lower()
        passed = left == right
    return (1.0 if passed else 0.0), passed


def _score_json_schema(output: Any, params: Mapping[str, Any]) -> tuple[float, bool]:
    """``json_schema``：输出可解析 JSON 且满足 ``required`` + 字段类型（1/0）。"""
    parsed = _load_json(output)
    if parsed is _MISSING or not isinstance(parsed, Mapping):
        return 0.0, False
    required = list(params.get("required") or [])
    types = dict(params.get("fields") or params.get("types") or {})
    ok = True
    for name in required:
        if name not in parsed:
            ok = False
            break
    if ok:
        for name, type_name in types.items():
            if name not in parsed:
                ok = False
                break
            expected_types = _JSON_TYPE_NAMES.get(str(type_name))
            if expected_types is None or not isinstance(parsed[name], expected_types):
                ok = False
                break
    return (1.0 if ok else 0.0), ok


def _score_field_assert(output: Any, params: Mapping[str, Any]) -> tuple[float, bool]:
    """``field_assert``：字段值断言（子项比例 = 命中数 / 字段数）。"""
    parsed = _load_json(output)
    fields = dict(params.get("fields") or {})
    if not fields:
        return 0.0, False
    if parsed is _MISSING or not isinstance(parsed, Mapping):
        return 0.0, False
    matched = sum(1 for name, value in fields.items() if parsed.get(name) == value)
    total = len(fields)
    score = matched / total
    return score, matched == total


def _score_contains(output: Any, params: Mapping[str, Any], *, negate: bool) -> tuple[float, bool]:
    """``contains`` / ``not_contains``：子串命中比。"""
    values = list(params.get("values") or [])
    if not values:
        return 0.0, False
    text = _normalize_text(output)
    if negate:
        hits = sum(1 for item in values if str(item) not in text)
    else:
        hits = sum(1 for item in values if str(item) in text)
    score = hits / len(values)
    return score, hits == len(values)


def _score_numeric_range(output: Any, params: Mapping[str, Any]) -> tuple[float, bool]:
    """``numeric_range``：数值落 ``[min,max]``（**二值 1/0**，R6）。"""
    low = params.get("min")
    high = params.get("max")
    value = _coerce_number(output)
    if value is None or not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return 0.0, False
    passed = float(low) <= value <= float(high)
    return (1.0 if passed else 0.0), passed


def _coerce_number(value: Any) -> float | None:
    """把输出值强制转为数值（失败 → ``None``）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _tool_call_names(tool_calls: Sequence[Any] | None) -> list[str]:
    """把工具调用快照归一化为名称序列（支持 ``ToolCallView`` / ``str`` / 映射）。"""
    names: list[str] = []
    for call in tool_calls or []:
        if isinstance(call, ToolCallView):
            names.append(call.name)
        elif isinstance(call, str):
            names.append(call)
        elif isinstance(call, Mapping):
            names.append(str(call.get("name", "")))
        else:  # pragma: no cover - 兜底
            names.append(str(getattr(call, "name", "")))
    return names


def _is_subsequence(expected: Sequence[str], actual: Sequence[str]) -> bool:
    """``expected`` 是否为 ``actual`` 的**有序子序列**。"""
    iterator = iter(actual)
    return all(item in iterator for item in expected)


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    """最长公共子序列长度（经典 DP）。"""
    previous = [0] * (len(right) + 1)
    for item_left in left:
        current = [0] * (len(right) + 1)
        for index, item_right in enumerate(right, start=1):
            if item_left == item_right:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current
    return previous[len(right)]


def _score_tool_call_sequence(
    tool_calls: Sequence[Any] | None, params: Mapping[str, Any]
) -> tuple[float, bool]:
    """``tool_call_sequence``：实际工具名序列匹配期望序列（``subsequence`` / ``exact`` /
    ``lcs``）。"""
    expected = [str(item) for item in (params.get("sequence") or [])]
    actual = _tool_call_names(tool_calls)
    mode = str(params.get("mode", "subsequence"))
    if not expected:
        return 0.0, False
    if mode == "exact":
        passed = actual == expected
        return (1.0 if passed else 0.0), passed
    if mode == "lcs":
        score = _lcs_length(expected, actual) / len(expected)
        return score, score >= 1.0
    passed = _is_subsequence(expected, actual)
    return (1.0 if passed else 0.0), passed


def _evaluate_assertion(
    assertion: Mapping[str, Any],
    *,
    output: Any,
    expected: Any,
    tool_calls: Sequence[Any] | None,
) -> tuple[float, dict[str, Any]]:
    """评估单条断言，返回 ``(score, 明细)``。"""
    scorer = str(assertion["scorer"])
    weight = float(assertion["weight"])
    params = dict(assertion.get("params") or {})
    if scorer == SCORER_EXACT_MATCH:
        score, passed = _score_exact_match(output, expected, params)
    elif scorer == SCORER_JSON_SCHEMA:
        score, passed = _score_json_schema(output, params)
    elif scorer == SCORER_FIELD_ASSERT:
        score, passed = _score_field_assert(output, params)
    elif scorer == SCORER_CONTAINS:
        score, passed = _score_contains(output, params, negate=False)
    elif scorer == SCORER_NOT_CONTAINS:
        score, passed = _score_contains(output, params, negate=True)
    elif scorer == SCORER_NUMERIC_RANGE:
        score, passed = _score_numeric_range(output, params)
    else:  # SCORER_TOOL_CALL_SEQUENCE
        score, passed = _score_tool_call_sequence(tool_calls, params)
    score = max(0.0, min(1.0, float(score)))
    detail = {"scorer": scorer, "passed": bool(passed), "weight": weight, "score": score}
    return score, detail


def score_case(
    assertions: Any,
    *,
    output: Any,
    expected: Any = None,
    tool_calls: Sequence[Any] | None = None,
) -> CaseScore:
    """对单条用例评分（权重归一 0–1；**无断言 → ``score=None``**）。

    Args:
        assertions: 断言配置 ``list[{scorer, weight, params}]``（``None`` / ``[]`` → N/A）。
        output: 待评输出（agent_run 终态输出文本 / 结构化值）。
        expected: 期望值（供 ``exact_match`` 等）。
        tool_calls: 工具调用快照（供 ``tool_call_sequence``）。

    Returns:
        :class:`CaseScore`（``score`` 0–1 或 ``None``；``assertions`` 明细列表）。

    Raises:
        DomainError: 断言配置非法（``VALIDATION_ERROR``）。
    """
    validate_assertions(assertions)
    if not assertions:
        return CaseScore(score=None, assertions=[])
    total_weight = 0.0
    weighted = 0.0
    details: list[dict[str, Any]] = []
    for assertion in assertions:
        score, detail = _evaluate_assertion(
            assertion, output=output, expected=expected, tool_calls=tool_calls
        )
        weight = float(assertion["weight"])
        total_weight += weight
        weighted += weight * score
        details.append(detail)
    case_score = weighted / total_weight if total_weight > 0 else None
    if case_score is not None:
        case_score = max(0.0, min(1.0, case_score))
    return CaseScore(score=case_score, assertions=details)
