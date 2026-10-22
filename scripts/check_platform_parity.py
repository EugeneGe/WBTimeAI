"""T1-02 — the platform-baseline gate: the three «与契约全等» claims of the
TS platform base are **measured**, not asserted in prose.

What this gate has to answer
----------------------------
V0.1.0 rebuilds the platform base in TypeScript while the frozen contracts in
``contracts/`` stay the single oracle.  Three artifacts are *derived* from those
contracts by ``scripts/gen_platform_contracts.mjs``:

===========================  ==================================================
``@wbtime/core`` 错误码        ``contracts/errors.json`` → ``codes``
``@wbtime/core`` 响应壳字段     ``contracts/envelope.schema.json`` → 四顶层键
``@wbtime/event`` 通道          ``contracts/sse/channels.json`` → ``channels``
===========================  ==================================================

For each of them the claim is *全等* (identical), not "looks about right":

* **count** must match, **and** every single member must match;
* a drift in either direction (contract gained a member the TS side lacks, or
  the TS side invented one the contract does not have) is ``INVALID``;
* **an empty set is ``INVALID``, never PASS** — an empty glob / empty array is
  vacuously equal to nothing and that is exactly the 哑真 failure mode this
  version exists to kill (K-11).  Both sides are floor-checked independently.

Exit codes (same convention as the sibling gates)::

    0   all three claims hold (measured, non-empty both sides)
    1   violation: any drift, or EMPTY on either side, or a missing artifact
    2   usage / environment error (bad args, unreadable contract)
    9   ``--self-test`` failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Final

sys.dont_write_bytecode = True

TAG: Final[str] = "check_platform_parity"

ROOT: Final[Path] = Path(__file__).resolve().parent.parent

CONTRACT_ERRORS: Final[str] = "contracts/errors.json"
CONTRACT_ENVELOPE: Final[str] = "contracts/envelope.schema.json"
CONTRACT_CHANNELS: Final[str] = "contracts/sse/channels.json"
# V0.3.1 · T031-05：生成面 = 基线 19 项 + delta（subagent.*）。delta 文件存在时并入
# 期望面（基线 19 项本身逐字节冻结、零变化 —— 本脚本不放宽基线，只是把"契约真源"
# 从单文件扩为"基线 + 唯一登记的 delta 增量"）；文件缺失时行为与 V0.3.0 完全一致。
CONTRACT_CHANNELS_DELTA: Final[str] = "contracts/sse/channels.delta.json"

TS_ERROR_CODES: Final[str] = "packages/core/src/generated/errors.generated.ts"
TS_ENVELOPE: Final[str] = "packages/core/src/generated/envelope.generated.ts"
TS_CHANNELS: Final[str] = "packages/event/src/generated/channels.generated.ts"


# ─────────────────────────────────────────────────────────────────────────────
# extraction
# ─────────────────────────────────────────────────────────────────────────────

_STRING_LITERAL_RE: Final[re.Pattern[str]] = re.compile(r'"((?:[^"\\]|\\.)*)"')


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def extract_string_array(text: str, name: str) -> list[str]:
    """Pull ``export const <name> ... = [ "a", "b", ];`` out of TS source text.

    Returns ``[]`` when the declaration is absent **or** when the array body is
    empty — the caller floors that as ``EMPTY``, which is the whole point: an
    unparsable/empty artifact must never be silently equal to anything.
    """
    match = re.search(
        r"export\s+const\s+" + re.escape(name) + r"\b[^=]*=\s*\[(.*?)\]",
        text,
        re.S,
    )
    if match is None:
        return []
    return _STRING_LITERAL_RE.findall(match.group(1))


def extract_ts_const_object(text: str, name: str) -> dict[str, str]:
    """Pull ``export const <name> = { KEY: "value", ... } as const;`` into a dict.

    Returns ``{}`` when the declaration is absent or the body holds no
    ``string``-valued entries — the caller floors that as ``INVALID(EMPTY)``.

    Why a brace-matching walk instead of a non-greedy regex: the object body can
    contain nested braces (comments, template strings, future nesting), and
    ``\\{(.*?)\\}`` would stop at the first inner ``}``.  Silently returning a
    truncated object is exactly the "gate parses half the file and reports PASS"
    failure this repo keeps hitting, so the walk is explicit.
    """
    anchor = re.search(r"export\s+const\s+" + re.escape(name) + r"\s*=\s*\{", text)
    if anchor is None:
        return {}
    start = anchor.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    body = text[start : index - 1]
    pairs: dict[str, str] = {}
    for entry in re.finditer(r"([A-Za-z0-9_]+)\s*:\s*\"([^\"]*)\"", body):
        pairs[entry.group(1)] = entry.group(2)
    return pairs


def extract_http_status_map(text: str) -> dict[str, int]:
    """Pull ``export const ERROR_HTTP_STATUS ... = { A: 400, ... };``."""
    match = re.search(
        r"export\s+const\s+ERROR_HTTP_STATUS\b[^=]*=\s*\{(.*?)\n\};",
        text,
        re.S,
    )
    if match is None:
        return {}
    return {
        name: int(status)
        for name, status in re.findall(r"^\s*([A-Z][A-Z0-9_]*):\s*(\d+),", match.group(1), re.M)
    }


def contract_error_codes(doc: dict) -> list[str]:
    return sorted((doc.get("codes") or {}).keys())


def contract_http_status(doc: dict) -> dict[str, int]:
    codes = doc.get("codes") or {}
    out: dict[str, int] = {}
    for name, entry in codes.items():
        status = (entry or {}).get("http_status")
        if isinstance(status, int):
            out[name] = status
    return out


def contract_envelope_fields(doc: dict) -> list[str]:
    defs = doc.get("$defs") or {}
    ok = (defs.get("successEnvelope") or {}).get("required") or []
    err = (defs.get("errorEnvelope") or {}).get("required") or []
    # 全等口径：成功壳与失败壳的顶层字段集合必须一致（总纲 §11.1「四顶层键恒在」）。
    return sorted(set(ok) | set(err))


def contract_channels(doc: dict) -> list[str]:
    return [str(c.get("channel")) for c in (doc.get("channels") or [])]


# ─────────────────────────────────────────────────────────────────────────────
# comparison
# ─────────────────────────────────────────────────────────────────────────────


def _report(label: str, contract_side: list[str], ts_side: list[str], ordered: bool) -> tuple[bool, str]:
    """Compare two sides and render one line.  Empty on either side ⇒ INVALID."""
    if not contract_side:
        return False, f"  INVALID(EMPTY:contract=0)  {label}"
    if not ts_side:
        return False, f"  INVALID(EMPTY:ts=0)        {label}"

    if ordered:
        equal = contract_side == ts_side
    else:
        equal = sorted(contract_side) == sorted(ts_side)

    if equal:
        return True, f"  OK({len(ts_side)})                 {label}"

    missing = [x for x in contract_side if x not in ts_side]
    extra = [x for x in ts_side if x not in contract_side]
    bits = []
    if missing:
        bits.append(f"契约有TS缺={missing}")
    if extra:
        bits.append(f"TS有契约无={extra}")
    if not bits:
        bits.append(f"顺序不一致 contract={contract_side} ts={ts_side}")
    return False, f"  INVALID                    {label} — contract={len(contract_side)} ts={len(ts_side)}; {'; '.join(bits)}"


def evaluate(root: Path) -> tuple[int, list[str]]:
    """Return ``(exit_code, report_lines)``.  ``0`` only if every claim holds."""
    lines: list[str] = [f"{TAG}: 平台基座与契约全等（数据源 = contracts/，实测口径）"]

    errors_path = root / CONTRACT_ERRORS
    envelope_path = root / CONTRACT_ENVELOPE
    channels_path = root / CONTRACT_CHANNELS
    for path in (errors_path, envelope_path, channels_path):
        if not path.is_file():
            lines.append(f"  INVALID                    契约缺失: {path.relative_to(root)}")
            return 1, lines

    errors_doc = load_json(errors_path)
    envelope_doc = load_json(envelope_path)
    channels_doc = load_json(channels_path)

    # V0.3.1 · T031-05：基线 + delta（存在才并入）。
    delta_path = root / CONTRACT_CHANNELS_DELTA
    delta_channels: list[str] = []
    if delta_path.is_file():
        delta_channels = contract_channels(load_json(delta_path))
    expected_channels = contract_channels(channels_doc) + delta_channels

    ts_errors_path = root / TS_ERROR_CODES
    ts_envelope_path = root / TS_ENVELOPE
    ts_channels_path = root / TS_CHANNELS
    for path in (ts_errors_path, ts_envelope_path, ts_channels_path):
        if not path.is_file():
            lines.append(f"  INVALID                    生成物缺失: {path.relative_to(root)}（先跑 scripts/gen_platform_contracts.mjs）")
            return 1, lines

    ts_errors_text = ts_errors_path.read_text(encoding="utf-8")
    ts_envelope_text = ts_envelope_path.read_text(encoding="utf-8")
    ts_channels_text = ts_channels_path.read_text(encoding="utf-8")

    ok_all = True

    # 1) 错误码：集合 + 数量 + 逐项全等
    ok, line = _report(
        "错误码  @wbtime/core ← contracts/errors.json",
        contract_error_codes(errors_doc),
        extract_string_array(ts_errors_text, "ERROR_CODE_LIST"),
        ordered=False,
    )
    ok_all &= ok
    lines.append(line)

    # 2) 响应壳字段：集合全等（成功壳与失败壳同构）
    ok, line = _report(
        "响应壳  @wbtime/core ← contracts/envelope.schema.json",
        contract_envelope_fields(envelope_doc),
        extract_string_array(ts_envelope_text, "ENVELOPE_FIELD_NAMES"),
        ordered=False,
    )
    ok_all &= ok
    lines.append(line)

    # 3) SSE 通道：集合 + 契约 index 顺序全等（基线在前、delta 追加，与生成器同源）
    ok, line = _report(
        "通道    @wbtime/event ← contracts/sse/channels.json(+delta)",
        expected_channels,
        extract_string_array(ts_channels_text, "SSE_CHANNEL_LIST"),
        ordered=True,
    )
    ok_all &= ok
    lines.append(line)

    # 3b) SSE_CHANNELS 枚举：**值集合**必须与契约全等。
    # Why this exists (QA finding P-4, 2026-10-21): item 3 above only compares
    # ``SSE_CHANNEL_LIST``.  Mutating the *enum value* (``AGENT_STARTED:
    # "agent.startedX"``) leaves the list untouched, so the gate stayed green while
    # ``SSE_CHANNELS.AGENT_STARTED`` — the thing runtime code actually uses — was
    # already wrong.  A gate that guards the list but not the enum guards the wrong
    # object.  Key names are deliberately NOT compared (contract uses ``event_class``
    # PascalCase, TS uses SCREAMING_SNAKE); comparing them adds a naming-convention
    # coupling without adding safety, so only the *values* and the *count* are locked.
    ts_enum = extract_ts_const_object(ts_channels_text, "SSE_CHANNELS")
    contract_values = sorted(expected_channels)
    ts_values = sorted(ts_enum.values())
    if not ts_enum or not contract_values:
        ok_all = False
        lines.append(
            f"  INVALID(EMPTY)             SSE_CHANNELS 枚举 — enum={len(ts_enum)} contract={len(contract_values)}"
        )
    elif ts_values != contract_values:
        ok_all = False
        missing = [v for v in contract_values if v not in ts_values]
        extra = [v for v in ts_values if v not in contract_values]
        lines.append(
            f"  INVALID                    SSE_CHANNELS 枚举 — 缺={missing} 多={extra}"
        )
    else:
        lines.append(f"  OK({len(ts_values)})                SSE_CHANNELS 枚举 ↔ 契约值集合")

    # 4) 错误码 → HTTP 状态映射（同为契约派生，一并比对，避免「码对了状态错了」）
    contract_status = contract_http_status(errors_doc)
    ts_status = extract_http_status_map(ts_errors_text)
    if not contract_status or not ts_status:
        ok_all = False
        lines.append(
            f"  INVALID(EMPTY)             错误码→HTTP状态映射 — contract={len(contract_status)} ts={len(ts_status)}"
        )
    elif contract_status != ts_status:
        ok_all = False
        diff = [k for k in contract_status if ts_status.get(k) != contract_status[k]]
        lines.append(f"  INVALID                    错误码→HTTP状态映射 — 不一致: {diff}")
    else:
        lines.append(f"  OK({len(ts_status)})                错误码→HTTP状态映射")

    lines.append(f"{TAG}: {'PASS' if ok_all else 'FAIL'}")
    return (0 if ok_all else 1), lines


# ─────────────────────────────────────────────────────────────────────────────
# --self-test
# ─────────────────────────────────────────────────────────────────────────────

_FAKE_ERRORS: Final[dict] = {
    "codes": {
        "UNKNOWN": {"code": "UNKNOWN", "http_status": 500},
        "NOT_FOUND": {"code": "NOT_FOUND", "http_status": 404},
    }
}

_FAKE_ENVELOPE: Final[dict] = {
    "$defs": {
        "successEnvelope": {"required": ["code", "data", "message", "request_id"]},
        "errorEnvelope": {"required": ["code", "data", "message", "request_id"]},
    }
}

_FAKE_CHANNELS: Final[dict] = {"channels": [{"channel": "agent.started"}]}


def _write_fixture(root: Path, *, codes: list[str], fields: list[str], channels: list[str]) -> None:
    (root / "contracts" / "sse").mkdir(parents=True, exist_ok=True)
    (root / "packages" / "core" / "src" / "generated").mkdir(parents=True, exist_ok=True)
    (root / "packages" / "event" / "src" / "generated").mkdir(parents=True, exist_ok=True)

    (root / CONTRACT_ERRORS).write_text(json.dumps(_FAKE_ERRORS), encoding="utf-8")
    (root / CONTRACT_ENVELOPE).write_text(json.dumps(_FAKE_ENVELOPE), encoding="utf-8")
    (root / CONTRACT_CHANNELS).write_text(json.dumps(_FAKE_CHANNELS), encoding="utf-8")

    code_rows = "".join(f'  "{c}",\n' for c in codes)
    status_rows = "".join(f"  {c}: {_FAKE_ERRORS['codes'].get(c, {}).get('http_status', 500)},\n" for c in codes)
    (root / TS_ERROR_CODES).write_text(
        "export const ERROR_CODE_LIST: readonly string[] = [\n" + code_rows + "];\n"
        "export const ERROR_HTTP_STATUS: Readonly<Record<string, number>> = {\n" + status_rows + "};\n",
        encoding="utf-8",
    )
    field_rows = "".join(f'  "{f}",\n' for f in fields)
    (root / TS_ENVELOPE).write_text(
        "export const ENVELOPE_FIELD_NAMES = [\n" + field_rows + "] as const;\n",
        encoding="utf-8",
    )
    channel_rows = "".join(f'  "{c}",\n' for c in channels)
    (root / TS_CHANNELS).write_text(
        "export const SSE_CHANNEL_LIST: readonly string[] = [\n" + channel_rows + "];\n",
        encoding="utf-8",
    )


def self_test() -> int:
    """Prove the gate can actually go red.  Returns 0 / 9."""
    import contextlib
    import io

    failures: list[str] = []

    def expect(label: str, want: int, got: int, detail: list[str]) -> None:
        if want != got:
            failures.append(f"{label}: 期望退出码 {want}，实测 {got}\n    " + "\n    ".join(detail))

    tmp = Path(tempfile.mkdtemp(prefix=f"{TAG}-selftest-"))
    try:
        # ① 全等 ⇒ PASS(0)
        root_ok = tmp / "ok"
        _write_fixture(root_ok, codes=["UNKNOWN", "NOT_FOUND"], fields=["code", "data", "message", "request_id"], channels=["agent.started"])
        code, detail = evaluate(root_ok)
        expect("① 全等", 0, code, detail)

        # ② 少一个码 ⇒ 红
        root_missing = tmp / "missing"
        _write_fixture(root_missing, codes=["UNKNOWN"], fields=["code", "data", "message", "request_id"], channels=["agent.started"])
        code, detail = evaluate(root_missing)
        expect("② 少一个错误码", 1, code, detail)

        # ③ 多一个契约没有的码 ⇒ 红
        root_extra = tmp / "extra"
        _write_fixture(root_extra, codes=["UNKNOWN", "NOT_FOUND", "INVENTED"], fields=["code", "data", "message", "request_id"], channels=["agent.started"])
        code, detail = evaluate(root_extra)
        expect("③ 多一个编造错误码", 1, code, detail)

        # ④ 响应壳字段缺失 ⇒ 红
        root_fields = tmp / "fields"
        _write_fixture(root_fields, codes=["UNKNOWN", "NOT_FOUND"], fields=["code", "data"], channels=["agent.started"])
        code, detail = evaluate(root_fields)
        expect("④ 响应壳字段缺失", 1, code, detail)

        # ⑤ 通道顺序错 ⇒ 红（ordered 比对）
        root_order = tmp / "order"
        root_order.mkdir(parents=True)
        shutil.copytree(root_ok, root_order, dirs_exist_ok=True)
        _write_fixture(root_order, codes=["UNKNOWN", "NOT_FOUND"], fields=["code", "data", "message", "request_id"], channels=["agent.thinking", "agent.started"])
        code, detail = evaluate(root_order)
        expect("⑤ 通道顺序错", 1, code, detail)

        # ⑥ 空集合必红（TS 侧空）
        root_empty = tmp / "empty"
        _write_fixture(root_empty, codes=[], fields=[], channels=[])
        code, detail = evaluate(root_empty)
        expect("⑥ 空集合必红", 1, code, detail)

        # ⑦ 契约侧空 ⇒ 红（防哑真的另一侧）
        root_cempty = tmp / "contract-empty"
        root_cempty.mkdir(parents=True, exist_ok=True)
        (root_cempty / "contracts" / "sse").mkdir(parents=True, exist_ok=True)
        (root_cempty / CONTRACT_ERRORS).write_text(json.dumps({"codes": {}}), encoding="utf-8")
        (root_cempty / CONTRACT_ENVELOPE).write_text(json.dumps({"$defs": {"successEnvelope": {"required": []}, "errorEnvelope": {"required": []}}}), encoding="utf-8")
        (root_cempty / CONTRACT_CHANNELS).write_text(json.dumps({"channels": []}), encoding="utf-8")
        code, detail = evaluate(root_cempty)
        expect("⑦ 契约侧空必红", 1, code, detail)

        # ⑧ 生成物缺失 ⇒ 红（提示先跑生成器）
        root_nots = tmp / "no-ts"
        root_nots.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root_ok / "contracts", root_nots / "contracts")
        code, detail = evaluate(root_nots)
        expect("⑧ 生成物缺失", 1, code, detail)

        # ⑨ 真实仓自检：真契约 vs 真生成物（若仓库状态完好应为 0）
        code, detail = evaluate(ROOT)
        expect("⑨ 真实仓", 0, code, detail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"{TAG}: --self-test FAILED")
        for f in failures:
            print(f"  - {f}")
        return 9

    print(f"{TAG}: --self-test PASSED（9 组反例全部按预期变红）")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# cli
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_platform_parity.py",
        description="T1-02 · 平台基座（错误码 / 响应壳 / SSE 通道）与 contracts/ 全等门禁",
    )
    parser.add_argument("--root", default=str(ROOT), help="仓库根（默认：脚本上级目录）")
    parser.add_argument("--self-test", action="store_true", help="跑自检：证明门禁会红")
    parser.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"{TAG}: --root 不是目录: {root}", file=sys.stderr)
        return 2

    if args.self_test:
        return self_test()

    code, lines = evaluate(root)
    if args.quiet:
        lines = [lines[0], lines[-1]]
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
