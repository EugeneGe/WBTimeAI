"""T04 / DoD#7 — the loop-contract invariant checker (fixture level).

Boundary of this deliverable (D-5, already ruled)
------------------------------------------------
At ``V0.0.2`` there is **no agent runtime yet** (it arrives in ``V0.3.0``).  The
six loop-contract counterexamples therefore exist as an **executable
specification plus fixtures**: this module is the judge, and
``scripts/conformance/traces/*.json`` are seven hand-built run traces (six that
each violate exactly one invariant, one clean baseline).

    These six counterexamples are **red at the fixture layer**.  The runtime layer
    is *not* claimed: ``V0.3.0`` must re-run this same judge against real traces.

The judge takes a run trace — an ordered list of events — and returns the ids of
the invariants it violates, so the same code can be pointed at a real
``V0.3.0`` trace later without touching the criteria.

The six invariants (design §1.6)
--------------------------------
======  =============================================================  ==============
id      predicate over the trace                                      fixture
======  =============================================================  ==============
``I-1`` two workers hold overlapping leases for the same ``run_id``     ``bad-double-worker``
``I-2`` any event for a run arrives **after** its ``run.terminal``      ``bad-event-after-terminal``
``I-3`` ``tool_call.started`` / ``tool_call.completed`` after           ``bad-tool-after-cancel``
        ``run.cancelled``
``I-4`` the same ``(run_id, tool_call_id)`` completes twice, **or**     ``bad-duplicate-tool-side-effect``
        one non-empty ``idempotency_key`` starts twice
``I-5`` ``budget.exhausted`` with no terminal event afterwards          ``bad-budget-no-terminal``
``I-6`` a ``(run_id, seq)`` pair repeats, or ``seq`` is not strictly    ``bad-seq-reuse``
        increasing inside a run
======  =============================================================  ==============

Trace format
------------
.. code-block:: json

    {
      "trace_id": "good-baseline",
      "contract_version": "V0.3.0-draft",
      "description": "...",
      "expected_violations": [],
      "events": [
        {"seq": 1, "run_id": "run-a", "type": "run.started"},
        {"seq": 2, "run_id": "run-a", "type": "run.lease.acquired",
         "worker_id": "w1", "lease": {"from_seq": 1, "to_seq": 10}},
        {"seq": 3, "run_id": "run-a", "type": "tool_call.started",
         "tool_call_id": "tc-1", "idempotency_key": "k-1"}
      ]
    }

``seq`` is per-run and must be strictly increasing in file order.  ``lease`` is
inclusive and only meaningful on ``run.lease.acquired``.

Modes and exit codes
--------------------
``--trace-dir DIR`` (default)  conformance: every fixture must violate **exactly**
    the set it declares.  An empty directory, a missing directory, or a trace with
    no ``expected_violations`` key is ``INVALID`` (K-11), never a pass.
``--require-clean``            every trace in the directory must be compliant —
    this is the mode ``V0.3.0`` will use on real traces.
``--trace FILE``               judge one trace and print its violations (runtime
    use; exit ``1`` when it violates anything).

``0``   conformant / clean
``1``   non-conformant, INVALID (empty or missing input), or a runtime trace violated
``2``   usage error
``9``   ``--self-test`` failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)

__all__ = [
    "TAG",
    "INVARIANTS",
    "INVARIANT_TITLES",
    "EXPECTED_BY_TRACE",
    "evaluate_trace",
    "load_trace",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "flow"

#: The six invariants, in report order.
INVARIANTS: Final[tuple[str, ...]] = ("I-1", "I-2", "I-3", "I-4", "I-5", "I-6")

#: One-line title per invariant (printed next to a violation).
INVARIANT_TITLES: Final[dict[str, str]] = {
    "I-1": "two workers advanced the same run with overlapping leases",
    "I-2": "an event was emitted after run.terminal",
    "I-3": "a tool call ran after run.cancelled",
    "I-4": "a duplicated tool side effect",
    "I-5": "budget exhausted but the run never reached a terminal state",
    "I-6": "event seq reused or not strictly increasing within a run",
}

#: Fixed expectation table for ``--self-test``.  It is deliberately duplicated
#: from the fixtures (which also declare ``expected_violations``): if the two ever
#: disagree the self-test fails, so a silent edit of a fixture cannot weaken the
#: suite.
EXPECTED_BY_TRACE: Final[dict[str, tuple[str, ...]]] = {
    "good-baseline": (),
    "bad-double-worker": ("I-1",),
    "bad-event-after-terminal": ("I-2",),
    "bad-tool-after-cancel": ("I-3",),
    "bad-duplicate-tool-side-effect": ("I-4",),
    "bad-budget-no-terminal": ("I-5",),
    "bad-seq-reuse": ("I-6",),
}

#: Event types that end a run.
TERMINAL_TYPES: Final[frozenset[str]] = frozenset(
    {"run.terminal", "run.completed", "run.failed", "run.cancelled"}
)

#: The strictest terminal marker, used by I-2 (a cancelled run may still emit the
#: cancellation bookkeeping that I-3 is about, so I-2 keys on this one only).
RUN_TERMINAL: Final[str] = "run.terminal"

#: Tool lifecycle events (I-3 / I-4).
TOOL_STARTED: Final[str] = "tool_call.started"
TOOL_COMPLETED: Final[str] = "tool_call.completed"

#: Budget marker (I-5).
BUDGET_EXHAUSTED: Final[str] = "budget.exhausted"

#: Lease marker (I-1).
LEASE_ACQUIRED: Final[str] = "run.lease.acquired"

#: Cancel marker (I-3).
RUN_CANCELLED: Final[str] = "run.cancelled"


class TraceError(RuntimeError):
    """Raised when a trace cannot be read or is structurally unusable."""


@dataclass(frozen=True)
class TraceVerdict:
    """Judgement for one trace.

    Attributes:
        trace_id: Declared ``trace_id`` (falls back to the file stem).
        violations: Invariant ids violated, in :data:`INVARIANTS` order.
        declared: ``expected_violations`` from the file (``None`` when absent).
        path: Where the trace came from.
        events: Number of events read.
    """

    trace_id: str
    violations: tuple[str, ...]
    declared: tuple[str, ...] | None
    path: str
    events: int


def load_trace(path: Path) -> dict[str, Any]:
    """Read one trace JSON document.

    Args:
        path: Trace file.

    Returns:
        The decoded document (``events`` is guaranteed to be a list).

    Raises:
        TraceError: The file is missing, not JSON, or has no ``events`` array.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise TraceError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise TraceError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict):
        raise TraceError(f"{path}: top level is not an object")
    events = document.get("events")
    if not isinstance(events, list):
        raise TraceError(f"{path}: missing 'events' array")
    return document


