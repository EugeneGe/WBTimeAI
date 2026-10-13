"""manual 验收证据归档校验单测（V0.4.1 · J-2）。

覆盖：
1. **正常**：声称通过 + 证据文件存在且非空 → 无违规（退出码 0）；
2. **空槽**：「每槽必填」表证据列空 + 含结论框 → ``empty_slot``；
3. **缺文件**：声称通过但引用不存在 → ``reference_missing``；
4. **0 字节**：引用存在但为空文件 → ``reference_empty``；
5. **目录缺失**：默认显式跳过（退出码 0）；``--require-material`` → 退出码 2。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_manual_evidence.py"

_MANUAL_SUBPATH = ("设计", "验收证据", "manual-checklists")


def _load_script() -> ModuleType:
    """把 ``scripts/check_manual_evidence.py`` 作为独立模块加载（非包导入）。"""
    assert SCRIPT_PATH.is_file(), f"证据校验脚本缺失：{SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("check_manual_evidence_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_root(tmp_path: Path) -> Path:
    """构造 docs 仓布局根 ``<tmp>/设计/验收证据/manual-checklists`` 并返回根。"""
    manual = tmp_path.joinpath(*_MANUAL_SUBPATH)
    manual.mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_checklist(root: Path, text: str, name: str = "demo.md") -> Path:
    """写入一个 checklist 文件。"""
    target = root.joinpath(*_MANUAL_SUBPATH) / name
    target.write_text(text, encoding="utf-8")
    return target


# -- 1. 正常（证据存在且非空 → 通过） ---------------------------------------


def test_passes_when_evidence_present(tmp_path: Path) -> None:
    module = _load_script()
    root = _make_root(tmp_path)
    evidence = root.joinpath(*_MANUAL_SUBPATH) / "evidence" / "e1.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("脱敏证据摘要（非空）", encoding="utf-8")
    _write_checklist(
        root,
        "# demo\n"
        "\n"
        "| 槽 | 证据（脱敏） | 结论 |\n"
        "|---|---|---|\n"
        "| R1 | `evidence/e1.txt` | ☑ 通过 |\n",
    )

    findings, manual_dir = module.scan(root)
    assert manual_dir is not None
    assert findings == [], f"证据存在且非空时不应违规：{findings}"
    assert module.main(["--root", str(root)]) == 0


def test_passes_for_inline_evidence(tmp_path: Path) -> None:
    """证据为**行内摘要**（无文件引用）且非空 → 通过。"""
    module = _load_script()
    root = _make_root(tmp_path)
    _write_checklist(
        root,
        "| 项 | 值 |\n" "|---|---|\n" "| 证据 | `[chat] OK content_len=4`（✅ 全绿） |\n",
    )
    findings, _ = module.scan(root)
    assert findings == [], f"行内证据不应违规：{findings}"


# -- 2. 空槽（证据列空 + 结论框） -------------------------------------------


def test_flags_empty_slot(tmp_path: Path) -> None:
    module = _load_script()
    root = _make_root(tmp_path)
    _write_checklist(
        root,
        "| 槽 | 真实对象 | 执行人 | 日期 | 证据（脱敏） | 结论 |\n"
        "|---|---|---|---|---|---|\n"
        "| R1 | 真实 MCP | | | | ☐ 通过 / ☐ 失败 |\n",
    )
    findings, _ = module.scan(root)
    assert any(item.rule == "manual_evidence.empty_slot" for item in findings), findings
    assert module.main(["--root", str(root)]) == 1


def test_empty_slot_disclosed_is_not_violation(tmp_path: Path) -> None:
    """显式「未留证」披露 → 不按违规计（已披露状态）。"""
    module = _load_script()
    root = _make_root(tmp_path)
    _write_checklist(
        root,
        "| 槽 | 真实对象 | 执行人 | 日期 | 证据（脱敏） | 结论 |\n"
        "|---|---|---|---|---|---|\n"
        "| R1 | 真实 MCP | | | 未留证（原执行未归档证据） | ☐ 通过 / ☐ 失败 |\n",
    )
    findings, _ = module.scan(root)
    assert findings == [], f"显式未留证不应判违规：{findings}"


# -- 3. 缺文件 ---------------------------------------------------------------


def test_flags_missing_reference(tmp_path: Path) -> None:
    module = _load_script()
    root = _make_root(tmp_path)
    _write_checklist(
        root,
        "| 槽 | 证据（脱敏） | 结论 |\n"
        "|---|---|---|\n"
        "| R1 | `evidence/does-not-exist.json` | ✅ 通过 |\n",
    )
    findings, _ = module.scan(root)
    assert any(item.rule == "manual_evidence.reference_missing" for item in findings), findings
    assert module.main(["--root", str(root)]) == 1


# -- 4. 0 字节 ---------------------------------------------------------------


def test_flags_empty_file(tmp_path: Path) -> None:
    module = _load_script()
    root = _make_root(tmp_path)
    evidence = root.joinpath(*_MANUAL_SUBPATH) / "evidence" / "empty.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("", encoding="utf-8")  # 0 字节
    _write_checklist(
        root,
        "| 槽 | 证据（脱敏） | 结论 |\n"
        "|---|---|---|\n"
        "| R1 | `evidence/empty.txt` | ✅ 通过 |\n",
    )
    findings, _ = module.scan(root)
    assert any(item.rule == "manual_evidence.reference_empty" for item in findings), findings


# -- 5. 目录缺失 -------------------------------------------------------------


def test_missing_material_semantics(tmp_path: Path) -> None:
    module = _load_script()
    empty = tmp_path / "empty-root"
    empty.mkdir()

    findings, manual_dir = module.scan(empty)
    assert findings == []
    assert manual_dir is None

    # 默认：显式提示 + 明示跳过（退出码 0，**不** `|| true`）。
    assert module.main(["--root", str(empty)]) == 0
    # 强制：素材缺失即退出码 2（可解释语义）。
    assert module.main(["--root", str(empty), "--require-material"]) == 2


# -- 6. 仓库自检（docs 存在时） ---------------------------------------------


def test_current_docs_are_clean_if_present() -> None:
    """若父仓挂载了 docs 素材，则当前 manual-checklists 必须无违规（防回归）。"""
    module = _load_script()
    if module._locate_manual_dir(REPO_ROOT) is None:
        import pytest

        pytest.skip("docs 素材未挂载（独立仓）")
    findings, manual_dir = module.scan(REPO_ROOT)
    assert manual_dir is not None
    assert findings == [], "当前 manual-checklists 存在违规：\n" + "\n".join(
        f"{item.file}:{item.line} [{item.rule}] {item.message}" for item in findings
    )
