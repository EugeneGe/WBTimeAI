#!/usr/bin/env python3
"""R3-00-② · `contract-manifest.json` 的**语义等价**断言（不是字节等价）。

它守什么
--------
v0019 登记时，`contracts/contract-manifest.json` 被**全量重排**（+3315/−3259 行）并
`objects` 41→48。重排本身不改变语义，但"看起来变了"——`manifest.sha256` 只能证明
**字节**变了，不能证明**语义**没被误删改。本门禁补的就是这条：

    **重排 + 纯新增 之后，`contract-manifest.json` 的语义面必须与 v0019 登记前完全一致。**

六条断言（逐条可断言，任一不满足 ⇒ 红）
--------------------------------------
A1 `objects` **恰好 53**（字面量；v0019 登记 48 + V0.3.1 契约增量 5，R-15 回钉 reseal
   2026-10-23；**再推进本数字必须有人解释为什么** —— 哪个版本的哪次登记、对应判据号）。
A2 相对基线**新增恰好 12 条**：7 条 path 含 `v0019`（v0019 五产物 + README + 副本台账），
   5 条为 V0.3.1 契约增量（`channels.delta.json` / `message.delta.keys.txt` /
   `message.delta.keys.sha256` / `subagent.started.txt` / `subagent.finished.txt`，
   见 `ADDED_PATH_MARKS`）。
A3 相对基线**删除 0 条**（v0018 的 41 条一条都不能少 —— 反「重排时顺手删」）。
A4 其余七个顶层结构的计数 `== {classification_rules 18 / criteria 23 / ddl_objects 245 /
   field_semantics 3 / notices 7 / schema 7 / status_semantics 5}`（全部不变）。
A5 `classification_rules` 的 **pattern 集合**与基线**集合相等**（只比 pattern，不比
   `matched` / `rationale` / 顺序 —— 重排会打乱顺序，但集合语义必须一致）。
A6 `schema` 自洽：`object_count == len(objects)`、`ddl_object_count == len(ddl_objects)`
   （防"改了 objects 忘了改摘要"）。

基线为什么**钉 commit**而不是 `git show HEAD`
------------------------------------------
R3-00 原文写「与 `git show HEAD` 版本集合相等」，那是**登记当时**（HEAD = v0019 前）的口径。
一旦登记被提交，HEAD 就等于现值 ⇒ 自比自，断言恒真（K-11 哑真）。故这里钉
`DEFAULT_BASELINE`（v0.2.0 收口点 `c6888b6`，v0019 登记前最后一个提交），并允许
`--baseline REV` 覆盖。基线取不到 ⇒ **以用法错误退出**，不降级为绿。

反例（`--self-test`）
--------------------
在临时副本上做 5 条注入，逐条断言"必须红且红在预期理由上"：
删 1 条 object / 加 1 条非 v0019 object / 删 1 条 notices / 改一个 classification pattern /
基线自身必须绿。

Exit codes：`0` 绿 · `1` 有差异 · `2` 用法/基线不可得 · `9` self-test 未按预期变红。

Python：标准库 only。
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - 取决于调用方式
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (只借退出码 / Diff / log，不含判定逻辑)

TAG: Final[str] = "manifest-semantics"

REPO: Final[Path] = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST: Final[Path] = REPO / "contracts" / "contract-manifest.json"
MANIFEST_REL: Final[str] = "contracts/contract-manifest.json"

#: v0019 登记前最后一个提交（v0.2.0 收口点）。改这里 = 声明"换了一个语义基线"，必须写理由。
DEFAULT_BASELINE: Final[str] = "c6888b6"

#: A1 —— 绝对计数（字面量）。
#: v0019 登记 = 48；V0.3.1 · T031-01 契约增量 +5（sse/channels.delta.json +
#: sse/golden/subagent.started.txt / subagent.finished.txt / message.delta.keys.txt /
#: message.delta.keys.sha256，R-15 回钉 reseal，2026-10-23）⇒ 53。
#: **再推进本数字必须有人解释为什么**（哪个版本的哪次登记、对应判据号）。
EXPECTED_OBJECTS: Final[int] = 53

#: A2/A3 —— 相对基线的增量形状。
#: v0019 登记 +7（路径含 v0019）；V0.3.1 契约增量 +5（路径含下述四个标记之一）。
EXPECTED_ADDED: Final[int] = 12
ADDED_PATH_MARKS: Final[tuple[str, ...]] = (
    "v0019",
    "channels.delta.json",
    "message.delta.keys",
    "subagent.started",
    "subagent.finished",
)

#: A4 —— 其余七个顶层结构的计数（全部不变）。
EXPECTED_TOP_COUNTS: Final[dict[str, int]] = {
    "classification_rules": 18,
    "criteria": 23,
    "ddl_objects": 245,
    "field_semantics": 3,
    "notices": 7,
    "schema": 7,
    "status_semantics": 5,
}


class BaselineUnavailable(RuntimeError):
    """基线版本取不到（git 不可用 / rev 不存在 / 内容不是 JSON）。"""


@dataclass
class Report:
    """差异集合（只承载结果，不承载"哪些原因合法"的判定）。"""

    diffs: list[_gate_io.Diff] = field(default_factory=list)

    def red(self, kind: str, subject: str, left: Any, right: Any) -> None:
        self.diffs.append(_gate_io.Diff(kind, subject, str(left), str(right)))

    @property
    def ok(self) -> bool:
        return not self.diffs


def load_manifest(path: Path) -> dict[str, Any]:
    """读一个 manifest JSON。"""
    return json.loads(path.read_text(encoding="utf-8"))


def load_baseline(rev: str) -> dict[str, Any]:
    """从 git 取基线版本的 manifest。

    Raises:
        BaselineUnavailable: git 退出码非 0，或输出不是合法 JSON。
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{rev}:{MANIFEST_REL}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        raise BaselineUnavailable(
            f"git show {rev}:{MANIFEST_REL} 退出码 {proc.returncode}：{(proc.stderr or '').strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - 历史件损坏才会触发
        raise BaselineUnavailable(f"基线 {rev} 的 manifest 不是合法 JSON：{exc}") from exc


def _paths(document: dict[str, Any]) -> list[str]:
    return [str(item.get("path", "")) for item in (document.get("objects") or [])]


def _patterns(document: dict[str, Any]) -> set[str]:
    return {str(rule.get("pattern", "")) for rule in (document.get("classification_rules") or [])}


def check(document: dict[str, Any], baseline: dict[str, Any]) -> Report:
    """跑 A1–A6，返回差异集合。"""
    rep = Report()

    current_paths = _paths(document)
    baseline_paths = _paths(baseline)
    current_set = set(current_paths)
    baseline_set = set(baseline_paths)

    # A1 绝对计数
    if len(current_paths) != EXPECTED_OBJECTS:
        rep.red("count.objects", "objects", EXPECTED_OBJECTS, len(current_paths))
    if len(current_set) != len(current_paths):
        duplicated = sorted({p for p in current_paths if current_paths.count(p) > 1})
        rep.red("object.duplicate", "objects", "no duplicates", duplicated[:10])

    # A2 新增条数与命名（V0.3.1 起：标记为**多值**，见 ADDED_PATH_MARKS）
    added = sorted(current_set - baseline_set)
    if len(added) != EXPECTED_ADDED:
        rep.red("count.added", "objects", EXPECTED_ADDED, len(added))
    for path in added:
        if not any(mark in path for mark in ADDED_PATH_MARKS):
            rep.red("object.added-unknown-mark", path, f"path 含 {ADDED_PATH_MARKS} 之一", path)

    # A3 删除必须为 0
    for path in sorted(baseline_set - current_set):
        rep.red("object.removed", path, "present in baseline", "absent now")

    # A4 顶层计数
    for key, expected in EXPECTED_TOP_COUNTS.items():
        value = document.get(key)
        if not isinstance(value, (list, dict)):
            rep.red(f"count.{key}", key, expected, f"missing/not a collection: {type(value).__name__}")
            continue
        if len(value) != expected:
            rep.red(f"count.{key}", key, expected, len(value))

    # A5 classification_rules 的 pattern 集合
    if _patterns(document) != _patterns(baseline):
        left = sorted(_patterns(baseline))
        right = sorted(_patterns(document))
        for pattern in sorted(_patterns(baseline) - _patterns(document)):
            rep.red("classification.pattern", pattern, "present in baseline", "absent now")
        for pattern in sorted(_patterns(document) - _patterns(baseline)):
            rep.red("classification.pattern", pattern, "absent in baseline", "added now")
        if not (_patterns(baseline) - _patterns(document)) and not (_patterns(document) - _patterns(baseline)):
            rep.red("classification.pattern", "set", left, right)

    # A6 schema 自洽
    schema = document.get("schema") or {}
    for field_name, actual_len in (("object_count", len(current_paths)), ("ddl_object_count", len(document.get("ddl_objects") or []))):
        declared = schema.get(field_name)
        if declared != actual_len:
            rep.red(f"schema.{field_name}", field_name, actual_len, declared)

    return rep


def print_report(rep: Report, document: dict[str, Any], baseline: dict[str, Any], rev: str) -> None:
    """打一行摘要 + 差异明细。"""
    paths = _paths(document)
    added = sorted(set(paths) - set(_paths(baseline)))
    _gate_io.log(
        TAG,
        f"objects {len(paths)}（期望 {EXPECTED_OBJECTS}）· 相对 {rev} 新增 {len(added)}（期望 {EXPECTED_ADDED}）· 删除 {len(set(_paths(baseline)) - set(paths))}",
    )
    counts = " / ".join(
        f"{key} {len(document.get(key) or [])}" for key in EXPECTED_TOP_COUNTS
    )
    _gate_io.log(TAG, f"顶层计数：{counts}")
    _gate_io.log(
        TAG,
        f"classification_rules pattern {len(_patterns(document))} 个；与基线集合{'相等' if _patterns(document) == _patterns(baseline) else '不等'}",
    )


def run_self_test(manifest_path: Path, baseline: dict[str, Any]) -> int:
    """5 条注入，逐条断言"必红且红在预期理由上"。"""
    _gate_io.log(TAG, "SELFTEST 开始（全部操作在临时副本，绝不动 contracts/）")
    document = load_manifest(manifest_path)

    # 基线自身必须绿 —— 否则后面所有注入的"红"都无法归因。
    base_rep = check(document, baseline)
    if not base_rep.ok:
        _gate_io.log(TAG, f"SELFTEST FAIL: baseline 自身不绿，差异 {len(base_rep.diffs)} 条")
        for diff in base_rep.diffs[:10]:
            _gate_io.log(TAG, f"  ! {diff.render()}")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, "  baseline: 绿")

    cases: list[tuple[str, dict[str, Any], str]] = []

    drop = copy.deepcopy(document)
    removed_path = _paths(drop)[0]
    drop["objects"] = [o for o in drop["objects"] if o.get("path") != removed_path]
    cases.append(("case1 删 1 条 object", drop, "object.removed"))

    extra = copy.deepcopy(document)
    extra["objects"].append(
        {
            "path": "extra-artifact.json",
            "sha256": "0" * 64,
            "source": "manual",
            "generated_by": None,
            "dialect_only": None,
            "requirement": "selftest",
        }
    )
    cases.append(("case2 加 1 条无登记标记 object（V0.3.1 起标记多值，仍必须红）", extra, "object.added-unknown-mark"))

    drop_notice = copy.deepcopy(document)
    drop_notice["notices"] = drop_notice["notices"][:-1]
    cases.append(("case3 删 1 条 notices", drop_notice, "count.notices"))

    rename_pattern = copy.deepcopy(document)
    rename_pattern["classification_rules"][0]["pattern"] = "selftest/*"
    cases.append(("case4 改 1 个 classification pattern", rename_pattern, "classification.pattern"))

    bad_summary = copy.deepcopy(document)
    bad_summary["schema"]["object_count"] = len(_paths(bad_summary)) + 1
    cases.append(("case5 schema.object_count 与 objects 不一致", bad_summary, "schema.object_count"))

    failures = 0
    for title, mutated, expected_kind in cases:
        rep = check(mutated, baseline)
        kinds = {diff.kind for diff in rep.diffs}
        if expected_kind in kinds:
            _gate_io.log(TAG, f"  v {title} ⇒ 必红（{expected_kind}）")
        else:
            failures += 1
            _gate_io.log(TAG, f"  x {title} ⇒ 未按预期变红（实际 kinds={sorted(kinds)}）")

    if failures:
        _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL（{failures}/{len(cases)} 条注入未按预期变红）")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, f"SELFTEST VERDICT: PASS（{len(cases)} 次注入都按预期理由变红，baseline 保持绿）")
    return _gate_io.EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_manifest_semantics.py",
        description="R3-00-②：contract-manifest.json 的语义等价断言（objects/计数/pattern 集合）",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="manifest JSON 路径")
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        metavar="REV",
        help=f"语义基线 commit（默认 {DEFAULT_BASELINE} = v0019 登记前）",
    )
    parser.add_argument("--self-test", action="store_true", help="5 条注入并断言必红")
    parser.add_argument("--json", type=Path, default=None, help="把差异另存为 JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    try:
        baseline = load_baseline(args.baseline)
    except BaselineUnavailable as exc:
        _gate_io.log(TAG, f"USAGE FAIL: 基线不可得 —— {exc}")
        return _gate_io.EXIT_USAGE

    if args.self_test:
        try:
            return run_self_test(args.manifest, baseline)
        except (OSError, json.JSONDecodeError) as exc:
            _gate_io.log(TAG, f"USAGE FAIL: {exc}")
            return _gate_io.EXIT_USAGE

    try:
        document = load_manifest(args.manifest)
    except (OSError, json.JSONDecodeError) as exc:
        _gate_io.log(TAG, f"USAGE FAIL: {exc}")
        return _gate_io.EXIT_USAGE

    rep = check(document, baseline)
    print_report(rep, document, baseline, args.baseline)

    _gate_io.log(TAG, "-" * 74)
    if rep.ok:
        _gate_io.log(TAG, "VERDICT: PASS —— 语义面与基线一致（重排 + 纯新增，无删改）")
        return _gate_io.EXIT_OK

    _gate_io.log(TAG, f"VERDICT: FAIL —— {len(rep.diffs)} 条语义差异")
    for diff in rep.diffs[:40]:
        _gate_io.log(TAG, f"  {diff.render()}")
    if len(rep.diffs) > 40:
        _gate_io.log(TAG, f"  …（共 {len(rep.diffs)} 条，已截断至前 40 条）")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([diff.to_dict() for diff in rep.diffs], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _gate_io.log(TAG, f"diff 已写入 {args.json}")
    return _gate_io.EXIT_VIOLATION


if __name__ == "__main__":
    raise SystemExit(main())
