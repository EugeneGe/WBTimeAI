"""D4 守卫：``ASTRA_MODE`` 分流**仅**允许出现在 ``providers.py``。

扫描 ``packages/config/src/astra_config/*.py``，断言 ``mode ==`` / ``if mode`` 等
环境分流模式**只**出现在 ``providers.py``。T0-21 新增的 ``feature_flags.py`` 为**纯逻辑**，
不得包含任何 mode 判断（否则会破坏决策 D4 的唯一分流点）。

W8 / T1-37 **加固 + 扩展**（零放宽）：D4 原文为「业务代码无 ``if mode ==``，唯一豁免在
``providers.py``」——原实现仅扫 ``packages/config``。本节**新增**一条**全业务代码**扫描
（``packages/*/src`` + ``apps/*/src``），以**精确**的「``mode`` 与 ``server``/``local``
字面量比较」模式识别 ASTRA_MODE 分流，豁免仍**仅** ``providers.py``；不放松任何既有断言。

附加断言（T1-01 / P0-03）：``server`` 模式下 ``storage`` 占位标注为 ``Team``
（不再是 ``Phase 1``）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SRC = REPO_ROOT / "packages" / "config" / "src" / "astra_config"

#: 匹配 mode 环境分流：`mode == …` / `mode != …` / `if mode` / `if xxx.mode`。
_MODE_BRANCH_RE = re.compile(r"\bmode\s*(?:==|!=)|\bif\s+mode\b|\bif\s+[\w.]*\.mode\b")

#: 唯一允许出现 mode 分流的模块。
_ALLOWED_MODULE = "providers.py"

#: **精确**的 ASTRA_MODE 分流模式：``mode`` 与 ``"server"`` / ``"local"`` 字面量比较。
#: 不误命中 ``run.run_mode == RUN_MODE_INLINE``（RHS 为常量）或 ``if mode is not None``。
_MODE_LITERAL_RE = re.compile(r"\bmode\s*(?:==|!=)\s*[\"'](?:server|local)[\"']")

#: 全业务代码扫描根（``<root>/<pkg>/src`` 下的 ``.py``）。
_BIZ_SRC_GLOBS: tuple[str, ...] = ("packages/*/src", "apps/*/src")


def _scan() -> dict[str, list[str]]:
    """返回 ``{文件名: [命中行…]}``（仅含存在命中的文件）。"""
    offenders: dict[str, list[str]] = {}
    for path in sorted(CONFIG_SRC.glob("*.py")):
        hits = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if _MODE_BRANCH_RE.search(line)
        ]
        if hits:
            offenders[path.name] = hits
    return offenders


def test_mode_branch_only_in_providers() -> None:
    """mode 分流只允许出现在 ``providers.py``（D4）。"""
    offenders = _scan()
    unexpected = {name: hits for name, hits in offenders.items() if name != _ALLOWED_MODULE}
    assert not unexpected, f"检测到 providers.py 之外的 mode 分流：{unexpected}"


def test_providers_is_the_detected_branch_point() -> None:
    """反向校验：守卫模式确能命中 ``providers.py``（确保断言有效）。"""
    offenders = _scan()
    assert _ALLOWED_MODULE in offenders, "providers.py 未命中 mode 分流，守卫模式可能失效"


def test_unsupported_storage_phase_is_team() -> None:
    """``server`` 模式 ``storage`` 占位标注为 ``Team``（P0-03 / T01 级必闭合）。

    直接调用 ``providers.py`` 的工厂，断言标注不再是 ``Phase 1``。
    """
    from astra_config.providers import _build_unsupported_storage

    placeholder = _build_unsupported_storage(None)  # type: ignore[arg-type]
    assert placeholder.available_in == "Team"
    assert placeholder.available_in != "Phase 1"


# -- W8 / T1-37：全业务代码 D4 加固（仅新增 / 收紧，零放宽） -------------------


def _iter_business_source_files() -> Iterator[Path]:
    """遍历**全业务代码** ``.py``（``packages/*/src`` + ``apps/*/src``）。"""
    for glob in _BIZ_SRC_GLOBS:
        for base in sorted(REPO_ROOT.glob(glob)):
            for path in base.rglob("*.py"):
                if "__pycache__" in path.parts or ".venv" in path.parts:
                    continue
                yield path


def _scan_mode_literal() -> dict[str, list[str]]:
    """返回 ``{相对路径: [命中行…]}``——仅统计**精确** ASTRA_MODE 字面量分流。"""
    offenders: dict[str, list[str]] = {}
    for path in _iter_business_source_files():
        hits = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if _MODE_LITERAL_RE.search(line)
        ]
        if hits:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = hits
    return offenders


def test_mode_literal_branch_only_in_providers_across_all_business_code() -> None:
    """全业务代码中，ASTRA_MODE 字面量分流**仅**允许出现在 ``providers.py``（D4 加固）。"""
    offenders = _scan_mode_literal()
    unexpected = {
        path: hits for path, hits in offenders.items() if Path(path).name != _ALLOWED_MODULE
    }
    assert not unexpected, f"检测到 providers.py 之外的 ASTRA_MODE 分流：{unexpected}"


def test_mode_literal_guard_hits_providers_across_all_business_code() -> None:
    """反向校验：加固后的模式在全业务代码中确能命中 ``providers.py``（防假绿）。"""
    offenders = _scan_mode_literal()
    assert any(
        Path(path).name == _ALLOWED_MODULE for path in offenders
    ), "全业务代码扫描未命中 providers.py，加固守卫可能失效"


def test_mode_literal_guard_pattern_precision() -> None:
    """精确性自证：命中 ASTRA_MODE 分流，**不**误命中 ``run_mode`` / ``is not None``。"""
    assert _MODE_LITERAL_RE.search('if mode == "server":')
    assert _MODE_LITERAL_RE.search("elif mode != 'local':")
    assert not _MODE_LITERAL_RE.search("if run.run_mode == RUN_MODE_INLINE:")
    assert not _MODE_LITERAL_RE.search("if mode is not None:")
    # 正向断言扫描集非空。
    assert any(_iter_business_source_files()), "全业务代码扫描集为空"


@pytest.mark.parametrize("package", ["config", "model", "event"])
def test_no_mode_literal_branch_outside_providers_scope(package: str) -> None:
    """抽查若干包：除 ``config/providers.py`` 外无 mode 字面量分流。"""
    base = REPO_ROOT / "packages" / package / "src"
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in base.rglob("*.py")
        if path.name != _ALLOWED_MODULE and _MODE_LITERAL_RE.search(path.read_text("utf-8"))
    ]
    assert not offenders, f"packages/{package} 出现 ASTRA_MODE 字面量分流：{offenders}"
