"""环境就绪断言单测（V0.4.1 · J-3；设计 §13.3 防假绿）。

覆盖开关矩阵（**开 / 关 × 可达 / 不可达**）——单测自身在任何环境可跑（monkeypatch 环境变量 +
显式构造「不可达」探针，**不**依赖真实 Docker / PG）。

语义（对齐裁定 §4 J-3）：

- 未设开关 → 不可达保持 **skip**（零回归）；可达 → 放行；
- 设开关（``=1``）+ 不可达 → **fail**（非 skip，防假绿）。
"""

from __future__ import annotations

import pytest

from tests._env_readiness import decide, ensure_available, require_flag, should_collect

# -- decide 矩阵（纯函数） ---------------------------------------------------


@pytest.mark.parametrize(
    ("env_value", "available", "expected"),
    [
        (None, True, "available"),
        (None, False, "skip"),
        ("1", True, "available"),
        ("1", False, "fail"),
        ("0", False, "skip"),  # 仅 "1" 视为开启
    ],
)
def test_decide_matrix(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str | None,
    available: bool,
    expected: str,
) -> None:
    if env_value is None:
        monkeypatch.delenv("ASTRA_TEST_REQUIRE_PG", raising=False)
    else:
        monkeypatch.setenv("ASTRA_TEST_REQUIRE_PG", env_value)
    assert decide("PG", available) == expected


def test_require_flag_only_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅 ``"1"`` 视为开启（``""`` / ``"0"`` / ``"true"`` 均否）。"""
    for value in ("", "0", "true", "yes"):
        monkeypatch.setenv("ASTRA_TEST_REQUIRE_DOCKER", value)
        assert require_flag("DOCKER") is False
    monkeypatch.setenv("ASTRA_TEST_REQUIRE_DOCKER", "1")
    assert require_flag("DOCKER") is True
    monkeypatch.delenv("ASTRA_TEST_REQUIRE_DOCKER", raising=False)
    assert require_flag("DOCKER") is False


# -- should_collect（收集门控） ----------------------------------------------


@pytest.mark.parametrize(
    ("env_value", "probe_available", "expected"),
    [
        (None, True, True),
        (None, False, False),
        ("1", False, True),
        ("1", True, True),
    ],
)
def test_should_collect_matrix(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str | None,
    probe_available: bool,
    expected: bool,
) -> None:
    if env_value is None:
        monkeypatch.delenv("ASTRA_TEST_REQUIRE_PG", raising=False)
    else:
        monkeypatch.setenv("ASTRA_TEST_REQUIRE_PG", env_value)
    assert should_collect("PG", probe_available=probe_available) is expected


# -- ensure_available（应用语义，抛 skip / fail） ----------------------------


def test_ensure_available_fails_when_required_but_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开关开 + 探针失败 → fail（非 skip）。"""
    monkeypatch.setenv("ASTRA_TEST_REQUIRE_PG", "1")
    with pytest.raises(pytest.fail.Exception):
        ensure_available("PG", available=False, reason="PG 不可达")


def test_ensure_available_skips_when_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """未设开关 + 探针失败 → skip（零回归）。"""
    monkeypatch.delenv("ASTRA_TEST_REQUIRE_PG", raising=False)
    with pytest.raises(pytest.skip.Exception):
        ensure_available("PG", available=False, reason="PG 不可达")


def test_ensure_available_noop_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """探针可用 → 放行（无论开关）。"""
    monkeypatch.delenv("ASTRA_TEST_REQUIRE_PG", raising=False)
    ensure_available("PG", available=True, reason="不应触发")
    monkeypatch.setenv("ASTRA_TEST_REQUIRE_PG", "1")
    ensure_available("PG", available=True, reason="不应触发")