def _as_int(value: Any, *, default: int | None = None) -> int | None:
    """Coerce a JSON scalar to ``int`` without raising.

    Args:
        value: Candidate value.
        default: Returned when the value is not an integer.

    Returns:
        The integer, or ``default``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def evaluate_trace(trace: Mapping[str, Any]) -> list[str]:
    """Return the invariant ids violated by one trace.

    The function is pure and order-stable: the same trace always yields the same
    list, sorted by :data:`INVARIANTS`.  Malformed events are skipped (a missing
    field cannot be judged), but an event with no ``type`` is ignored loudly only
    in the sense that it contributes nothing — the trace-level checks below are
    all driven by the events that do carry a type.

    Args:
        trace: Parsed trace document (see module docstring for the format).

    Returns:
        Violated invariant ids in :data:`INVARIANTS` order (empty when compliant).
    """
    events = [event for event in (trace.get("events") or []) if isinstance(event, Mapping)]
    violations: set[str] = set()

    # --- I-6: seq strictly increasing per run, never reused -------------------
    seen_seq: set[tuple[str, int]] = set()
    last_seq: dict[str, int] = {}
    for event in events:
        run_id = str(event.get("run_id", ""))
        seq = _as_int(event.get("seq"))
        if seq is None:
            continue
        if (run_id, seq) in seen_seq:
            violations.add("I-6")
        seen_seq.add((run_id, seq))
        previous = last_seq.get(run_id)
        if previous is not None and seq <= previous:
            violations.add("I-6")
        last_seq[run_id] = seq

    # --- I-1: overlapping leases of different workers on one run -------------
    leases: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for event in events:
        if str(event.get("type", "")) != LEASE_ACQUIRED:
            continue
        lease = event.get("lease")
        if not isinstance(lease, Mapping):
            continue
        start = _as_int(lease.get("from_seq"))
        end = _as_int(lease.get("to_seq"))
        if start is None or end is None:
            continue
        worker = str(event.get("worker_id") or lease.get("worker_id") or "")
        leases[str(event.get("run_id", ""))].append((worker, min(start, end), max(start, end)))
    for entries in leases.values():
        for index, (worker_a, start_a, end_a) in enumerate(entries):
            for worker_b, start_b, end_b in entries[index + 1 :]:
                if worker_a == worker_b:
                    continue
                if start_a <= end_b and start_b <= end_a:
                    violations.add("I-1")

    # --- I-2: nothing may follow run.terminal --------------------------------
    terminal_at: dict[str, int] = {}
    for index, event in enumerate(events):
        if str(event.get("type", "")) == RUN_TERMINAL:
            terminal_at.setdefault(str(event.get("run_id", "")), index)
    for index, event in enumerate(events):
        position = terminal_at.get(str(event.get("run_id", "")))
        if position is not None and index > position:
            violations.add("I-2")

    # --- I-3: no tool activity after run.cancelled ---------------------------
    cancelled_at: dict[str, int] = {}
    for index, event in enumerate(events):
        if str(event.get("type", "")) == RUN_CANCELLED:
            cancelled_at.setdefault(str(event.get("run_id", "")), index)
    for index, event in enumerate(events):
        position = cancelled_at.get(str(event.get("run_id", "")))
        if position is None or index <= position:
            continue
        if str(event.get("type", "")) in (TOOL_STARTED, TOOL_COMPLETED):
            violations.add("I-3")

    # --- I-4: duplicated tool side effect ------------------------------------
    completions: dict[tuple[str, str], int] = defaultdict(int)
    starts_by_key: dict[str, int] = defaultdict(int)
    for event in events:
        event_type = str(event.get("type", ""))
        run_id = str(event.get("run_id", ""))
        if event_type == TOOL_COMPLETED:
            call_id = str(event.get("tool_call_id", ""))
            if call_id:
                completions[(run_id, call_id)] += 1
        elif event_type == TOOL_STARTED:
            key = str(event.get("idempotency_key") or "")
            if key:
                starts_by_key[key] += 1
    if any(count > 1 for count in completions.values()):
        violations.add("I-4")
    if any(count > 1 for count in starts_by_key.values()):
        violations.add("I-4")

    # --- I-5: budget exhausted must be followed by a terminal state ---------
    for index, event in enumerate(events):
        if str(event.get("type", "")) != BUDGET_EXHAUSTED:
            continue
        run_id = str(event.get("run_id", ""))
        reached_terminal = any(
            str(later.get("type", "")) in TERMINAL_TYPES
            for later in events[index + 1 :]
            if str(later.get("run_id", "")) == run_id
        )
        if not reached_terminal:
            violations.add("I-5")

    return [identifier for identifier in INVARIANTS if identifier in violations]


def _verdict_for(path: Path) -> TraceVerdict:
    """Load and judge one trace file.

    Args:
        path: Trace file.

    Returns:
        The verdict.

    Raises:
        TraceError: The file cannot be read or judged.
    """
    document = load_trace(path)
    events = document.get("events") or []
    declared_raw = document.get("expected_violations")
    declared: tuple[str, ...] | None
    if isinstance(declared_raw, list):
        declared = tuple(str(item) for item in declared_raw)
    else:
        declared = None
    trace_id = str(document.get("trace_id") or path.stem)
    return TraceVerdict(
        trace_id=trace_id,
        violations=tuple(evaluate_trace(document)),
        declared=declared,
        path=path.as_posix(),
        events=len(events),
    )


def _trace_files(directory: Path) -> list[Path]:
    """List the trace files in a directory (any non-empty ``*.json``).

    Args:
        directory: Trace directory.

    Returns:
        Sorted trace paths; empty when the directory is missing or has no traces.
    """
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def _report(verdict: TraceVerdict, *, require_clean: bool) -> tuple[bool, str]:
    """Decide whether one trace satisfies the mode's requirement.

    Args:
        verdict: The judged trace.
        require_clean: ``True`` for ``--require-clean`` (no violations allowed),
            ``False`` for conformance against ``expected_violations``.

    Returns:
        ``(ok, detail)``.
    """
    if require_clean:
        if verdict.violations:
            detail = ", ".join(f"{item} ({INVARIANT_TITLES[item]})" for item in verdict.violations)
            return False, f"violates {detail}"
        return True, "compliant"
    if verdict.declared is None:
        return False, "INVALID: no 'expected_violations' declared (a trace with no expectation cannot be judged)"
    if verdict.violations == verdict.declared:
        return True, f"violations={list(verdict.violations)} as declared"
    return False, (
        f"expected {list(verdict.declared)} but the judge produced {list(verdict.violations)}"
    )


def _check_directory(directory: Path, *, require_clean: bool) -> int:
    """Judge every trace in a directory and print one line per trace.

    Args:
        directory: Trace directory.
        require_clean: See :func:`_report`.

    Returns:
        ``0`` when every trace satisfies the mode, ``1`` otherwise (including the
        ``INVALID`` cases: missing directory and empty glob — K-11).
    """
    if not INVARIANTS:
        # K-11 + §11.1: an emptied invariant tuple would make every trace
        # "compliant" without judging anything.  That is INVALID, never a pass.
        _gate_io.log(TAG, "INVALID: INVARIANTS is empty — nothing was judged (K-11)")
        return _gate_io.EXIT_VIOLATION

    files = _trace_files(directory)
    if not files:
        _gate_io.log(TAG, f"INVALID: no trace files under {directory.as_posix()} (K-11: empty is never green)")
        return _gate_io.EXIT_VIOLATION

    failures = 0
    violating = 0
    for path in files:
        try:
            verdict = _verdict_for(path)
        except TraceError as error:
            _gate_io.log(TAG, f"INVALID: {error}")
            failures += 1
            continue
        ok, detail = _report(verdict, require_clean=require_clean)
        if verdict.violations:
            violating += 1
        _gate_io.log(
            TAG,
            f"trace={verdict.trace_id:<32} events={verdict.events:<3} "
            f"violations={list(verdict.violations) or '[]'}  {'OK' if ok else 'FAIL'} — {detail}",
        )
        if not ok:
            failures += 1

    mode = "require-clean" if require_clean else "conformance"
    _gate_io.log(
        TAG,
        f"SUMMARY[{mode}]: {len(files)} trace(s), {violating} with violations, {failures} failure(s)",
    )
    if failures:
        _gate_io.log(TAG, f"VERDICT: FAIL ({failures} trace(s) did not satisfy the mode)")
        return _gate_io.EXIT_VIOLATION
    _gate_io.log(TAG, "VERDICT: PASS (every trace behaves as the contract says it must)")
    return _gate_io.EXIT_OK


def _check_single(path: Path) -> int:
    """Judge one trace (runtime mode) and print its violations.

    Args:
        path: Trace file.

    Returns:
        ``0`` compliant, ``1`` violations or unreadable, ``2`` missing file.
    """
    if not INVARIANTS:
        _gate_io.log(TAG, "INVALID: INVARIANTS is empty — nothing was judged (K-11)")
        return _gate_io.EXIT_VIOLATION
    if not path.is_file():
        _gate_io.log(TAG, f"ERROR: trace not found: {path.as_posix()}")
        return _gate_io.EXIT_USAGE
    try:
        verdict = _verdict_for(path)
    except TraceError as error:
        _gate_io.log(TAG, f"INVALID: {error}")
        return _gate_io.EXIT_VIOLATION
    _gate_io.log(
        TAG,
        f"trace={verdict.trace_id} events={verdict.events} violations={list(verdict.violations) or '[]'}",
    )
    for identifier in verdict.violations:
        _gate_io.log(TAG, f"  {identifier}: {INVARIANT_TITLES[identifier]}")
    if verdict.violations:
        _gate_io.log(TAG, f"VERDICT: FAIL ({len(verdict.violations)} invariant(s) violated)")
        return _gate_io.EXIT_VIOLATION
    _gate_io.log(TAG, "VERDICT: PASS (compliant trace)")
    return _gate_io.EXIT_OK


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test(trace_dir: Path) -> int:
    """Prove the judge is not vacuous.

    Checks:

    1. every fixture in :data:`EXPECTED_BY_TRACE` is on disk and violates
       **exactly** the declared invariant (both the module table and the file's
       own ``expected_violations`` must agree);
    2. the clean baseline violates nothing;
    3. an empty directory is ``INVALID`` (exit ``1``, not ``0``);
    4. a missing directory is ``INVALID``;
    5. a trace without ``expected_violations`` is ``INVALID``;
    6. a synthetic trace that swaps one event turns the *declared-red* judgment
       red — i.e. the conformance comparison is not always-true;
    7. ``--require-clean`` rejects every bad fixture (the mode is not a no-op).

    Args:
        trace_dir: Directory holding the seven fixtures.

    Returns:
        ``0`` when every check passes, ``9`` otherwise.
    """
    checks: list[tuple[str, bool]] = []
    files = {path.stem: path for path in _trace_files(trace_dir)}

    if not files:
        _gate_io.log(TAG, f"INVALID: no fixtures under {trace_dir.as_posix()}")
        return _gate_io.EXIT_SELFTEST

    for trace_id, expected in EXPECTED_BY_TRACE.items():
        path = files.get(trace_id)
        if path is None:
            checks.append((f"fixture {trace_id} present", False))
            continue
        try:
            verdict = _verdict_for(path)
        except TraceError as error:
            checks.append((f"fixture {trace_id} readable ({error})", False))
            continue
        checks.append(
            (
                f"{trace_id}: judge={list(verdict.violations)} expected={list(expected)}",
                verdict.violations == expected,
            )
        )
        checks.append(
            (
                f"{trace_id}: fixture declares {list(verdict.declared)} (module table {list(expected)})",
                verdict.declared == expected,
            )
        )
        ok, detail = _report(verdict, require_clean=False)
        checks.append((f"{trace_id}: conformance verdict ok ({detail})", ok))
        if expected:
            clean_ok, _ = _report(verdict, require_clean=True)
            checks.append((f"{trace_id}: --require-clean rejects it", not clean_ok))

    # 3 — empty directory is INVALID, not green.
    with tempfile.TemporaryDirectory(prefix="wbtime-flow-empty-") as empty:
        code = _check_directory(Path(empty), require_clean=True)
        checks.append((f"empty trace dir is INVALID (exit {code})", code == _gate_io.EXIT_VIOLATION))

    # 4 — missing directory is INVALID.
    missing = _check_directory(trace_dir / "__no_such_trace_dir__", require_clean=True)
    checks.append((f"missing trace dir is INVALID (exit {missing})", missing == _gate_io.EXIT_VIOLATION))

    # 5 — a trace with no declared expectation cannot be judged as conformant.
    no_expectation = TraceVerdict(
        trace_id="synthetic",
        violations=("I-1",),
        declared=None,
        path="<synthetic>",
        events=1,
    )
    ok, _ = _report(no_expectation, require_clean=False)
    checks.append(("undeclared expectation is INVALID", not ok))

    # 6 — conformance comparison must be able to fail.
    wrong_expectation = TraceVerdict(
        trace_id="synthetic",
        violations=("I-1",),
        declared=("I-2",),
        path="<synthetic>",
        events=1,
    )
    ok, _ = _report(wrong_expectation, require_clean=False)
    checks.append(("declared/recomputed mismatch is red", not ok))

    # 7 — detector sanity on a synthetic compliant trace.
    compliant = {
        "trace_id": "synthetic-clean",
        "events": [
            {"seq": 1, "run_id": "r", "type": "run.started"},
            {"seq": 2, "run_id": "r", "type": "agent.thinking"},
            {"seq": 3, "run_id": "r", "type": "run.terminal"},
        ],
    }
    checks.append(("synthetic compliant trace has no violations", evaluate_trace(compliant) == []))
    non_monotonic = {
        "trace_id": "synthetic-seq",
        "events": [
            {"seq": 2, "run_id": "r", "type": "run.started"},
            {"seq": 1, "run_id": "r", "type": "agent.thinking"},
        ],
    }
    checks.append(
        ("non-monotonic seq trips I-6 only", evaluate_trace(non_monotonic) == ["I-6"])
    )

    failures = 0
    _gate_io.log(TAG, "self-test: 6 red fixtures + 1 clean baseline + INVALID inputs")
    for label, ok in checks:
        _gate_io.log(TAG, f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failures += 1
    _gate_io.log(TAG, f"self-test: {len(checks) - failures}/{len(checks)} passed")
    if failures:
        _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({failures} check(s))")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, "SELFTEST VERDICT: PASS (6 fixtures red on their own invariant, baseline green)")
    return _gate_io.EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="check_control_flow.py",
        description=(
            "Judge agent run traces against the six loop-contract invariants "
            "(DoD#7). Fixture layer only: the runtime arrives in V0.3.0."
        ),
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="directory of trace JSON files (default: scripts/conformance/traces)",
    )
    parser.add_argument("--trace", type=Path, default=None, metavar="FILE", help="judge one trace (runtime mode)")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="every trace must be compliant (no expected violations allowed)",
    )
    parser.add_argument("--self-test", action="store_true", help="prove the judge is not vacuous (exit 9 on failure)")
    parser.add_argument("--json", action="store_true", help="print a JSON verdict")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``1`` / ``2`` / ``9`` (see module docstring).
    """
    parser = _build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    trace_dir = arguments.trace_dir or _SCRIPTS_DIR / "conformance" / "traces"

    if arguments.self_test:
        return _self_test(trace_dir)

    if arguments.trace is not None:
        code = _check_single(Path(arguments.trace))
        if arguments.json:
            print(json.dumps({"trace": str(arguments.trace), "exit_code": code}, ensure_ascii=False))
        return code

    if arguments.json:
        files = _trace_files(Path(trace_dir))
        payload: Iterable[dict[str, Any]]
        try:
            payload = [
                {
                    "trace_id": verdict.trace_id,
                    "path": verdict.path,
                    "events": verdict.events,
                    "violations": list(verdict.violations),
                    "declared": list(verdict.declared) if verdict.declared is not None else None,
                }
                for verdict in (_verdict_for(path) for path in files)
            ]
        except TraceError as error:
            print(json.dumps({"error": str(error), "exit_code": _gate_io.EXIT_VIOLATION}, ensure_ascii=False))
            return _gate_io.EXIT_VIOLATION
        print(json.dumps(list(payload), ensure_ascii=False, indent=2))

    return _check_directory(Path(trace_dir), require_clean=bool(arguments.require_clean))


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
