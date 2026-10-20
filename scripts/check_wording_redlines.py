#!/usr/bin/env python3
"""V0.0.2 措辞红线门禁（QA 复核 F-6 的落地；F-6 第 2 轮修订）。

## 为什么需要这个脚本

`02-施工/README.md` §8.1 的三条裁定（D-1 / D-4 / D-5）各自规定了一句**必须写、且不得放宽**的台账措辞。
但这些措辞此前**只靠人读**——`check_docs.py` 只扫 `01-计划/README.md` 的「不做」栏，
且 V0.0.2 在 `EXEMPT_VERSIONS` 里（`scanned=14 exempt=13 gated=1`），
所以验收命令「`check_docs.py` → 0 违规」对本版的措辞**零证明力**。

这与 N-1（判据存在、逻辑正确、但没有执行者）是同型缺陷。本脚本把它变成可执行门禁。

## 检查项

| ID | 要求 |
|---|---|
| W-1 | `真后端自证.md` 必须含 D-1 的原话要素：「runner spawn」+「不等于」+「后端自身实现」 |
| W-2 | `S-1-扫描面登记.md` 与 `DoD-V0.0.2.md` 都必须含 `PARTIAL(1/2` |
| W-3 | `DoD-V0.0.2.md` 必须含「夹具层」与「V0.3.0」（DoD#7 边界） |
| W-4 | 全局禁止**结论性**使用放宽表述：`桶③ 100% 有替代门禁` / `前端 0 改动已验证` / `S-1 已通过` |

## W-4 的豁免：**结构化**，不是"同行含某个词"

第 1 版用过"同行出现 `结构完整性` 就豁免"，被 QA 构造出绕过：
「桶③ 100% 有替代门禁（**结构完整性已达成**）。」——把限定词当结论用，照样放行。
也用过"否定词 ±2 行窗口"，同样被绕过（否定词后隔 2 行加放宽句，照样吞掉）。

**现在只认四种结构化豁免**（逐一对应台账里真实存在的合法语境）：

| # | 豁免 | 依据 |
|---|---|---|
| 1 | **表格行**（`^\\s*\\|`） | DoD 判据表里列判据名 = 复述原文 |
| 2 | **标题行**（`^#{1,6}\\s`） | 章节标题 `## DoD#6 · 桶③ 100% 有替代门禁` = 复述原文 |
| 3 | **同行含否定词**（`禁止/不得/不可/不许/严禁`，窗口 = 0） | 「**禁止**写「X」」= 在禁止它 |
| 4 | **纯引用行**（整行只由 `「…」`/`"…"` 串 + 标点组成） | 「禁止出现」类清单的引用行 |

**不再有的豁免**：同行含某个"限定词"（可被当幌子）。**不再有的窗口**：否定词前后 N 行。

## 自证

`--self-test` 有 5 个用例（基线 + 4 注入），其中**注入 3 / 注入 4 正是 QA 用来绕过第 1 版的那两个**。

退出码：0 = 全满足；1 = 有违规；2 = 台账目录缺失（无法评估）；9 = `--self-test` 失败。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_UNEVALUABLE = 2
EXIT_SELFTEST = 9

LEDGER_REL = Path("docs/V1.0/V0.0.2-oracle自证与假绿反例/03-台账")

# ---- W-1 ----
D1_FILE = "真后端自证.md"
D1_TOKENS = ("runner spawn", "不等于", "后端自身实现")

# ---- W-2 ----
S1_TOKEN = "PARTIAL(1/2"
S1_FILES = ("S-1-扫描面登记.md", "DoD-V0.0.2.md")

# ---- W-3 ----
D7_FILE = "DoD-V0.0.2.md"
D7_TOKENS = ("夹具层", "V0.3.0")

# ---- W-4 ----
FORBIDDEN = (
    "桶③ 100% 有替代门禁",
    "前端 0 改动已验证",
    "S-1 已通过",
)
NEGATIONS = ("禁止", "不得", "不可", "不许", "严禁")

RE_TABLE = re.compile(r"^\s*\|")
RE_HEADING = re.compile(r"^#{1,6}\s")
# 纯引用行：整行只有引号串、顿号/逗号/句号/空白
RE_PURE_QUOTE = re.compile(r"^\s*(?:[「][^」]{1,80}[」]\s*[、，。]?\s*)+$")


def _exempt_kind(line: str) -> str | None:
    """返回豁免类别名，None 表示不豁免。"""
    if RE_TABLE.match(line):
        return "table"
    if RE_HEADING.match(line):
        return "heading"
    if any(n in line for n in NEGATIONS):
        return "negation"
    if RE_PURE_QUOTE.match(line):
        return "pure-quote"
    return None


def _read(ledger: Path, name: str) -> str | None:
    p = ledger / name
    return p.read_text(encoding="utf-8") if p.is_file() else None


def run(repo: Path) -> tuple[int, list[str], list[str], int]:
    """返回 (exit, checks, violations, 豁免计数)。"""
    ledger = repo / LEDGER_REL
    if not ledger.is_dir():
        return EXIT_UNEVALUABLE, [], [f"台账目录不存在: {ledger}"], 0

    violations: list[str] = []
    checks: list[str] = []
    exempted = 0

    # W-1
    txt = _read(ledger, D1_FILE)
    if txt is None:
        violations.append(f"W-1 {D1_FILE} 不存在（D-1 的措辞无处可查）")
    else:
        missing = [t for t in D1_TOKENS if t not in txt]
        if missing:
            violations.append(f"W-1 {D1_FILE} 缺要素: {missing}")
        else:
            checks.append(f"W-1 {D1_FILE}: 三要素齐")

    # W-2
    for name in S1_FILES:
        txt = _read(ledger, name)
        if txt is None:
            violations.append(f"W-2 {name} 不存在")
        elif S1_TOKEN not in txt:
            violations.append(f"W-2 {name} 未写 `{S1_TOKEN}`（S-1 必须记 PARTIAL，不得记通过）")
        else:
            checks.append(f"W-2 {name}: 含 `{S1_TOKEN}`")

    # W-3
    txt = _read(ledger, D7_FILE)
    if txt is None:
        violations.append(f"W-3 {D7_FILE} 不存在")
    else:
        missing = [t for t in D7_TOKENS if t not in txt]
        if missing:
            violations.append(f"W-3 {D7_FILE} 缺 DoD#7 边界要素: {missing}")
        else:
            checks.append(f"W-3 {D7_FILE}: DoD#7 边界齐")

    # W-4
    hits = 0
    for md in sorted(ledger.glob("*.md")):
        for idx, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            for bad in FORBIDDEN:
                if bad not in line:
                    continue
                if _exempt_kind(line) is not None:
                    exempted += 1
                    continue
                violations.append(f"W-4 {md.name}:{idx} 结论性使用放宽表述「{bad}」")
                hits += 1
    if hits == 0:
        checks.append(f"W-4 无结论性放宽表述（{exempted} 处合法语境已按结构化规则豁免）")

    code = EXIT_VIOLATION if violations else EXIT_OK
    return code, checks, violations, exempted


def _print(code: int, checks: list[str], violations: list[str], exempted: int) -> None:
    for c in checks:
        print(f"[wording]   ok   {c}")
    for v in violations:
        print(f"[wording]   FAIL {v}")
    if code == EXIT_OK:
        print(f"[wording] VERDICT: PASS (0) — {len(checks)} check(s); 豁免 {exempted} 处（全为表格/标题/否定/纯引用）")
    elif code == EXIT_UNEVALUABLE:
        print(f"[wording] VERDICT: UNEVALUABLE ({EXIT_UNEVALUABLE})")
    else:
        print(f"[wording] VERDICT: FAIL ({EXIT_VIOLATION}) — {len(violations)} violation(s)")


# ---------------------------------------------------------------- self-test
def _selftest(repo: Path) -> int:
    ledger = repo / LEDGER_REL
    if not ledger.is_dir():
        print(f"[wording] SELFTEST: 台账目录不存在: {ledger}", file=sys.stderr)
        return EXIT_SELFTEST

    cases: list[tuple[str, str, str, int]] = []  # (名, 目标文件, 追加/替换, 期望 exit)

    def clone(td: Path) -> Path:
        root = td / "repo"
        dst = root / LEDGER_REL
        dst.mkdir(parents=True)
        for f in ledger.glob("*.md"):
            shutil.copy2(f, dst / f.name)
        return root

    ok = True

    # 0 基线
    with tempfile.TemporaryDirectory() as td:
        root = clone(Path(td))
        code, _, v, _ = run(root)
        print(f"[wording] SELFTEST [baseline] expect=0 got={code}")
        ok &= code == EXIT_OK

    # 1 删 PARTIAL → W-2 红
    with tempfile.TemporaryDirectory() as td:
        root = clone(Path(td))
        p = root / LEDGER_REL / "S-1-扫描面登记.md"
        p.write_text(p.read_text(encoding="utf-8").replace(S1_TOKEN, "PARTIAL(2/2"), encoding="utf-8")
        code, _, v, _ = run(root)
        print(f"[wording] SELFTEST [inject-1 drop PARTIAL] expect=1 got={code} :: {v[:1]}")
        ok &= code == EXIT_VIOLATION

    # 2 正文加放宽句 → W-4 红
    with tempfile.TemporaryDirectory() as td:
        root = clone(Path(td))
        p = root / LEDGER_REL / "README.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n\n结论：前端 0 改动已验证。\n", encoding="utf-8")
        code, _, v, _ = run(root)
        print(f"[wording] SELFTEST [inject-2 plain widening] expect=1 got={code} :: {v[:1]}")
        ok &= code == EXIT_VIOLATION

    # 3 QA 的绕过：限定词当幌子 → 必须红（第 1 版在此假阴性）
    with tempfile.TemporaryDirectory() as td:
        root = clone(Path(td))
        p = root / LEDGER_REL / "README.md"
        p.write_text(
            p.read_text(encoding="utf-8") + "\n\n结论：桶③ 100% 有替代门禁（结构完整性已达成）。\n",
            encoding="utf-8",
        )
        code, _, v, _ = run(root)
        print(f"[wording] SELFTEST [inject-3 qualifier-as-shield] expect=1 got={code} :: {v[:1]}")
        ok &= code == EXIT_VIOLATION

    # 4 QA 的绕过：否定词后隔 2 行 → 必须红（第 1 版 ±2 行窗口在此假阴性）
    with tempfile.TemporaryDirectory() as td:
        root = clone(Path(td))
        p = root / LEDGER_REL / "README.md"
        p.write_text(
            p.read_text(encoding="utf-8") + "\n\n本条不得放宽。\n\n中间一行。\n\n前端 0 改动已验证。\n",
            encoding="utf-8",
        )
        code, _, v, _ = run(root)
        print(f"[wording] SELFTEST [inject-4 negation-window] expect=1 got={code} :: {v[:1]}")
        ok &= code == EXIT_VIOLATION

    print(f"[wording] SELFTEST VERDICT: {'PASS' if ok else 'FAIL'}")
    return EXIT_OK if ok else EXIT_SELFTEST


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        rest = [a for a in argv if a != "--self-test"]
        repo = Path(rest[0]).resolve() if rest else Path(__file__).resolve().parents[1]
        return _selftest(repo)

    repo = Path(argv[0]).resolve() if argv else Path(__file__).resolve().parents[1]
    code, checks, violations, exempted = run(repo)
    _print(code, checks, violations, exempted)
    return code


if __name__ == "__main__":
    sys.exit(main())
