"""T04 / S-7 — the meta gate: prove that a gate *can be greened* and that the
greening is detectable.

The question S-7 answers
------------------------
"I believe the gate is red" is worth nothing if the gate can be edited into
"always green" without anybody noticing.  So S-7 does the opposite of the
injection engine: instead of asking *"does the gate go red?"*, it asks
*"can I make the gate lie, and does the harness notice?"*.

For every probe the meta gate performs three observations on a **temporary
clone** of ``scripts/`` + ``contracts/`` (the real source tree is never touched):

============================  ===============================================
``control``   the *unmutated* gate on a known-bad input must detect it
``mutated``   the gate with a "make it green" mutation, on the same input
``verdict``   ``INVALID`` when the mutated gate no longer detects the bad input
              (that is the finding: this gate's green is not self-proving), or
              when it refuses to judge at all (its own vacuity guard fired)
============================  ===============================================

Verdict vocabulary
------------------
``INVALID(DEFEATED)``
    The mutation worked: the gate reported green on an input that is known to be
    bad.  Meta recorded the attack vector and the exact mutation.
``INVALID(REFUSED)``
    The mutated gate refused to judge and printed ``INVALID`` (empty expectation
    set / empty invariant set).  A gate that says "I have nothing to check" is
    honest; a gate that says PASS in that state is the fake green this version
    exists to kill (K-11).
``INVALID(ABSENT)``
    The gate under test is not on disk yet (``check_frontend_baseline.py`` is a
    T05 deliverable).  Absence is ``INVALID``, never a pass (K-11).  This is the
    **weakest** of the three classes and is reported separately in the summary
    line; ``--strict`` promotes it to failure (``40``).
``NOT-DETECTED``
    The mutation did not change the outcome — the gate still detected the bad
    input correctly.  Meta learned nothing, so the probe **fails** (``40``).
``UNEVALUABLE``
    The control observation itself failed (no red to lose, clone failure,
    mutation anchor missing).  ``41``.

The four probes
---------------
``inject``            empty one case's expectation set (``must_be_red = ()``)
``oracle``            replace the comparison with the identity (always MATCH)
``control-flow``      empty the invariant tuple
``frontend-baseline`` empty glob judged green (``MIN_FILES = 0``; ``ABSENT`` today)

CLI::

    python -B scripts/meta_gate.py
    python -B scripts/meta_gate.py --probe oracle --verbose
    python -B scripts/meta_gate.py --strict
    python -B scripts/meta_gate.py --self-test

Exit codes (design §3.3, the 40/41 band belongs to this script)::

    0   every probe reported INVALID
    40  a probe reported NOT-DETECTED (mutation ineffective — nothing was proven),
        or ``--strict`` and a gate is absent
    41  a probe could not be evaluated (control red missing, clone/mutation failure)
    2   usage error
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)
import inject_cases  # noqa: E402  (victims + mutators, reused on purpose)
import inject_counterexample as engine  # noqa: E402  (clone / reseal / run_command)

__all__ = [
    "TAG",
    "ProbeOutcome",
    "PROBES",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "meta"

#: The token a mutated gate must print when it refuses to judge.
INVALID_TOKEN: Final[str] = "INVALID"

#: Verdict strings (kept as constants so the summary can count them).
VERDICT_DEFEATED: Final[str] = "INVALID(DEFEATED)"
VERDICT_REFUSED: Final[str] = "INVALID(REFUSED)"
VERDICT_ABSENT: Final[str] = "INVALID(ABSENT)"
VERDICT_NOT_DETECTED: Final[str] = "NOT-DETECTED"
VERDICT_UNEVALUABLE: Final[str] = "UNEVALUABLE"


class ProbeError(RuntimeError):
    """Raised when a probe cannot be evaluated (``UNEVALUABLE`` / ``41``)."""


@dataclass(frozen=True)
class ProbeOutcome:
    """Result of one meta probe.

    Attributes:
        probe_id: ``inject`` / ``oracle`` / ``control-flow`` / ``frontend-baseline``.
        gate: The gate (or engine) under test, relative to the repository root.
        mutation: One-line description of the "make it green" mutation.
        control: One-line description of the control observation.
        mutated: One-line description of the mutated observation.
        verdict: One of the ``VERDICT_*`` constants.
        detail: Why the verdict is what it is.
        exit_code: ``0`` for an INVALID verdict, ``40`` for NOT-DETECTED,
            ``41`` for UNEVALUABLE.
    """

    probe_id: str
    gate: str
    mutation: str
    control: str
    mutated: str
    verdict: str
    detail: str
    exit_code: int

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view.

        Returns:
            The record as a plain dict.
        """
        return {
            "probe_id": self.probe_id,
            "gate": self.gate,
            "mutation": self.mutation,
            "control": self.control,
            "mutated": self.mutated,
            "verdict": self.verdict,
            "detail": self.detail,
            "exit_code": self.exit_code,
        }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _prepare_clone(source_repo: Path, scratch_root: Path, label: str, *, keep: bool) -> Path:
    """Clone ``contracts/`` + ``scripts/`` into a fresh scratch repository.

    Args:
        source_repo: Real repository root (read-only).
        scratch_root: Parent directory for the clone.
        label: Prefix for the scratch directory name.
        keep: Keep the clone afterwards (printed by the caller's caller).

    Returns:
        The clone's repository root.

    Raises:
        ProbeError: The clone failed.
    """
    scratch = Path(tempfile.mkdtemp(prefix=f"wbtime-meta-{label}-", dir=str(scratch_root)))
    clone = scratch / "repo"
    try:
        engine.clone_repo(source_repo, clone)
    except engine.CaseError as error:
        raise ProbeError(f"cannot clone the repository: {error}") from error
    if keep:
        _gate_io.log(TAG, f"  kept: {clone.as_posix()}")
    return clone


