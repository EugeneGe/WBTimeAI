"""B-1 — TS error-code ledger gate: every TS literal must come from the contract.

Why this gate exists (audit finding B-1)
----------------------------------------
`contracts/errors.json` is the frozen oracle for error codes (code name +
``http_status``).  Two TS packages predate `@wbtime/contracts` and therefore
*inline* the literals by hand:

===========================  ==========================================
``packages/domain/src/errors.ts``  ``DOMAIN_ERROR_CODES``
``packages/ports/src/errors.ts``   ``PORTS_ERROR_CODES`` +
                                   ``CONFIGURATION_ERROR_HTTP_STATUS``
===========================  ==========================================

Both files carry a comment claiming "值必须与 contracts/errors.json 一致" and both
say the inlining is temporary.  A comment is not a check: a typo in the literal, or
a status drifting from 422 to 500, compiles fine, tests fine (nothing asserts the
number), and only surfaces as a wrong HTTP status in production.  This gate turns
that comment into an executable assertion, and it does so **without** importing
`@wbtime/core` — the whole point of the duplication is that these packages stay
dependency-free, so the comparison has to happen here, out of band.

Claims measured
---------------
=============================================  ==========================
claim                                           failure tag
=============================================  ==========================
contract ``codes`` parses to a non-empty map    ``empty-set``
contract entry is self-consistent              ``contract-inconsistent``
each TS block parses to a non-empty map         ``empty-set``
literal's value exists in the contract          ``unknown-code``
literal's value == its key (no rename drift)    ``value-drift``
``CONFIGURATION_ERROR_HTTP_STATUS`` == 422      ``status-drift``
``CONFIGURATION_ERROR_HTTP_STATUS`` exists      ``missing-status-const``
=============================================  ==========================

Empty sets are ``INVALID``, never PASS: an empty TS block compared against an empty
contract would be "equal" while proving nothing (K-11 哑真).  Both sides are
floor-checked independently.

Exit codes (same convention as the sibling gates)::

    0   every claim above holds
    1   violation (drift / unknown code / status drift / empty set / missing const)
    2   usage / environment error (unreadable contract or TS source)

``--self-test`` runs the same evaluator against four in-memory counter-examples
(unknown code / value drift / status drift / empty set) plus one well-formed
control; it passes only if **all four** turn red *and* the control stays green.

Python: standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

sys.dont_write_bytecode = True

TAG: Final[str] = "check_error_codes"

ROOT: Final[Path] = Path(__file__).resolve().parent.parent

CONTRACT_ERRORS: Final[str] = "contracts/errors.json"

#: TS const name → file that must declare it.
CODE_BLOCKS: Final[Mapping[str, str]] = {
    "DOMAIN_ERROR_CODES": "packages/domain/src/errors.ts",
    "PORTS_ERROR_CODES": "packages/ports/src/errors.ts",
}

#: The single HTTP-status literal that must track the contract, and where it lives.
STATUS_CONST: Final[str] = "CONFIGURATION_ERROR_HTTP_STATUS"
STATUS_CONST_FILE: Final[str] = "packages/ports/src/errors.ts"
STATUS_REFERENCE_CODE: Final[str] = "CONFIGURATION_ERROR"

#: Floor for "the parse actually found something".  Empty ⇒ INVALID, never PASS.
MIN_ENTRIES: Final[int] = 1


@dataclass(frozen=True)
class Violation:
    """One detected problem, tagged so the self-test can assert *what* was caught."""

    tag: str
    detail: str

    def render(self) -> str:
        """Render as ``[FAIL] tag: detail``."""
        return f"  [FAIL] {self.tag}: {self.detail}"


class ParseError(RuntimeError):
    """Raised when a declaration cannot be located in a source file."""


def parse_code_block(text: str, const_name: str) -> dict[str, str]:
    """Extract ``const_name = { KEY: "VALUE", ... }`` into a dict.

    Args:
        text: TS source.
        const_name: Declaration name (e.g. ``DOMAIN_ERROR_CODES``).

    Returns:
        Ordered mapping of literal key → literal value.

    Raises:
        ParseError: The declaration is absent, so no claim can be made about it.
    """
    block = re.search(
        rf"{re.escape(const_name)}\s*=\s*\{{(.*?)\n\}}",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if block is None:
        raise ParseError(f"找不到 {const_name} = {{ ... }} 声明")

    entries: dict[str, str] = {}
    for line in block.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        entry = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*"([^"]*)"\s*,?', stripped)
        if entry is None:
            continue
        entries[entry.group(1)] = entry.group(2)
    return entries


def parse_int_const(text: str, const_name: str) -> int | None:
    """Extract ``const_name = <int>``; ``None`` when the declaration is absent.

    Args:
        text: TS source.
        const_name: Declaration name.

    Returns:
        The integer value, or ``None``.
    """
    match = re.search(rf"{re.escape(const_name)}\s*=\s*(-?\d+)\s*;", text)
    return int(match.group(1)) if match is not None else None


def normalize_contract(raw_codes: Mapping[str, object]) -> tuple[dict[str, int], list[Violation]]:
    """Turn ``contracts/errors.json → codes`` into ``code → http_status``.

    Args:
        raw_codes: The raw ``codes`` mapping from the contract.

    Returns:
        ``(code_to_status, violations)``.  Entries whose ``code`` field does not
        match their key, or whose ``http_status`` is not an integer, are reported
        as ``contract-inconsistent`` and dropped from the returned mapping.
    """
    violations: list[Violation] = []
    normalized: dict[str, int] = {}

    for name, entry in raw_codes.items():
        if not isinstance(entry, dict):
            violations.append(Violation("contract-inconsistent", f"codes.{name} 不是对象"))
            continue
        declared = entry.get("code")
        if declared != name:
            violations.append(
                Violation(
                    "contract-inconsistent",
                    f"codes.{name}.code = {declared!r} 与键名不一致",
                )
            )
            continue
        status = entry.get("http_status")
        if not isinstance(status, int):
            violations.append(
                Violation("contract-inconsistent", f"codes.{name}.http_status 不是整数: {status!r}")
            )
            continue
        normalized[name] = status

    if not normalized:
        violations.append(
            Violation("empty-set", "契约 codes 解析出 0 条 —— 空集合必须红，不得当作 PASS")
        )
    return normalized, violations


def evaluate(
    contract_status: Mapping[str, int],
    blocks: Mapping[str, Mapping[str, str]],
    status_consts: Mapping[str, int],
) -> list[Violation]:
    """Evaluate every claim against already-parsed inputs (pure function).

    Args:
        contract_status: ``code → http_status`` from the contract.
        blocks: TS const name → parsed literal mapping.
        status_consts: TS const name → parsed integer value.

    Returns:
        All violations in a stable order (empty → unknown/drift → status).
    """
    violations: list[Violation] = []

    if not contract_status:
        violations.append(
            Violation("empty-set", "契约错误码为空 —— 空对空的相等不算 PASS")
        )

    for label, entries in blocks.items():
        if len(entries) < MIN_ENTRIES:
            violations.append(
                Violation(
                    "empty-set",
                    f"{label}: 解析出 {len(entries)} 个字面量 —— 空集合必须红，不得当作 PASS",
                )
            )
            continue
        for name, value in entries.items():
            if name in contract_status and value != name:
                violations.append(
                    Violation(
                        "value-drift",
                        f"{label}.{name} = {value!r}，与键名不一致（值漂移）",
                    )
                )
            if value not in contract_status:
                violations.append(
                    Violation(
                        "unknown-code",
                        f"{label}.{name} = {value!r}，契约里没有这个错误码",
                    )
                )

    expected_status = contract_status.get(STATUS_REFERENCE_CODE)
    if STATUS_CONST not in status_consts:
        violations.append(
            Violation("missing-status-const", f"{STATUS_CONST} 未声明（{STATUS_CONST_FILE}）")
        )
    elif expected_status is not None and status_consts[STATUS_CONST] != expected_status:
        violations.append(
            Violation(
                "status-drift",
                f"{STATUS_CONST} = {status_consts[STATUS_CONST]}，"
                f"契约 {STATUS_REFERENCE_CODE}.http_status = {expected_status}",
            )
        )

    return violations


def _read(repo_root: Path, rel_path: str) -> str:
    """Read a repo-relative text file.

    Args:
        repo_root: Repository root.
        rel_path: Path relative to the root.

    Returns:
        File content.

    Raises:
        OSError: The file is missing or unreadable.
    """
    return (repo_root / rel_path).read_text(encoding="utf-8")


def run_self_test() -> int:
    """Prove the evaluator turns red on four counter-examples (green on control).

    Returns:
        ``0`` when all four are caught and the control stays green, else ``1``.
    """
    contract = {"VALIDATION_ERROR": 400, "CONFIGURATION_ERROR": 422}
    good_blocks = {
        "DOMAIN_ERROR_CODES": {
            "VALIDATION_ERROR": "VALIDATION_ERROR",
            "CONFIGURATION_ERROR": "CONFIGURATION_ERROR",
        }
    }
    good_status = {STATUS_CONST: 422}

    cases: list[tuple[str, str, Mapping[str, int], Mapping[str, Mapping[str, str]], Mapping[str, int]]] = [
        (
            "unknown-code",
            "TS 侧写了个契约里没有的码",
            contract,
            {"PORTS_ERROR_CODES": {"TOTALLY_UNKNOWN": "TOTALLY_UNKNOWN"}},
            good_status,
        ),
        (
            "value-drift",
            "键名对、值漂移",
            contract,
            {"DOMAIN_ERROR_CODES": {"VALIDATION_ERROR": "VALIDATION_ERR"}},
            good_status,
        ),
        (
            "status-drift",
            "HTTP 状态码与契约不一致",
            contract,
            good_blocks,
            {STATUS_CONST: 500},
        ),
        (
            "empty-set",
            "TS 侧代码块为空",
            contract,
            {"PORTS_ERROR_CODES": {}},
            good_status,
        ),
    ]

    failures: list[str] = []

    control = evaluate(contract, good_blocks, good_status)
    if control:
        failures.append(
            "对照组（全部与契约一致）不该红，实测: " + "; ".join(v.render().strip() for v in control)
        )
    else:
        sys.stdout.write("  [ok  ] control: 字面量与状态码全部对齐契约 ⇒ 绿\n")

    for expected_tag, description, contract_status, blocks, status_consts in cases:
        found = evaluate(contract_status, blocks, status_consts)
        tags = {violation.tag for violation in found}
        if expected_tag in tags:
            sys.stdout.write(f"  [ok  ] {expected_tag}: 已捕获 '{description}'\n")
        else:
            failures.append(
                f"反例 '{description}' 未被捕获（期望 tag={expected_tag}，实测 tags={sorted(tags)}）"
            )

    if failures:
        for failure in failures:
            sys.stdout.write(f"  [FAIL] {failure}\n")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` pass, ``1`` violation, ``2`` usage / environment error.
    """
    parser = argparse.ArgumentParser(
        prog="check_error_codes.py",
        description="B-1 · TS error-code literals ≡ contracts/errors.json",
    )
    parser.add_argument("--self-test", action="store_true", help="用内存反例证明检测器会红")
    arguments = parser.parse_args(argv)

    sys.stdout.write(f"[{TAG}] repo={ROOT.as_posix()}\n")

    if arguments.self_test:
        sys.stdout.write(f"[{TAG}] self-test: 4 个反例 + 1 个对照组\n")
        code = run_self_test()
        if code == 0:
            sys.stdout.write(f"[{TAG}] PASS (self-test)\n")
        else:
            sys.stdout.write(f"[{TAG}] FAIL (self-test)\n")
        return code

    try:
        contract_doc = json.loads(_read(ROOT, CONTRACT_ERRORS))
    except (OSError, ValueError) as error:
        sys.stderr.write(f"[{TAG}] ERROR: 无法读取 {CONTRACT_ERRORS}: {error}\n")
        return 2

    raw_codes = contract_doc.get("codes")
    if not isinstance(raw_codes, dict):
        sys.stderr.write(f"[{TAG}] ERROR: {CONTRACT_ERRORS} 缺少 codes 对象\n")
        return 2

    contract_status, violations = normalize_contract(raw_codes)

    blocks: dict[str, dict[str, str]] = {}
    for const_name, rel_path in CODE_BLOCKS.items():
        try:
            text = _read(ROOT, rel_path)
        except OSError as error:
            sys.stderr.write(f"[{TAG}] ERROR: 无法读取 {rel_path}: {error}\n")
            return 2
        try:
            blocks[const_name] = parse_code_block(text, const_name)
        except ParseError as error:
            violations.append(Violation("missing-block", f"{rel_path}: {error}"))

    status_consts: dict[str, int] = {}
    try:
        ports_text = _read(ROOT, STATUS_CONST_FILE)
    except OSError as error:
        sys.stderr.write(f"[{TAG}] ERROR: 无法读取 {STATUS_CONST_FILE}: {error}\n")
        return 2
    status_value = parse_int_const(ports_text, STATUS_CONST)
    if status_value is not None:
        status_consts[STATUS_CONST] = status_value

    counts = "、".join(f"{name}={len(entries)}" for name, entries in blocks.items())
    expected_status = contract_status.get(STATUS_REFERENCE_CODE)
    sys.stdout.write(
        f"  measured: 契约 codes={len(contract_status)}（{counts}）, "
        f"{STATUS_CONST}={status_value!r}（契约 {STATUS_REFERENCE_CODE}.http_status={expected_status!r}）\n"
    )

    violations.extend(evaluate(contract_status, blocks, status_consts))

    for violation in violations:
        sys.stdout.write(violation.render() + "\n")

    if violations:
        sys.stdout.write(f"[{TAG}] FAIL ({len(violations)} 项)\n")
        return 1

    sys.stdout.write(
        f"  [ok  ] 全部 {sum(len(e) for e in blocks.values())} 个字面量都在契约中存在且值相同，"
        f"状态码 {status_value} == 契约 {expected_status}\n"
    )
    sys.stdout.write(f"[{TAG}] PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
