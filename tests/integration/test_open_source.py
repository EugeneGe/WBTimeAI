"""开源纪律扫描断言（W8 / T1-37；设计 §3-#16 / 总纲 §13.3）。

开源核心**不得**出现商业版 / 版本分流（edition gate），Feature Flag 亦**不得**用于
「商业版解锁」（仅「开发期开关 / 风险功能灰度 / 未完成模块隐藏」）。断言：

1. **源码无商业分流**：``packages`` / ``apps`` 的业务代码中，``if commercial`` /
   ``edition ==`` / ``IS_COMMERCIAL`` / ``EDITION_GATE`` 等模式**非空即红**；
   **显式排除** ``plugins/**`` 与 tests（设计 §3-#16）；
2. **Feature Flag 非 edition gate**：任一 flag 的 ``purpose`` **不得**为 ``EDITION_GATE``，
   且默认**全开**（不得作为解锁开关）；
3. **关闭任一开关仍可启动**：全部 flag 关闭时应用**仍可启动**（``/health`` 200，
   行为降级而非模块 / 路由缺失，验收 §3-#14）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 扫描根（业务代码）。
SCAN_ROOTS: tuple[Path, ...] = (REPO_ROOT / "packages", REPO_ROOT / "apps")

#: 显式排除的路径片段（设计 §3-#16：``plugins/**`` 与 tests）。
_EXCLUDED_PARTS: frozenset[str] = frozenset(
    {"plugins", "tests", "node_modules", ".venv", "__pycache__"}
)

#: 商业版 / 版本分流模式（保守：命中即视为 edition gate 违规）。
_COMMERCIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bif\s+commercial\b"),
    re.compile(r"\bedition\s*=="),
    re.compile(r"\bIS_COMMERCIAL\b"),
    re.compile(r"\bEDITION_GATE\b"),
    re.compile(r"\bcommercial_edition\b"),
    re.compile(r"\bis_commercial\b"),
)


def _iter_source_files() -> Iterator[Path]:
    """遍历业务代码 ``.py``（显式排除 plugins / tests / 缓存）。"""
    for base in SCAN_ROOTS:
        for path in base.rglob("*.py"):
            if _EXCLUDED_PARTS & set(path.parts):
                continue
            yield path


def test_no_commercial_edition_gating_in_source() -> None:
    """业务代码无商业版 / 版本分流（排除 ``plugins/**`` 与 tests）。"""
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _COMMERCIAL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)} ~ /{pattern.pattern}/")
    assert not offenders, "检测到开源核心中的商业分流（edition gate）：\n" + "\n".join(offenders)


def test_plugin_and_test_exclusions_are_not_vacuous() -> None:
    """正向断言：扫描根存在（防「扫了空目录」的假绿）。"""
    for base in SCAN_ROOTS:
        assert base.is_dir(), f"扫描根缺失：{base.relative_to(REPO_ROOT)}"
    assert any(_iter_source_files()), "扫描集为空，开源纪律断言可能失效"


def test_feature_flags_are_not_edition_gates() -> None:
    """Feature Flag 不得为 edition gate；默认全开（非商业版解锁开关）。"""
    from astra_config import FEATURE_FLAGS

    assert FEATURE_FLAGS, "Feature Flag 注册表为空"
    for name, definition in FEATURE_FLAGS.items():
        purpose = getattr(definition, "purpose", None)
        assert purpose != "EDITION_GATE", f"flag {name} 的 purpose 不得为 EDITION_GATE"
        # 默认全开：flag 仅作行为开关，不作「未购买则关闭」的解锁门。
        assert definition.default is True, f"flag {name} 默认须为 True（非解锁开关）"


def test_disabling_all_flags_still_starts_up(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全部 Feature Flag 关闭 → 应用**仍可启动**（``/health`` 200）。"""
    import json

    from astra_config import feature_flag_names
    from astra_config.loader import reset_settings_cache

    disabled = {name: False for name in feature_flag_names()}
    monkeypatch.setenv("ASTRA_FEATURE_FLAGS", json.dumps(disabled))
    reset_settings_cache()

    from astra_api.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as test_client:
        response = test_client.get("/health")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "ok"
