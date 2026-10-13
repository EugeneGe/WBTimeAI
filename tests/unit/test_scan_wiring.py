"""装配可达性扫描单测（V0.4.1 · J-1；施工口径见 ``00-本机轮开工前架构裁定`` §4）。

覆盖（**防「假绿」自我验证**）：

1. **仓库自检**：``scripts/scan_wiring.py`` 对**当前仓库**返回 ``0``（无违规）；
2. **检出能力**：对 ``tmp_path`` 构造的违规样本（注册点无引用 / 孤儿 ``recover_*`` /
   ``Providers`` 漏装配）能逐条检出——样本不被检出即扫描失效（假绿）；
3. **白名单生效**：显式登记的预留符号不被误报；
4. **正向断言**：扫描集非空、白名单机制存在、脚本存在。

与 ``tests/integration/test_discipline_scan.py``（纪律面）**互补**：本文件为**接线面**单测。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "scan_wiring.py"


def _load_script() -> ModuleType:
    """把 ``scripts/scan_wiring.py`` 作为独立模块加载（非包导入）。

    先登记进 ``sys.modules``——脚本含 ``from __future__ import annotations`` 的 dataclass，
    其 ``__module__`` 解析依赖模块已在 ``sys.modules``（否则 dataclass 装配期报错）。
    """
    assert SCRIPT_PATH.is_file(), f"装配可达性扫描脚本缺失：{SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("scan_wiring_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# -- 1. 仓库自检（当前仓库无违规） -------------------------------------------


def test_scan_wiring_is_clean_on_current_repo() -> None:
    """脚本对**当前仓库**返回 0；``scan`` 无发现项。"""
    module = _load_script()

    findings = module.scan(REPO_ROOT)
    assert findings == [], "当前仓库存在装配接线违规：\n" + "\n".join(
        f"{item.path}:{item.line} [{item.rule}] {item.message}" for item in findings
    )

    assert module.main(["--root", str(REPO_ROOT)]) == 0


def test_scan_is_not_vacuous() -> None:
    """正向断言：扫描集非空、注册点清单非空、白名单机制存在（防「扫了空目录」的假绿）。"""
    module = _load_script()

    assert list(module._iter_py(REPO_ROOT)), "扫描集为空，装配扫描可能失效"
    assert module.REGISTRY_IMPLEMENTATIONS, "注册点清单为空，维度①失效"
    assert module.RESERVED_UNWIRED, "白名单机制缺失（预留符号需显式登记）"

    for rule in (
        module.scan_registry_implementations,
        module.scan_build_providers_slots,
        module.scan_orphan_sweeps,
    ):
        assert callable(rule), f"规则函数缺失：{rule}"


# -- 2. 维度①：注册点 / 实现类无引用 ----------------------------------------


def test_detects_orphan_registry_implementation(tmp_path: Path) -> None:
    """实现类**有定义、全仓无装配引用** → 检出 ``wiring.registry_symbol_unwired``。"""
    module = _load_script()
    orphan = tmp_path / "packages" / "sandbox" / "src" / "astra_sandbox"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "local_process_provider.py").write_text(
        "class LocalProcessSandboxProvider:\n    pass\n", encoding="utf-8"
    )

    findings = module.scan_registry_implementations(tmp_path)
    hits = [
        item
        for item in findings
        if item.rule == "wiring.registry_symbol_unwired"
        and "LocalProcessSandboxProvider" in item.message
    ]
    assert hits, f"未检出无引用的实现类：{[(i.rule, i.message) for i in findings]}"
    assert module.main(["--root", str(tmp_path)]) == 1


def test_wired_registry_implementation_is_not_flagged(tmp_path: Path) -> None:
    """实现类**被非定义模块引用/实例化** → 不误报。"""
    module = _load_script()
    base = tmp_path / "packages" / "sandbox" / "src" / "astra_sandbox"
    base.mkdir(parents=True, exist_ok=True)
    (base / "local_process_provider.py").write_text(
        "class LocalProcessSandboxProvider:\n    pass\n", encoding="utf-8"
    )
    # 另一模块装配它（非定义模块引用 + 实例化）。
    (base / "factory.py").write_text(
        "from .local_process_provider import LocalProcessSandboxProvider\n"
        "def build():\n"
        "    return LocalProcessSandboxProvider()\n",
        encoding="utf-8",
    )

    findings = module.scan_registry_implementations(tmp_path)
    assert not any(
        "LocalProcessSandboxProvider" in item.message for item in findings
    ), "已被装配的实现类不应误报"


# -- 3. 维度②：Providers 槽位覆盖 -------------------------------------------


def _write_mini_providers(root: Path, body: str) -> None:
    """在 ``root`` 下写一个最小 ``astra_config/providers.py`` 样本。"""
    target = root / "packages" / "config" / "src" / "astra_config" / "providers.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_detects_uncovered_and_unknown_slots(tmp_path: Path) -> None:
    """``Providers`` 字段漏装配 / 未知槽键 → 检出（槽位覆盖一致性）。"""
    module = _load_script()
    _write_mini_providers(
        tmp_path,
        "class Providers:\n"
        "    settings: object\n"
        "    database: object | None = None\n"
        "    storage: object | None = None\n"
        "\n"
        "def _build_phase1_slots(settings):\n"
        '    return {"sandbox": None}\n'
        "\n"
        "def build_providers(settings):\n"
        "    phase1_slots = _build_phase1_slots(settings)\n"
        "    return Providers(settings=settings, **phase1_slots)\n",
    )

    findings = module.scan_build_providers_slots(tmp_path)
    rules = {item.rule for item in findings}
    messages = " ".join(item.message for item in findings)
    # ``sandbox`` 不是字段 → 未知槽；``database`` / ``storage`` 未装配 → 漏装配。
    assert "wiring.slot_unknown" in rules, f"未检出未知槽：{sorted(rules)}"
    assert "wiring.slot_uncovered" in rules, f"未检出漏装配：{sorted(rules)}"
    assert "database" in messages and "storage" in messages


def test_build_providers_slots_clean_when_fully_covered(tmp_path: Path) -> None:
    """字段被显式 kwarg + phase 槽全覆盖 → 无发现项。"""
    module = _load_script()
    _write_mini_providers(
        tmp_path,
        "class Providers:\n"
        "    settings: object\n"
        "    database: object | None = None\n"
        "    sandbox: object | None = None\n"
        "\n"
        "def _build_phase1_slots(settings):\n"
        '    return {"sandbox": None}\n'
        "\n"
        "def build_providers(settings):\n"
        "    phase1_slots = _build_phase1_slots(settings)\n"
        "    return Providers(settings=settings, database=None, **phase1_slots)\n",
    )

    findings = module.scan_build_providers_slots(tmp_path)
    assert findings == [], "全覆盖样本不应误报：\n" + "\n".join(
        f"[{i.rule}] {i.message}" for i in findings
    )


# -- 4. 维度③：无调用者的 recover_* / *_sweep --------------------------------


def test_detects_orphan_sweep_definition(tmp_path: Path) -> None:
    """``recover_*`` 定义存在但无调用者 → 检出 ``wiring.orphan_sweep_definition``。"""
    module = _load_script()
    (tmp_path / "pkg_recovery.py").write_text(
        "def recover_on_startup():\n    return None\n", encoding="utf-8"
    )

    findings = module.scan_orphan_sweeps(tmp_path)
    assert any(item.rule == "wiring.orphan_sweep_definition" for item in findings), (
        "未检出孤儿 recover_* 定义（FR5-1 型失效）：" f"{[(i.rule, i.message) for i in findings]}"
    )


def test_called_sweep_definition_is_not_flagged(tmp_path: Path) -> None:
    """``recover_*`` 有调用者 → 不误报。"""
    module = _load_script()
    (tmp_path / "pkg_recovery.py").write_text(
        "class Manager:\n"
        "    def recover_on_startup(self):\n"
        "        return None\n"
        "\n"
        "def run(manager):\n"
        "    return manager.recover_on_startup()\n",
        encoding="utf-8",
    )

    findings = module.scan_orphan_sweeps(tmp_path)
    assert not any(
        "recover_on_startup" in item.message for item in findings
    ), "有调用者的 recover_* 不应误报"


# -- 5. 白名单生效 -----------------------------------------------------------


def test_whitelist_suppresses_flagged_symbol(tmp_path: Path) -> None:
    """显式登记于白名单的符号 → 不计为违规（预留未接线登记机制）。"""
    module = _load_script()
    orphan = tmp_path / "packages" / "sandbox" / "src" / "astra_sandbox"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "local_process_provider.py").write_text(
        "class LocalProcessSandboxProvider:\n    pass\n", encoding="utf-8"
    )

    findings = module.scan_registry_implementations(
        tmp_path, whitelist={"LocalProcessSandboxProvider": "预留契约（测试）"}
    )
    assert not any(
        "LocalProcessSandboxProvider" in item.message for item in findings
    ), "白名单未生效：预留符号仍被误报"


def test_reserved_null_implementations_are_whitelisted() -> None:
    """总纲 §12.2 预留空实现（``Null*``）已显式登记白名单 → 当前仓库不误报。"""
    module = _load_script()
    reserved = set(module.RESERVED_UNWIRED)
    assert reserved, "白名单为空（预留符号未登记）"

    findings = module.scan_registry_implementations(REPO_ROOT)
    offenders = [
        item.message for item in findings if any(symbol in item.message for symbol in reserved)
    ]
    assert offenders == [], f"白名单符号被误报：{offenders}"