def _run(clone: Path, script: str, argv: Sequence[str], *, timeout_s: float) -> engine.CommandResult:
    """Run one script inside a clone.

    Args:
        clone: Clone repository root.
        script: Script path relative to the clone root.
        argv: Arguments after the script path.
        timeout_s: Hard timeout.

    Returns:
        The command result.
    """
    command = [sys.executable, "-B", str(clone / Path(*script.split("/"))), *argv]
    return engine.run_command(command, cwd=clone, timeout_s=timeout_s)


def _replace_once(path: Path, old: str, new: str, *, label: str) -> str:
    """Replace ``old`` with ``new`` exactly once inside ``path`` (the mutation).

    Args:
        path: File to rewrite inside the clone.
        old: Anchor text; must occur exactly once.
        new: Replacement text.
        label: Description used in the error message and the evidence line.

    Returns:
        The description of the mutation.

    Raises:
        ProbeError: The anchor is missing or ambiguous — a mutation that silently
            did nothing would make the probe meaningless.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ProbeError(f"cannot read {path.as_posix()}: {error}") from error
    occurrences = text.count(old)
    if occurrences != 1:
        raise ProbeError(
            f"mutation anchor for {label} occurs {occurrences} time(s) in "
            f"{path.as_posix()}, expected exactly 1"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return label


def _replace_regex_once(path: Path, pattern: str, new: str, *, label: str) -> str:
    """Replace the single regex match in ``path`` (name the mutation in ``label``).

    Args:
        path: File to rewrite inside the clone.
        pattern: Regular expression that must match exactly once.
        new: Replacement text (literal).
        label: Description used in the error message and the evidence line.

    Returns:
        The description of the mutation.

    Raises:
        ProbeError: The pattern matches zero or more than one time.
    """
    text = path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ProbeError(
            f"mutation pattern for {label} matched {len(matches)} time(s) in "
            f"{path.as_posix()}, expected exactly 1"
        )
    start, end = matches[0].span()
    path.write_text(text[:start] + new + text[end:], encoding="utf-8")
    return label


def _insert_before(path: Path, anchor: str, block: str, *, label: str) -> str:
    """Insert ``block`` immediately before the single occurrence of ``anchor``.

    Python rebinds module-level names in source order, so appending a second
    ``def recompute(...)`` before the ``__main__`` guard replaces the original at
    import time *without* deleting one line of it — a realistic "someone patched
    the gate" mutation, and one that cannot silently no-op.

    Args:
        path: File to rewrite inside the clone.
        anchor: Text that must occur exactly once (the insertion point).
        block: Code block to insert (no trailing newline required).
        label: Description used in the error message and the evidence line.

    Returns:
        The description of the mutation.

    Raises:
        ProbeError: The anchor is missing or ambiguous.
    """
    text = path.read_text(encoding="utf-8-sig")
    if text.count(anchor) != 1:
        raise ProbeError(
            f"insertion anchor for {label} occurs {text.count(anchor)} time(s) in "
            f"{path.as_posix()}, expected exactly 1"
        )
    path.write_text(text.replace(anchor, block.rstrip("\n") + "\n\n\n" + anchor, 1), encoding="utf-8")
    return label


def _classify(
    *,
    probe_id: str,
    gate: str,
    mutation: str,
    control: str,
    mutated: str,
    control_detected: bool,
    mutated_exit: int,
    mutated_output: str,
    absent: bool = False,
    absent_reason: str = "",
) -> ProbeOutcome:
    """Turn two observations into a probe verdict.

    This is the whole judgement of the meta gate, kept as one pure function so
    ``--self-test`` can exercise every branch without cloning anything.

    Args:
        probe_id: Probe identifier.
        gate: Gate under test.
        mutation: Mutation description.
        control: Control observation description.
        mutated: Mutated observation description.
        control_detected: Did the *unmutated* gate detect the known-bad input?
        mutated_exit: Exit code of the mutated gate on the same input.
        mutated_output: Combined output of the mutated gate.
        absent: The gate is not on disk (absence is INVALID, never a pass).
        absent_reason: Why it is absent (quoted in the detail line).

    Returns:
        A :class:`ProbeOutcome`.
    """
    if absent:
        return ProbeOutcome(
            probe_id=probe_id,
            gate=gate,
            mutation=mutation,
            control=control,
            mutated=mutated,
            verdict=VERDICT_ABSENT,
            detail=absent_reason or "gate is not on disk",
            exit_code=_gate_io.EXIT_OK,
        )
    if not control_detected:
        return ProbeOutcome(
            probe_id=probe_id,
            gate=gate,
            mutation=mutation,
            control=control,
            mutated=mutated,
            verdict=VERDICT_UNEVALUABLE,
            detail="the unmutated gate did not detect the known-bad input: there is no red to lose",
            exit_code=_gate_io.EXIT_META_UNEVALUABLE,
        )
    if INVALID_TOKEN in mutated_output:
        return ProbeOutcome(
            probe_id=probe_id,
            gate=gate,
            mutation=mutation,
            control=control,
            mutated=mutated,
            verdict=VERDICT_REFUSED,
            detail=(
                "the mutated gate refused to judge and printed INVALID "
                "(its own vacuity guard fired instead of passing)"
            ),
            exit_code=_gate_io.EXIT_OK,
        )
    if mutated_exit == 0:
        return ProbeOutcome(
            probe_id=probe_id,
            gate=gate,
            mutation=mutation,
            control=control,
            mutated=mutated,
            verdict=VERDICT_DEFEATED,
            detail=(
                "the mutation turned a known-bad input into a green verdict: this gate can be "
                "greened by editing the code/parameters it is built from"
            ),
            exit_code=_gate_io.EXIT_OK,
        )
    return ProbeOutcome(
        probe_id=probe_id,
        gate=gate,
        mutation=mutation,
        control=control,
        mutated=mutated,
        verdict=VERDICT_NOT_DETECTED,
        detail=(
            f"the mutated gate still refused to pass (exit={mutated_exit}) but never said "
            "INVALID: the mutation did not demonstrate anything"
        ),
        exit_code=_gate_io.EXIT_META_NOT_DETECTED,
    )


# ---------------------------------------------------------------------------
# Probe 1 — inject: empty the expectation set
# ---------------------------------------------------------------------------


def probe_inject(source_repo: Path, scratch_root: Path, *, timeout_s: float, keep: bool) -> ProbeOutcome:
    """Empty one case's ``must_be_red`` and require the engine to say ``INVALID``.

    The injection engine is the "gate" here: its job is to refuse to call a case
    a pass when no expectation is declared.  Emptying the tuple is precisely the
    one-line edit that would otherwise turn the whole matrix green.

    Args:
        source_repo: Real repository root.
        scratch_root: Where to clone.
        timeout_s: Hard timeout per run.
        keep: Keep the clone.

    Returns:
        The probe outcome.
    """
    gate = "scripts/inject_counterexample.py"
    clone = _prepare_clone(source_repo, scratch_root, "inject", keep=keep)
    case_id = "ddl-hnsw-deleted-naive"
    # T3-18: the engine refuses to judge without external truth, and the clone
    # carries only ``scripts/`` + ``contracts/`` — no ``_old``.  Left to its own
    # resolution the engine guessed ``<clone>/_old`` inside the scratch directory
    # and every healthy tree reported UNEVALUABLE(41).  Pass the REAL
    # repository's resolved legacy root explicitly (``$E2E_LEGACY_ROOT`` still
    # wins inside ``GatePaths.resolve``, so a broken operator override keeps
    # failing loud — it is never silently swapped for a guessed path).  This is
    # the same pattern probe_oracle has used since it landed.
    argv = [
        "--case",
        case_id,
        "--legacy-root",
        str(_gate_io.GatePaths.resolve(repo_root=source_repo).legacy_root),
    ]

    control = _run(clone, gate, argv, timeout_s=timeout_s)
    control_detected = control.exit_code == 0

    mutation = _replace_once(
        clone / "scripts" / "inject_cases.py",
        "        must_be_red=(\"C7\", \"counts.raw_indexes\"),",
        "        must_be_red=(),",
        label="inject_cases.py: must_be_red=() for case " + case_id,
    )
    mutated = _run(clone, gate, argv, timeout_s=timeout_s)
    return _classify(
        probe_id="inject",
        gate=gate,
        mutation=mutation,
        control=f"unmutated engine --case {case_id}: exit={control.exit_code} :: {control.tail(1)}",
        mutated=f"mutated engine --case {case_id}: exit={mutated.exit_code} :: {mutated.red_lines(2)}",
        control_detected=control_detected,
        mutated_exit=mutated.exit_code,
        mutated_output=mutated.output,
    )


# ---------------------------------------------------------------------------
# Probe 2 — oracle: replace the comparison with the identity
# ---------------------------------------------------------------------------

#: The "always MATCH" patch injected into the cloned ``oracle_recompute.py``.
#: It redefines ``recompute`` (module-level rebinding: the later definition wins)
#: so every face matches by construction — the classic "make the comparison
#: vacuous" greening, and exactly what ``_facts_from_store`` must never be able
#: to do for real.
_IDENTITY_PATCH: Final[str] = '''
# ==== META-GATE MUTATION (S-7 probe "oracle"): comparison -> identity ====
def recompute(contracts, facts):  # noqa: F811 - deliberate override of the gate
    """Always MATCH: the comparison was replaced by the identity (S-7 probe)."""
    print("[oracle] META-MUTATION: comparison replaced by identity (always MATCH)")
    faces = tuple(
        FaceVerdict(
            face=face,
            label=label,
            state="MATCH",
            external=0,
            contracts=0,
            diffs=(),
        )
        for face, label in (
            ("F1", "openapi.paths"),
            ("F2", "ddl.raw_indexes"),
            ("F3", "sse.channels"),
            ("F4", "errors.codes"),
        )
    )
    return OracleVerdict(tier="O-A(legacy)", faces=faces, facts=facts, notes=("meta mutation",))
'''


def probe_oracle(
    source_repo: Path, scratch_root: Path, *, timeout_s: float, keep: bool
) -> ProbeOutcome:
    """Replace the oracle comparison with the identity and check it is caught.

    The known-bad input is the *self-consistent* hnsw deletion (structure, counts,
    ``pg.sql``, ``ddl_objects`` and the toolkit constants all agree with the loss),
    which only the external oracle can catch.  With the comparison replaced by the
    identity the gate prints ``PASS (0)`` — the meta gate must record that as a
    defeat, because a green from this gate would then mean nothing at all.

    Args:
        source_repo: Real repository root.
        scratch_root: Where to clone.
        timeout_s: Hard timeout per run.
        keep: Keep the clone.

    Returns:
        The probe outcome.
    """
    gate = "scripts/oracle_recompute.py"
    clone = _prepare_clone(source_repo, scratch_root, "oracle", keep=keep)
    contracts = clone / "contracts"
    argv = [
        "--oracle",
        "legacy",
        "--contracts",
        str(contracts),
        "--legacy-root",
        str(_gate_io.GatePaths.resolve(repo_root=source_repo).legacy_root),
    ]

    try:
        # The known-bad input must be one the oracle is the *only* witness for:
        # the fully self-consistent hnsw deletion (structure + counts + pg.sql +
        # ddl_objects + toolkit constants).  A mere ``counts.raw_indexes`` edit is
        # invisible to F2 (it compares object *names*), so using it here would mean
        # "there is no red to lose" instead of a real control.
        inject_cases.ddl_hnsw_deleted_consistent(contracts, clone)
        engine.reseal(contracts, clone)
    except (inject_cases.MutationError, engine.CaseError) as error:
        raise ProbeError(f"cannot build the known-bad input: {error}") from error

    control = _run(clone, gate, argv, timeout_s=timeout_s)
    control_detected = control.exit_code == 20

    mutation = _insert_before(
        clone / "scripts" / "oracle_recompute.py",
        'if __name__ == "__main__":  # pragma: no cover - manual invocation',
        _IDENTITY_PATCH,
        label="oracle_recompute.py: recompute() replaced by an always-MATCH identity",
    )
    mutated = _run(clone, gate, argv, timeout_s=timeout_s)
    return _classify(
        probe_id="oracle",
        gate=gate,
        mutation=mutation,
        control=f"unmutated oracle on the self-consistent hnsw deletion: exit={control.exit_code} :: {control.red_lines(2)}",
        mutated=f"identity-comparison oracle on the same input: exit={mutated.exit_code} :: {mutated.red_lines(2)}",
        control_detected=control_detected,
        mutated_exit=mutated.exit_code,
        mutated_output=mutated.output,
    )


# ---------------------------------------------------------------------------
# Probe 3 — control-flow: empty the invariant set
# ---------------------------------------------------------------------------


def probe_control_flow(
    source_repo: Path, scratch_root: Path, *, timeout_s: float, keep: bool
) -> ProbeOutcome:
    """Empty ``INVARIANTS`` and require the checker to say ``INVALID``.

    The known-bad input is the shipped trace directory, which contains six traces
    that each violate exactly one invariant.  Emptying the invariant tuple is the
    edit that would silently make every trace compliant, so the checker must
    refuse instead of reporting "0 violations".

    Args:
        source_repo: Real repository root.
        scratch_root: Where to clone.
        timeout_s: Hard timeout per run.
        keep: Keep the clone.

    Returns:
        The probe outcome.
    """
    gate = "scripts/check_control_flow.py"
    clone = _prepare_clone(source_repo, scratch_root, "control-flow", keep=keep)
    trace_dir = clone / "scripts" / "conformance" / "traces"
    if not trace_dir.is_dir():
        raise ProbeError(f"trace fixtures are missing from the clone: {trace_dir.as_posix()}")
    # ``--require-clean`` is the runtime mode: any violation is a red, which is
    # what "the known-bad input" means for this checker (the shipped fixtures are
    # *declared* red, so conformance mode would legitimately pass on them).
    argv = ["--trace-dir", str(trace_dir), "--require-clean"]

    control = _run(clone, gate, argv, timeout_s=timeout_s)
    control_detected = control.exit_code == 1

    mutation = _replace_regex_once(
        clone / "scripts" / "check_control_flow.py",
        r"INVARIANTS: Final\[tuple\[str, \.\.\.\]\] = \([^)]*\)",
        "INVARIANTS: Final[tuple[str, ...]] = ()",
        label="check_control_flow.py: INVARIANTS emptied",
    )
    mutated = _run(clone, gate, argv, timeout_s=timeout_s)
    return _classify(
        probe_id="control-flow",
        gate=gate,
        mutation=mutation,
        control=f"unmutated checker on the shipped traces: exit={control.exit_code} :: {control.red_lines(2)}",
        mutated=f"empty-invariant checker on the same traces: exit={mutated.exit_code} :: {mutated.red_lines(2)}",
        control_detected=control_detected,
        mutated_exit=mutated.exit_code,
        mutated_output=mutated.output,
    )


# ---------------------------------------------------------------------------
# Probe 4 — frontend-baseline: empty glob judged green
# ---------------------------------------------------------------------------


def probe_frontend_baseline(
    source_repo: Path, scratch_root: Path, *, timeout_s: float, keep: bool
) -> ProbeOutcome:
    """Probe S-1's ``MIN_FILES`` floor ("empty glob ⇒ green" is the bug).

    ``scripts/check_frontend_baseline.py`` is a **T05** deliverable.  When it is
    not on disk the probe reports ``INVALID(ABSENT)`` — absence is never a pass
    (K-11) — and the summary line keeps this class separate from the three probes
    that really executed.  Once T05 lands, the probe runs for real:

    * control: the shipped gate over a tree with **no** e2e files must not pass;
    * mutation: ``MIN_FILES = 6`` -> ``0`` (empty glob judged green) must be
      reported by the meta gate as a defeat.

    Args:
        source_repo: Real repository root.
        scratch_root: Where to clone.
        timeout_s: Hard timeout per run.
        keep: Keep the clone.

    Returns:
        The probe outcome.
    """
    gate = "scripts/check_frontend_baseline.py"
    if not (source_repo / "scripts" / "check_frontend_baseline.py").is_file():
        return _classify(
            probe_id="frontend-baseline",
            gate=gate,
            mutation="(not executed)",
            control="(not executed)",
            mutated="(not executed)",
            control_detected=False,
            mutated_exit=0,
            mutated_output="",
            absent=True,
            absent_reason=(
                "scripts/check_frontend_baseline.py is not on disk (owner=T05); per K-11 an "
                "absent gate is INVALID, and the S-1 probe must be re-run once T05 lands"
            ),
        )

    clone = _prepare_clone(source_repo, scratch_root, "fbaseline", keep=keep)
    # A tree with no e2e files at all: the vacuous input S-1 exists to reject.
    (clone / "packages" / "e2e").mkdir(parents=True, exist_ok=True)
    argv = ["--repo-root", str(clone)]

    control = _run(clone, gate, argv, timeout_s=timeout_s)
    control_detected = control.exit_code != 0

    try:
        mutation = _replace_once(
            clone / "scripts" / "check_frontend_baseline.py",
            "MIN_FILES = 6",
            "MIN_FILES = 0",
            label="check_frontend_baseline.py: MIN_FILES 6 -> 0 (empty glob judged green)",
        )
    except ProbeError as error:
        if not control_detected:
            return _classify(
                probe_id="frontend-baseline",
                gate=gate,
                mutation="MIN_FILES 6 -> 0",
                control=f"unmutated S-1 gate on an empty tree: exit={control.exit_code}",
                mutated="(not executed)",
                control_detected=False,
                mutated_exit=-1,
                mutated_output="",
            )
        return ProbeOutcome(
            probe_id="frontend-baseline",
            gate=gate,
            mutation="MIN_FILES 6 -> 0",
            control=f"unmutated S-1 gate on an empty tree: exit={control.exit_code}",
            mutated="(mutation anchor not found)",
            verdict=VERDICT_UNEVALUABLE,
            detail=str(error),
            exit_code=_gate_io.EXIT_META_UNEVALUABLE,
        )

    mutated = _run(clone, gate, argv, timeout_s=timeout_s)
    return _classify(
        probe_id="frontend-baseline",
        gate=gate,
        mutation=mutation,
        control=f"unmutated S-1 gate on an empty tree: exit={control.exit_code} :: {control.red_lines(2)}",
        mutated=f"MIN_FILES=0 gate on the same tree: exit={mutated.exit_code} :: {mutated.red_lines(2)}",
        control_detected=control_detected,
        mutated_exit=mutated.exit_code,
        mutated_output=mutated.output,
    )


#: The probe table (id -> callable), in report order.
PROBES: Final[tuple[tuple[str, Callable[..., ProbeOutcome]], ...]] = (
    ("inject", probe_inject),
    ("oracle", probe_oracle),
    ("control-flow", probe_control_flow),
    ("frontend-baseline", probe_frontend_baseline),
)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render(outcome: ProbeOutcome) -> None:
    """Print one probe as evidence lines.

    Args:
        outcome: The probe outcome.
    """
    _gate_io.log(TAG, f"PROBE {outcome.probe_id}  gate={outcome.gate}")
    _gate_io.log(TAG, f"  mutation: {outcome.mutation}")
    _gate_io.log(TAG, f"  control : {outcome.control}")
    _gate_io.log(TAG, f"  mutated : {outcome.mutated}")
    _gate_io.log(TAG, f"  VERDICT : {outcome.verdict} — {outcome.detail}")


def summarize(outcomes: Sequence[ProbeOutcome], *, strict: bool) -> tuple[int, dict[str, int]]:
    """Fold probe verdicts into one exit code.

    Args:
        outcomes: All probe outcomes.
        strict: When true an ``INVALID(ABSENT)`` verdict is a failure (``40``):
            it is weaker evidence than a probe that actually ran.

    Returns:
        ``(exit_code, counts_by_verdict)``.
    """
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.verdict] = counts.get(outcome.verdict, 0) + 1

    codes = [outcome.exit_code for outcome in outcomes]
    if _gate_io.EXIT_META_UNEVALUABLE in codes:
        return _gate_io.EXIT_META_UNEVALUABLE, counts
    if _gate_io.EXIT_META_NOT_DETECTED in codes:
        return _gate_io.EXIT_META_NOT_DETECTED, counts
    if strict and counts.get(VERDICT_ABSENT):
        return _gate_io.EXIT_META_NOT_DETECTED, counts
    return _gate_io.EXIT_OK, counts


# ---------------------------------------------------------------------------
# Self-test — every branch of the classifier, no cloning
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Exercise every branch of :func:`_classify` plus the summary fold.

    Five classifier branches (absent / control-miss / refused / defeated /
    not-detected) and two summary behaviours (a NOT-DETECTED probe fails with
    ``40``; ``--strict`` turns ABSENT into ``40`` while the default does not).

    Returns:
        ``0`` when every probe behaves, ``9`` otherwise.
    """
    checks: list[tuple[str, bool]] = []

    def expect(label: str, outcome: ProbeOutcome, verdict: str, code: int) -> None:
        checks.append(
            (
                f"{label} -> {outcome.verdict}/{outcome.exit_code} (want {verdict}/{code})",
                outcome.verdict == verdict and outcome.exit_code == code,
            )
        )

    base: dict[str, Any] = {
        "probe_id": "self-test",
        "gate": "scripts/x.py",
        "mutation": "m",
        "control": "c",
        "mutated": "u",
    }
    expect(
        "absent gate",
        _classify(**base, control_detected=False, mutated_exit=0, mutated_output="", absent=True),
        VERDICT_ABSENT,
        _gate_io.EXIT_OK,
    )
    expect(
        "no red to lose",
        _classify(**base, control_detected=False, mutated_exit=1, mutated_output="FAIL"),
        VERDICT_UNEVALUABLE,
        _gate_io.EXIT_META_UNEVALUABLE,
    )
    expect(
        "mutated gate refuses",
        _classify(**base, control_detected=True, mutated_exit=12, mutated_output="VERDICT: INVALID"),
        VERDICT_REFUSED,
        _gate_io.EXIT_OK,
    )
    expect(
        "mutated gate is green",
        _classify(**base, control_detected=True, mutated_exit=0, mutated_output="VERDICT: PASS"),
        VERDICT_DEFEATED,
        _gate_io.EXIT_OK,
    )
    expect(
        "mutation ineffective",
        _classify(**base, control_detected=True, mutated_exit=1, mutated_output="VERDICT: FAIL"),
        VERDICT_NOT_DETECTED,
        _gate_io.EXIT_META_NOT_DETECTED,
    )

    defeated = _classify(**base, control_detected=True, mutated_exit=0, mutated_output="PASS")
    not_detected = _classify(**base, control_detected=True, mutated_exit=1, mutated_output="FAIL")
    absent = _classify(**base, control_detected=False, mutated_exit=0, mutated_output="", absent=True)

    code, counts = summarize([defeated, defeated], strict=False)
    checks.append((f"summary all-INVALID -> {code}/0", code == _gate_io.EXIT_OK and counts.get(VERDICT_DEFEATED) == 2))
    code, _ = summarize([defeated, not_detected], strict=False)
    checks.append((f"summary not-detected -> {code}/40", code == _gate_io.EXIT_META_NOT_DETECTED))
    code, _ = summarize([defeated, absent], strict=False)
    checks.append((f"summary absent (default) -> {code}/0", code == _gate_io.EXIT_OK))
    code, _ = summarize([defeated, absent], strict=True)
    checks.append((f"summary absent (--strict) -> {code}/40", code == _gate_io.EXIT_META_NOT_DETECTED))

    failures = 0
    _gate_io.log(TAG, "self-test: classifier branches + summary fold")
    for label, ok in checks:
        _gate_io.log(TAG, f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failures += 1
    _gate_io.log(TAG, f"self-test: {len(checks) - failures}/{len(checks)} passed")
    if failures:
        _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({failures} probe(s))")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, "SELFTEST VERDICT: PASS (every verdict class is reachable for the right input)")
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
        prog="meta_gate.py",
        description=(
            "S-7 meta gate: mutate each gate into 'always green' inside a clone and "
            "check that the mutation is detected (INVALID) instead of silently passing."
        ),
    )
    parser.add_argument("--probe", metavar="ID", action="append", default=None, help="run one probe (repeatable)")
    parser.add_argument("--strict", action="store_true", help="treat INVALID(ABSENT) as a failure (exit 40)")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--self-test", action="store_true", help="unit-test the classifier (exit 9 on failure)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch clones")
    parser.add_argument("--verbose", action="store_true", help="echo extra detail")
    parser.add_argument("--scratch-root", type=Path, default=None, metavar="DIR", help="where to create clones")
    parser.add_argument("--timeout", type=float, default=engine.DEFAULT_TIMEOUT_S, help="per-run timeout in seconds")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``40`` / ``41`` / ``2`` / ``9`` (design §3.3).
    """
    parser = _build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    if arguments.self_test:
        return _self_test()

    repo_root = _SCRIPTS_DIR.parent
    selected = list(PROBES)
    if arguments.probe:
        known = {probe_id for probe_id, _ in PROBES}
        unknown = [name for name in arguments.probe if name not in known]
        if unknown:
            _gate_io.log(TAG, f"ERROR: unknown probe(s) {unknown}; known={sorted(known)}")
            return _gate_io.EXIT_USAGE
        selected = [(probe_id, func) for probe_id, func in PROBES if probe_id in set(arguments.probe)]

    if not selected:  # pragma: no cover - argparse makes this unreachable
        _gate_io.log(TAG, "INVALID: empty probe selection (K-11)")
        return _gate_io.EXIT_META_UNEVALUABLE

    scratch_root = (
        Path(arguments.scratch_root).expanduser().resolve()
        if arguments.scratch_root
        else Path(tempfile.mkdtemp(prefix="wbtime-meta-root-"))
    )
    scratch_root.mkdir(parents=True, exist_ok=True)

    _gate_io.log(
        TAG,
        f"meta gate (S-7): {len(selected)} probe(s)  repo={repo_root.as_posix()}  "
        f"scratch={scratch_root.as_posix()}  at {_gate_io.utc_now_iso()}",
    )

    outcomes: list[ProbeOutcome] = []
    try:
        for probe_id, function in selected:
            try:
                outcome = function(
                    repo_root,
                    scratch_root,
                    timeout_s=float(arguments.timeout),
                    keep=bool(arguments.keep),
                )
            except ProbeError as error:
                outcome = ProbeOutcome(
                    probe_id=probe_id,
                    gate="(see detail)",
                    mutation="(not executed)",
                    control="(not executed)",
                    mutated="(not executed)",
                    verdict=VERDICT_UNEVALUABLE,
                    detail=str(error),
                    exit_code=_gate_io.EXIT_META_UNEVALUABLE,
                )
            outcomes.append(outcome)
            if not arguments.json:
                render(outcome)
    finally:
        if not arguments.keep:
            shutil.rmtree(scratch_root, ignore_errors=True)

    exit_code, counts = summarize(outcomes, strict=bool(arguments.strict))
    executed = sum(
        count for verdict, count in counts.items() if verdict in (VERDICT_DEFEATED, VERDICT_REFUSED)
    )
    absent = counts.get(VERDICT_ABSENT, 0)

    if arguments.json:
        print(
            json.dumps(
                {
                    "generated_at": _gate_io.utc_now_iso(),
                    "repo_root": repo_root.as_posix(),
                    "strict": bool(arguments.strict),
                    "probes": [outcome.as_dict() for outcome in outcomes],
                    "summary": {
                        "total": len(outcomes),
                        "executed_invalid": executed,
                        "absent_invalid": absent,
                        "not_detected": counts.get(VERDICT_NOT_DETECTED, 0),
                        "unevaluable": counts.get(VERDICT_UNEVALUABLE, 0),
                        "exit_code": exit_code,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    _gate_io.log(
        TAG,
        f"SUMMARY: {executed}/{len(outcomes)} probe(s) reported INVALID(executed); "
        f"{absent} INVALID(ABSENT); {counts.get(VERDICT_NOT_DETECTED, 0)} NOT-DETECTED; "
        f"{counts.get(VERDICT_UNEVALUABLE, 0)} UNEVALUABLE",
    )
    if exit_code == _gate_io.EXIT_OK:
        _gate_io.log(
            TAG,
            "VERDICT: PASS (0) — every gate under test can be greened by editing what it is "
            "built from, and the meta gate detects it",
        )
    elif exit_code == _gate_io.EXIT_META_NOT_DETECTED:
        _gate_io.log(TAG, "VERDICT: NOT-DETECTED (40) — a mutation left the gate's behaviour unchanged, or --strict rejected an ABSENT gate")
    else:
        _gate_io.log(TAG, "VERDICT: UNEVALUABLE (41) — a probe could not be evaluated at all")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
