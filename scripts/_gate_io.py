"""Shared primitives for the V0.0.2 gates — the single shared layer.

Scope (hard boundary)
---------------------
This module holds **primitives only**:

* the exit-code table (§3.3 of the design doc), as constants;
* :class:`Diff`, the one record shape every gate uses to report a difference;
* :class:`GatePaths`, path resolution (repo / contracts / legacy / workdir);
* :func:`load_json` / :func:`load_text`, encoding-safe artifact reading;
* :func:`iter_sql_statements`, the quote- and comment-aware ``';'`` splitter;
* :func:`set_diff_report`, plain set arithmetic rendered as :class:`Diff`;
* :func:`log`, the single-line ``[tag] message`` writer (K-7);
* :func:`utc_now_iso`, the ledger timestamp (K-9).

It deliberately carries **no judging logic** — no parity rules, no coverage
rules, no "is this red cause legal" table. Every gate must own its own criteria,
so a criterion can never be weakened from one shared place.

Reference: ``docs/V1.0/V0.0.2-oracle自证与假绿反例/02-施工/README.md`` §3.2
(signatures) and §3.3 (exit-code table).

Import note
-----------
``scripts/<gate>.py`` may ``import _gate_io`` directly, because running
``python scripts/<gate>.py`` puts ``scripts/`` on ``sys.path[0]``. Modules that
live one level deeper (``scripts/oracle/*.py``, ``scripts/selfproof/*.py``)
must add the parent directory first::

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import _gate_io

Python: standard library only (no third-party imports, no PyYAML dependency).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

__all__ = [
    # exit codes (§3.3)
    "EXIT_OK",
    "EXIT_VIOLATION",
    "EXIT_USAGE",
    "EXIT_SELFTEST",
    "EXIT_FAKE_GREEN",
    "EXIT_FALSE_REFUTATION",
    "EXIT_CASE_UNEVALUABLE",
    "EXIT_ORACLE_MISMATCH",
    "EXIT_ORACLE_UNAVAILABLE",
    "EXIT_ARTIFACT_LOAD",
    "EXIT_RUNNER_NOT_GREEN",
    "EXIT_RUNNER_BAD_CAUSE",
    "EXIT_RUNNER_NONCE",
    "EXIT_RUNNER_COUNT",
    "EXIT_RUNNER_PRECONDITION",
    "EXIT_PORT_STILL_OPEN",
    "EXIT_READONLY_DIRTY",
    "EXIT_META_NOT_DETECTED",
    "EXIT_META_UNEVALUABLE",
    "EXIT_LAUNCH_TIMEOUT",
    "EXIT_PORT_BUSY",
    "EXIT_LAUNCH_READONLY_DIRTY",
    "EXIT_CODE_MEANINGS",
    # primitives
    "Diff",
    "GatePaths",
    "GateIOError",
    "load_json",
    "load_text",
    "iter_sql_statements",
    "set_diff_report",
    "log",
    "utc_now_iso",
    "LEGACY_ROOT_ENV",
]

# ---------------------------------------------------------------------------
# Exit codes — §3.3 「退出码总表」
# ---------------------------------------------------------------------------
#: PASS.
EXIT_OK: Final[int] = 0
#: Gate red: integrity / difference / violation (existing meaning, reused).
EXIT_VIOLATION: Final[int] = 1
#: Usage error (never used for "semantic red" in the new gates).
EXIT_USAGE: Final[int] = 2
#: ``--self-test`` failed. **All new scripts use 9**, never the legacy 4.
EXIT_SELFTEST: Final[int] = 9

#: ``inject_counterexample.py``: the red stayed green (that is the bug itself).
EXIT_FAKE_GREEN: Final[int] = 10
#: ``inject_counterexample.py``: red, but for the wrong reason (伪反证).
EXIT_FALSE_REFUTATION: Final[int] = 11
#: ``inject_counterexample.py``: case not evaluable (clone / load failure).
EXIT_CASE_UNEVALUABLE: Final[int] = 12

#: ``oracle_recompute.py``: the artifacts disagree with the external oracle.
EXIT_ORACLE_MISMATCH: Final[int] = 20
#: ``oracle_recompute.py``: oracle unavailable (degraded → snapshot, or BLOCKED).
EXIT_ORACLE_UNAVAILABLE: Final[int] = 21
#: ``oracle_recompute.py``: artifact loading failed.
EXIT_ARTIFACT_LOAD: Final[int] = 22

#: Node runner: cases not all green.
EXIT_RUNNER_NOT_GREEN: Final[int] = 30
#: Node runner: red cause is not in the allowed set (``ETIMEDOUT`` / assertion).
EXIT_RUNNER_BAD_CAUSE: Final[int] = 31
#: Node runner: ``X-E2E-Nonce`` absent or wrong on some response.
EXIT_RUNNER_NONCE: Final[int] = 32
#: Node runner: executed-count mismatch, or ``skip`` / ``only`` / ``todo`` used.
EXIT_RUNNER_COUNT: Final[int] = 33
#: Node runner: precondition unavailable (backend never came up, etc.).
EXIT_RUNNER_PRECONDITION: Final[int] = 34

#: ``run_selfproof.py``: port still open after kill (timeout).
EXIT_PORT_STILL_OPEN: Final[int] = 35
#: ``run_selfproof.py``: the read-only tree was written (incl. ``__pycache__``).
EXIT_READONLY_DIRTY: Final[int] = 36

#: ``meta_gate.py``: a gate failed to notice it had been mutated into green.
EXIT_META_NOT_DETECTED: Final[int] = 40
#: ``meta_gate.py``: probe not evaluable.
EXIT_META_UNEVALUABLE: Final[int] = 41

#: Launcher: backend did not answer ``/health`` within the timeout.
EXIT_LAUNCH_TIMEOUT: Final[int] = 51
#: Launcher: port already taken.
EXIT_PORT_BUSY: Final[int] = 52
#: Launcher: the read-only tree was written while booting (G-4).
EXIT_LAUNCH_READONLY_DIRTY: Final[int] = 53

#: Human-readable meaning per code, so a gate can map a code back to prose.
EXIT_CODE_MEANINGS: Final[dict[int, str]] = {
    EXIT_OK: "PASS",
    EXIT_VIOLATION: "gate red (integrity / difference / violation)",
    EXIT_USAGE: "usage error",
    EXIT_SELFTEST: "--self-test failed",
    EXIT_FAKE_GREEN: "fake green: the injected red did not turn red",
    EXIT_FALSE_REFUTATION: "false refutation: red, but the red cause is wrong",
    EXIT_CASE_UNEVALUABLE: "injection case not evaluable (clone / load failure)",
    EXIT_ORACLE_MISMATCH: "artifacts disagree with the external oracle",
    EXIT_ORACLE_UNAVAILABLE: "external oracle unavailable (degraded / BLOCKED)",
    EXIT_ARTIFACT_LOAD: "artifact loading failed",
    EXIT_RUNNER_NOT_GREEN: "e2e cases not all green",
    EXIT_RUNNER_BAD_CAUSE: "e2e red cause not in the allowed set",
    EXIT_RUNNER_NONCE: "X-E2E-Nonce absent or mismatched",
    EXIT_RUNNER_COUNT: "case count mismatch or skip/only/todo used",
    EXIT_RUNNER_PRECONDITION: "e2e precondition unavailable",
    EXIT_PORT_STILL_OPEN: "port still open after kill",
    EXIT_READONLY_DIRTY: "read-only tree was written",
    EXIT_META_NOT_DETECTED: "meta gate: mutation into green went unnoticed",
    EXIT_META_UNEVALUABLE: "meta gate: probe not evaluable",
    EXIT_LAUNCH_TIMEOUT: "backend launch timeout",
    EXIT_PORT_BUSY: "port already in use",
    EXIT_LAUNCH_READONLY_DIRTY: "read-only tree written during launch",
}

#: Environment variable holding the read-only legacy repo root (G-1).
LEGACY_ROOT_ENV: Final[str] = "E2E_LEGACY_ROOT"

#: Name of the in-repo legacy archive (``<repo>/_old``), the V0.1.0+ convention.
LEGACY_INREPO_DIRNAME: Final[str] = "_old"

#: Name of the sibling legacy archive (``<repo>/../WBTimeAI_old``), the older layout.
LEGACY_SIBLING_DIRNAME: Final[str] = "WBTimeAI_old"

#: Everything K-7 wants collapsed into one line.
_LINE_BREAK_RE: Final[re.Pattern[str]] = re.compile(r"\r\n|\r|\n")


class GateIOError(RuntimeError):
    """Raised when an artifact cannot be read or parsed.

    Gates translate this into their own "load failed" exit code
    (``EXIT_ARTIFACT_LOAD`` / ``EXIT_CASE_UNEVALUABLE`` / ``EXIT_USAGE``); it is
    never swallowed silently.
    """


@dataclass(frozen=True)
class Diff:
    """One difference between two artifact faces.

    Attributes:
        kind: What kind of difference this is. Gates use their own vocabulary
            (``"missing"`` / ``"extra"`` / ``"type"`` / ``"count"`` ...); the
            shared layer only fixes the record shape, not the vocabulary.
        subject: The thing being compared (a table, a column, a path, a
            channel name ...). Never empty.
        left: How the left/frozen side sees the subject.
        right: How the right/candidate side sees the subject.
    """

    kind: str
    subject: str
    left: str
    right: str

    def render(self) -> str:
        """Render as one ASCII-preferring line.

        Returns:
            ``"<kind>: <subject> (left=<left>, right=<right>)"``.
        """
        return f"{self.kind}: {self.subject} (left={self.left}, right={self.right})"

    def to_dict(self) -> dict[str, str]:
        """Return the record as a plain dict (for ``--json`` output)."""
        return {
            "kind": self.kind,
            "subject": self.subject,
            "left": self.left,
            "right": self.right,
        }

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.render()


@dataclass(frozen=True)
class GatePaths:
    """The four roots every gate needs, resolved once.

    Attributes:
        repo_root: Repository root (``D:/WBT/WBTimeAI``).
        contracts_dir: Frozen contract artifacts (``<repo>/contracts``).
        legacy_root: Read-only legacy repository (``D:/WBT/WBTimeAI_old``);
            never written by any gate.
        workdir: Scratch / evidence directory (``<repo>/output/e2e``), already
            outside both ``contracts/`` and ``legacy_root`` (G-4).
    """

    repo_root: Path
    contracts_dir: Path
    legacy_root: Path
    workdir: Path

    @classmethod
    def resolve(
        cls,
        *,
        repo_root: Path | str | None = None,
        contracts_dir: Path | str | None = None,
        legacy_root: Path | str | None = None,
        workdir: Path | str | None = None,
    ) -> GatePaths:
        """Build a :class:`GatePaths`, defaulting every unspecified root.

        Args:
            repo_root: Repository root; defaults to the parent of ``scripts/``.
            contracts_dir: Overrides ``<repo>/contracts`` (used by the injection
                gates, which point at a temporary clone).
            legacy_root: Overrides the read-only legacy root. Resolution order
                when omitted: ``$E2E_LEGACY_ROOT``, then the sibling directory
                ``<repo>/../WBTimeAI_old``, then the hard-coded
                ``D:/WBT/WBTimeAI_old``.
            workdir: Overrides ``<repo>/output/e2e``.

        Returns:
            A frozen :class:`GatePaths` with absolute paths.
        """
        root = (
            Path(repo_root).expanduser().resolve()
            if repo_root is not None
            else Path(__file__).resolve().parents[1]
        )
        contracts = (
            Path(contracts_dir).expanduser().resolve()
            if contracts_dir is not None
            else root / "contracts"
        )
        legacy = (
            Path(legacy_root).expanduser().resolve()
            if legacy_root is not None
            else _default_legacy_root(root)
        )
        work = (
            Path(workdir).expanduser().resolve()
            if workdir is not None
            else root / "output" / "e2e"
        )
        return cls(repo_root=root, contracts_dir=contracts, legacy_root=legacy, workdir=work)

    def contract_file(self, relative: str) -> Path:
        """Return ``<contracts_dir>/<relative>`` without touching the filesystem.

        Args:
            relative: POSIX-style path relative to ``contracts/``.

        Returns:
            The joined path.
        """
        return self.contracts_dir / _posix_to_native(relative)

    def as_dict(self) -> dict[str, str]:
        """Return the roots as strings (for evidence lines)."""
        return {
            "repo_root": self.repo_root.as_posix(),
            "contracts_dir": self.contracts_dir.as_posix(),
            "legacy_root": self.legacy_root.as_posix(),
            "workdir": self.workdir.as_posix(),
        }


def _posix_to_native(relative: str) -> Path:
    """Convert a POSIX-style relative path into a native :class:`Path`.

    Args:
        relative: Path such as ``"schema.v0018.pg.normalized.json"`` or
            ``"sse/channels.json"``.

    Returns:
        The native path.
    """
    return Path(*relative.split("/")) if "/" in relative else Path(relative)


def _default_legacy_root(repo_root: Path) -> Path:
    """Resolve the read-only legacy root when the caller did not pass one.

    Candidates, in order:

    1. ``$E2E_LEGACY_ROOT`` — explicit operator override, always wins.
    2. ``<repo>/_old`` — the in-repo archive convention (V0.1.0+).
    3. ``<repo>/../WBTimeAI_old`` — the sibling archive (legacy layout).
    4. ``<repo>/_old`` — the *expected* location, returned even when absent.

    Args:
        repo_root: Repository root, used to look for the archive.

    Returns:
        The first existing candidate; otherwise ``<repo>/_old`` so the caller's
        error message names a path the operator can actually act on.

    Note:
        Until 2026-10-21 this function fell back to a hard-coded
        ``D:/WBT/WBTimeAI_old``.  On Linux that produced a failure message naming
        a Windows path that could never exist there, which reads like a config
        error while the real cause is "the archive lives somewhere else on this
        host".  Two gates (``check_extension_point_signatures`` and
        ``check_frontend_diff``) inherited the same defect and reported
        ``0/9 points`` / ``common=0`` on an otherwise healthy tree — see
        ``V0.1.0/03-台账/风险与决策.md`` D-10 and D-12.  A path that is *guessed*
        must never masquerade as a path that was *found*.
    """
    from_env = os.environ.get(LEGACY_ROOT_ENV, "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()
    for candidate in (
        repo_root / LEGACY_INREPO_DIRNAME,
        repo_root.parent / LEGACY_SIBLING_DIRNAME,
    ):
        if candidate.is_dir():
            return candidate.resolve()
    return (repo_root / LEGACY_INREPO_DIRNAME).resolve()


def load_json(path: Path) -> Any:
    """Read a JSON artifact.

    Args:
        path: File to read (UTF-8, a leading BOM is tolerated).

    Returns:
        The decoded document.

    Raises:
        GateIOError: The file is missing, unreadable, or not valid JSON.
    """
    text = load_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise GateIOError(f"invalid JSON in {path.as_posix()}: {error}") from error


def load_text(path: Path) -> str:
    """Read a UTF-8 text artifact.

    Args:
        path: File to read. A UTF-8 BOM is stripped so byte-identical artifacts
            stay comparable across editors.

    Returns:
        The decoded text.

    Raises:
        GateIOError: The file is missing or not decodable as UTF-8.
    """
    target = Path(path)
    if not target.is_file():
        raise GateIOError(f"missing file: {target.as_posix()}")
    try:
        return target.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise GateIOError(f"cannot read {target.as_posix()}: {error}") from error
    except UnicodeDecodeError as error:
        raise GateIOError(f"{target.as_posix()} is not valid UTF-8: {error}") from error


def iter_sql_statements(text: str) -> Iterator[str]:
    """Split SQL text into statements at top-level ``';'``.

    Comments are dropped before splitting, and ``';'`` inside string literals or
    dollar-quoted bodies does **not** split, so a comment like
    ``-- 索引一律 FOLLOW 所属表；`` never produces a fragment.

    Rules (deliberate, documented so gates can rely on them):

    * line comments ``-- ...`` and block comments ``/* ... */`` are removed;
    * ``'...'``, ``"..."`` and ``$tag$ ... $tag$`` bodies are copied verbatim;
    * a statement is emitted when a top-level ``';'`` closes it; the emitted
      text **excludes** the terminating ``';'`` and is whitespace-stripped;
    * comment-only and empty fragments are never emitted;
    * a trailing statement without a closing ``';'`` **is** emitted (a silently
      dropped statement would be a silent green — K-11);
    * dialect-level constructs such as SQLite ``CREATE TRIGGER ... BEGIN ... END;``
      are *not* merged: this splitter is quote/comment aware only. A gate that
      needs statement-level grammar must tokenize itself.

    Args:
        text: Raw SQL file content.

    Yields:
        One statement per top-level ``';'``, in file order.
    """
    buffer: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]

        if char == "-" and text.startswith("--", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            buffer.append(" ")
            continue

        if char == "/" and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            buffer.append(" ")
            continue

        if char in ("'", '"'):
            start = index
            index = _skip_quoted(text, index, char)
            buffer.append(text[start:index])
            continue

        if char == "$":
            end = _dollar_quote_end(text, index)
            if end is not None:
                buffer.append(text[index:end])
                index = end
                continue

        if char == ";":
            statement = "".join(buffer).strip()
            buffer.clear()
            index += 1
            if statement:
                yield statement
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        yield tail


def _skip_quoted(text: str, index: int, quote: str) -> int:
    """Advance past a quoted body, honouring doubled-quote escapes.

    Args:
        text: Full SQL text.
        index: Position of the opening quote.
        quote: The quote character (``'`` or ``"``).

    Returns:
        Index one past the closing quote (or ``len(text)`` when unterminated).
    """
    length = len(text)
    position = index + 1
    while position < length:
        if text[position] == quote:
            if position + 1 < length and text[position + 1] == quote:
                position += 2
                continue
            return position + 1
        position += 1
    return length


def _dollar_quote_end(text: str, index: int) -> int | None:
    """Return the end of a ``$tag$ ... $tag$`` body starting at ``index``.

    Args:
        text: Full SQL text.
        index: Position of a ``$`` character.

    Returns:
        Index one past the closing tag, or ``None`` when this ``$`` does not open
        a dollar-quoted body (e.g. a ``$1`` placeholder).
    """
    tag_end = text.find("$", index + 1)
    if tag_end == -1:
        return None
    tag = text[index : tag_end + 1]
    if not re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", tag):
        return None
    closing = text.find(tag, tag_end + 1)
    if closing == -1:
        return None
    return closing + len(tag)


def set_diff_report(left: set[str], right: set[str]) -> list[Diff]:
    """Render the symmetric difference of two name sets as :class:`Diff` records.

    Args:
        left: Names on the left (frozen) side.
        right: Names on the right (candidate) side.

    Returns:
        Sorted diffs: every ``left - right`` as ``kind="missing"`` (present on the
        left, absent on the right), then every ``right - left`` as
        ``kind="extra"``. Ordering is deterministic so evidence diffs are stable.
    """
    missing = sorted(set(left) - set(right))
    extra = sorted(set(right) - set(left))
    report: list[Diff] = [
        Diff(kind="missing", subject=subject, left="present", right="absent")
        for subject in missing
    ]
    report.extend(
        Diff(kind="extra", subject=subject, left="absent", right="present")
        for subject in extra
    )
    return report


def log(tag: str, message: str) -> None:
    """Write one ``[tag] message`` line to stdout (K-7).

    The line is always single: embedded newlines become ``" | "``. On a console
    whose code page cannot represent the text (Windows CP936/CP1252 traps), the
    write falls back to an ASCII ``backslashreplace`` rendering instead of
    raising :class:`UnicodeEncodeError` — the same reason ``run.py`` is ASCII-first.

    Args:
        tag: Short ASCII tag, one of ``gate`` / ``parity`` / ``openapi`` /
            ``bucket3`` / ``oracle`` / ``inject`` / ``meta`` / ``flow`` /
            ``fbaseline`` / ``selfproof`` / ``e2e``.
        message: Message body; may contain non-ASCII text.
    """
    flat = _LINE_BREAK_RE.sub(" | ", str(message))
    line = f"[{tag}] {flat}"
    stream = sys.stdout
    if stream is None:  # pragma: no cover - pythonw / detached stdout
        return
    try:
        stream.write(line + "\n")
        stream.flush()
    except UnicodeEncodeError:
        encoded = line.encode("ascii", "backslashreplace").decode("ascii")
        stream.write(encoded + "\n")
        stream.flush()


def utc_now_iso() -> str:
    """Return the current UTC instant as ``YYYY-MM-DDTHH:MM:SSZ`` (K-9).

    Returns:
        A second-resolution UTC timestamp with a literal ``Z`` suffix.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    """Print the exit-code table (``python scripts/_gate_io.py``).

    Exists so a reviewer can read the numbers without opening the design doc.
    It is not a gate: it asserts nothing and always returns ``0``.

    Args:
        argv: Arguments without program name. Any argument is a usage error.

    Returns:
        ``0`` on success, ``2`` for an unexpected argument.
    """
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments:
        log("gate", f"ERROR: _gate_io.py takes no arguments (got {arguments!r})")
        return EXIT_USAGE
    log("gate", f"exit-code table (V0.0.2, {utc_now_iso()})")
    for code in sorted(EXIT_CODE_MEANINGS):
        log("gate", f"  {code:>3}  {EXIT_CODE_MEANINGS[code]}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - manual inspection aid
    raise SystemExit(main())
