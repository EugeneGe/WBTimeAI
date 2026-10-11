"""纪律扫描集成测试（W10 / T2-51；设计 §2.17 / §3-#22 ``I-P2-22``）。

覆盖（**防「假绿」自我验证**）：

1. **仓库自检**：``scripts/scan_discipline.py`` 对**当前仓库**返回 ``0``（无违规）；
2. **检出能力**：对 ``tmp_path`` 构造的四类**违规样本**，脚本能逐条检出
   （分层 domain / 分层 router / 开源 edition gate / 凭证入日志）——若样本不被检出，
   说明扫描**失效**（假绿），测试必红；
3. **正向断言**：扫描集非空、脚本存在（防「扫了空目录 / 脚本缺失」的假绿）。

与既有 ``test_layering.py`` / ``test_open_source.py`` / ``test_credential_scan.py`` **互补**
（后者为包级 import 断言；本脚本为 **CI 单入口 AST 扫描**）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "scan_discipline.py"


def _load_script() -> ModuleType:
    """把 ``scripts/scan_discipline.py`` 作为独立模块加载（非包导入）。

    先登记进 ``sys.modules``——脚本含 ``from __future__ import annotations`` 的 dataclass，
    其 ``__module__`` 解析依赖模块已在 ``sys.modules``（否则 dataclass 装配期报错）。
    """
    assert SCRIPT_PATH.is_file(), f"纪律扫描脚本缺失：{SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("scan_discipline_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# -- 1. 仓库自检（当前仓库无违规） -------------------------------------------


def test_discipline_scan_is_clean_on_current_repo() -> None:
    """脚本对**当前仓库**返回 0；``scan`` 无发现项。"""
    module = _load_script()

    findings = module.scan(REPO_ROOT)
    assert findings == [], "当前仓库存在纪律违规：\n" + "\n".join(
        f"{item.path}:{item.line} [{item.rule}] {item.message}" for item in findings
    )

    assert module.main(["--root", str(REPO_ROOT)]) == 0


def test_scan_is_not_vacuous() -> None:
    """正向断言：扫描集非空，且各类规则的扫描函数均存在（防「扫了空目录」的假绿）。"""
    module = _load_script()

    files = list(module._iter_py(REPO_ROOT))
    assert files, "扫描集为空，纪律扫描可能失效"

    for rule in (
        module.scan_layering,
        module.scan_open_source,
        module.scan_credentials,
        module.scan_egress_single_source,
    ):
        assert callable(rule), f"规则函数缺失：{rule}"


# -- 2. 检出能力（构造违规样本） ---------------------------------------------


def _plant_violations(root: Path) -> dict[str, str]:
    """在 ``root`` 下构造四类违规样本，返回 ``规则名 → 期望命中路径``。"""
    domain_file = root / "pkg" / "src" / "astra_pkg" / "domain" / "bad.py"
    router_file = root / "apps" / "api" / "src" / "astra_api" / "routers" / "bad.py"
    market_file = root / "pkg" / "src" / "astra_pkg" / "core.py"
    log_file = root / "pkg" / "src" / "astra_pkg" / "logging_use.py"

    domain_file.parent.mkdir(parents=True, exist_ok=True)
    router_file.parent.mkdir(parents=True, exist_ok=True)

    # 分层 domain：import sqlalchemy（应违规）。
    domain_file.write_text("import sqlalchemy\n", encoding="utf-8")
    # 分层 router：import astra_database + 直调 MCPClient（应违规）。
    router_file.write_text(
        "from astra_database import SqlTaskRepository\n" "def _hack():\n" "    return MCPClient\n",
        encoding="utf-8",
    )
    # 开源：商业分流分支（应违规）。
    market_file.write_text(
        "def _feature(is_pro):\n" "    if commercial:\n" "        return 1\n" "    return 0\n",
        encoding="utf-8",
    )
    # 凭证：明文密码写日志（应违规）。
    log_file.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def _dump(password):\n"
        "    logger.info('auth %s', password)\n",
        encoding="utf-8",
    )

    return {
        "layering.domain_no_web_orm": "pkg/src/astra_pkg/domain/bad.py",
        "layering.router_no_infra": "apps/api/src/astra_api/routers/bad.py",
        "layering.router_no_mcp_client": "apps/api/src/astra_api/routers/bad.py",
        "open_source.no_commercial_gate": "pkg/src/astra_pkg/core.py",
        "credential.no_plaintext_in_log": "pkg/src/astra_pkg/logging_use.py",
    }


def test_scan_detects_planted_violations(tmp_path: Path) -> None:
    """四类违规样本**必须**被检出（规则名 + 命中路径逐条断言）。"""
    module = _load_script()
    expected = _plant_violations(tmp_path)

    findings = module.scan(tmp_path)
    detected = {(item.rule, item.path.replace("\\", "/")) for item in findings}

    missing = [key for key, path in expected.items() if (key, path) not in detected]
    assert not missing, f"未检出以下违规样本（扫描失效）：{missing}\n实得：{sorted(detected)}"

    # 违规根目录 → 退出码 1。
    assert module.main(["--root", str(tmp_path)]) == 1


def test_scan_reports_no_false_positive_on_benign_samples(tmp_path: Path) -> None:
    """**良性样本不误报**：``last_token_usage`` 用量日志、非日志的密码断言均不违规。"""
    module = _load_script()
    benign = tmp_path / "pkg" / "src" / "astra_pkg" / "benign.py"
    benign.parent.mkdir(parents=True, exist_ok=True)
    benign.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def _stats(last_token_usage):\n"
        "    logger.info('usage=%s', last_token_usage)\n"
        "def _masked(password):\n"
        "    return '***'\n",  # 敏感值未被日志 / 打印输出
        encoding="utf-8",
    )

    findings = module.scan(tmp_path)
    assert findings == [], "良性样本不应误报：\n" + "\n".join(
        f"{item.path}:{item.line} [{item.rule}] {item.message}" for item in findings
    )


# -- R1（Phase 2）· T2-56 · L-6：出网判定唯一源 --------------------------------


def test_scan_detects_second_egress_source(tmp_path: Path) -> None:
    """在允许位置之外**定义**出网判定符号 → 检出 ``egress.single_decision_source``。

    防「另建白名单判定源」：模拟在普通能力包里新定义 ``SecurityEgressPolicy`` / ``DENY_RANGES``。
    """
    module = _load_script()
    rogue = tmp_path / "pkg" / "src" / "astra_pkg" / "rogue_egress.py"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text(
        "class SecurityEgressPolicy:\n"
        "    def authorize(self, url):\n"
        "        return True\n"
        "DENY_RANGES = ()\n",
        encoding="utf-8",
    )

    findings = module.scan_egress_single_source(tmp_path)
    detected = {(item.rule, item.path.replace("\\", "/")) for item in findings}
    assert ("egress.single_decision_source", "pkg/src/astra_pkg/rogue_egress.py") in detected, (
        f"未检出另建判定源：{sorted(detected)}"
    )


def test_scan_allows_canonical_egress_definitions() -> None:
    """规范原语 / 唯一入口 / Phase 1 薄委托的**定义**不被误判（允许位置白名单有效）。"""
    module = _load_script()
    findings = [
        item
        for item in module.scan_egress_single_source(REPO_ROOT)
        if item.rule == "egress.single_decision_source"
    ]
    assert findings == [], "允许位置被误判为第二判定源：\n" + "\n".join(
        f"{item.path}:{item.line} {item.message}" for item in findings
    )
