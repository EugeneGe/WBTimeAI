"""环境就绪断言共享帮助（V0.4.1 · J-3；设计 §13.3 防假绿 / 总纲 §13.3）。

统一 ``ASTRA_TEST_REQUIRE_<CAPABILITY>`` 语义：

- **未设开关** → 保持既有 **skip / 不收集** 语义（**零行为回归**）；
- **设开关（``=1``）+ 探针失败** → **fail-fast**（``pytest.fail``，**非** skip）——宣称某权威面
  验收时，环境探针失败即失败，**不得在未就绪环境下销账**。

**纯标准库**（仅 ``os`` + ``pytest``）；供 ``tests/conftest.py`` /
``tests/integration/conftest.py`` / ``tests/contracts/*`` 等复用，收敛散落的 ``require_*``
开关读取，避免语义漂移。
"""

from __future__ import annotations

import os
from typing import Literal

import pytest

__all__ = ["EnvOutcome", "decide", "ensure_available", "require_flag", "should_collect"]

#: 门控决策结果。
EnvOutcome = Literal["available", "skip", "fail"]


def _env_name(capability: str) -> str:
    """能力名 → 强开关环境变量名（``PG`` → ``ASTRA_TEST_REQUIRE_PG``）。"""
    return f"ASTRA_TEST_REQUIRE_{capability.upper()}"


def require_flag(capability: str) -> bool:
    """读取强开关 ``ASTRA_TEST_REQUIRE_<CAPABILITY>``（**仅** ``"1"`` 视为开启）。"""
    return os.environ.get(_env_name(capability)) == "1"


def decide(capability: str, available: bool) -> EnvOutcome:
    """门控决策（**纯函数**，便于矩阵单测）。

    Args:
        capability: 能力名（如 ``DOCKER`` / ``PG``）。
        available: 探针结果（环境是否就绪）。

    Returns:
        - ``"available"``：探针可用；
        - ``"fail"``：不可用 **且** 开关开启（应 fail-fast）；
        - ``"skip"``：不可用 **且** 未设开关（保持既有 skip 语义）。
    """
    if available:
        return "available"
    return "fail" if require_flag(capability) else "skip"


def should_collect(capability: str, *, probe_available: bool) -> bool:
    """是否**收集**受门控用例：探针可用 **或** 强开关开启（否则不收集，默认零噪声）。"""
    return probe_available or require_flag(capability)


def ensure_available(capability: str, *, available: bool, reason: str) -> None:
    """应用门控语义（就绪返回 / 开关开即 fail / 未设即 skip）。

    Args:
        capability: 能力名（如 ``DOCKER`` / ``PG``）。
        available: 探针结果。
        reason: 不可用原因（进 skip / fail 文案）。

    Raises:
        pytest.fail.Exception: 不可用且开关开启（防假绿，**不**静默 skip）。
        pytest.skip.Exception: 不可用且未设开关（保持既有语义）。
    """
    outcome = decide(capability, available)
    if outcome == "available":
        return
    if outcome == "fail":
        pytest.fail(f"{_env_name(capability)}=1 但{reason}（防假绿，不得静默 skip）")
    pytest.skip(reason)
