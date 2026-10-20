"""T05 / S-6 — orchestrate the self-proof: forward → kill → reverse.

What one run proves, in order
-----------------------------
1. **the artifacts are untouched**: a snapshot of the read-only legacy tree is taken
   before anything starts and compared afterwards (three subtrees, size + mtime_ns,
   plus a ``find -newermt`` equivalent over the whole tree);
2. **the response really came from our process**: the runner generates the nonce,
   injects it into the child's environment only, and the attestation reports the
   same nonce plus a pid that is the spawned process or its direct child (a ug/venv
   ``python.exe`` redirector inserts one process — measured, recorded, not hidden);
3. **a real write happened**: ``count(*) from session`` grows by exactly 1 because
   the login case registers a user (裁定 D-3: the bootstrap superuser is not usable
   in this database);
4. **the four DoD#4 cases are green and really executed**: ``node --test`` runs them
   against the live port, and the TAP summary is re-checked out-of-process by
   ``lib/counts.mjs`` (S-5: ``tests/pass/fail/skipped/todo`` exactly as declared);
5. **the reverse leg is red for a legal reason**: after SIGTERM the same port must
   answer ``ECONNREFUSED`` / ``ENOTFOUND``; ``ETIMEDOUT`` or "the request succeeded"
   is 伪反证 and exits 31 (``lib/errors.mjs``).

Evidence lands in ``03-台账/真后端自证-原始输出.md`` — **``*.log`` is git-ignored**,
so raw output is embedded in markdown (K-8), never written as a log file.

Exit codes (§3.3; the launcher's and the runner's numbers pass through)::

    0   forward 4/4 green, reverse red for a legal reason, read-only tree clean
    35  the port was still open after the kill
    36  the read-only tree was written (incl. ``__pycache__``)
    30..34   node runner (not green / bad red cause / nonce / count / precondition)
    51  the backend could not be started (or the G-x preconditions fail => BLOCKED)
    52  the port was busy
    2   usage error

Python: standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Sequence

sys.dont_write_bytecode = True

_SELF_DIR: Final[Path] = Path(__file__).resolve().parent
_SCRIPTS_DIR: Final[Path] = _SELF_DIR.parent
_REPO_ROOT: Final[Path] = _SCRIPTS_DIR.parent
for candidate in (str(_SCRIPTS_DIR), str(_SELF_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _gate_io  # noqa: E402  (shared primitives only)
import legacy_backend_launcher as launcher  # noqa: E402  (same directory, deliberate)

__all__ = ["TAG", "ReadonlyGuard", "SelfProofRun", "main"]

#: Log tag (K-7).
TAG: Final[str] = "selfproof"

#: Forward leg: exactly the four DoD#4 cases (the reverse leg lives elsewhere so a
#: zero-test file cannot inflate the ``node --test`` count).
FORWARD_GLOB: Final[str] = "packages/e2e/tests/e2e/**/*.test.mjs"

#: Reverse leg: one file, one case.
REVERSE_GLOB: Final[str] = "packages/e2e/tests/reverse/**/*.test.mjs"

#: The out-of-process S-5 re-check (reuses ``lib/counts.mjs``; no second definition).
COUNT_CHECK_SCRIPT: Final[str] = """
import { readFileSync } from 'node:fs';
const modulePath = process.env.E2E_COUNTS_MODULE;
const tapPath = process.env.E2E_TAP_FILE;
const expected = Number(process.env.E2E_EXPECTED_CASES);
const counts = await import(modulePath);
try {
  const summary = counts.parseTapSummary(readFileSync(tapPath, 'utf8'));
  counts.assertSummary(summary, { expected });
  process.stdout.write(`[e2e] count ok ${counts.formatSummary(summary)}\\n`);
} catch (error) {
  process.stdout.write(`[e2e] count FAIL ${error.name}: ${error.message}\\n`);
  process.exit(error.exitCode ?? 33);
}
"""

#: Subtrees snapshotted before/after (§11.6: the whole tree breaks the time budget).
READONLY_SUBTREES: Final[tuple[str, ...]] = (
    "migrations",
    "apps/api/src/wbtime_ai_api",
    "packages/core/src/wbtime_ai_core",
)

#: Directories never considered "writes to the read-only tree".
WALK_EXCLUDES: Final[frozenset[str]] = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".bt_runtime_build", ".mypy_cache", ".pytest_cache"}
)

#: Where the evidence markdown goes (docs is a separate repository).
EVIDENCE_RELATIVE: Final[str] = "03-台账/真后端自证-原始输出.md"


@dataclass
class Snapshot:
    """Size + mtime of the read-only tree (`find -newermt` needs mtimes anyway)."""

    files: dict[str, tuple[int, int]] = field(default_factory=dict)
    newer: list[str] = field(default_factory=list)

    def diff(self, other: Snapshot) -> list[str]:
        """Return human readable differences between two snapshots.

        Args:
            other: The later snapshot.

        Returns:
            One line per added / removed / changed path (empty means unchanged).
        """
        changes: list[str] = []
        for relative in sorted(set(self.files) - set(other.files)):
            changes.append(f"removed: {relative}")
        for relative in sorted(set(other.files) - set(self.files)):
            changes.append(f"added: {relative}")
        for relative in sorted(set(self.files) & set(other.files)):
            if self.files[relative] != other.files[relative]:
                before, after = self.files[relative], other.files[relative]
                changes.append(f"changed: {relative} (size/mtime {before} -> {after})")
        return changes


class ReadonlyGuard:
    """``_old`` must stay byte-identical: snapshot it, then compare (G-4 / §1.5)."""

    def __init__(self, legacy_root: Path, *, started_ns: int | None = None) -> None:
        """Record the tree and the instant the run started.

        Args:
            legacy_root: The read-only legacy tree.
            started_ns: ``time.time_ns()`` at process start (files newer than this
                are writes made by this run).
        """
        self.legacy_root = Path(legacy_root)
        self.started_ns = started_ns if started_ns is not None else time.time_ns()
        self.before: Snapshot | None = None
        self.after: Snapshot | None = None

    def snapshot(self) -> Snapshot:
        """Walk the tree.

        Returns:
            A :class:`Snapshot` with per-file ``(size, mtime_ns)`` for the three
            subtrees and every file newer than :attr:`started_ns` outside them.
        """
        result = Snapshot()
        subtree_roots = [(self.legacy_root / Path(*item.split("/"))) for item in READONLY_SUBTREES]
        for root in subtree_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if WALK_EXCLUDES & set(path.relative_to(self.legacy_root).parts):
                    continue
                try:
                    stat = path.stat()
                except OSError:  # pragma: no cover - race
                    continue
                result.files[path.relative_to(self.legacy_root).as_posix()] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )

        for path in self.legacy_root.rglob("*"):
            if not path.is_file():
                continue
            if WALK_EXCLUDES & set(path.relative_to(self.legacy_root).parts):
                continue
            try:
                if path.stat().st_mtime_ns > self.started_ns:
                    result.newer.append(path.relative_to(self.legacy_root).as_posix())
            except OSError:  # pragma: no cover - race
                continue
        result.newer.sort()
        return result

    def take_before(self) -> Snapshot:
        """Snapshot before the run.

        Returns:
            The baseline snapshot.
        """
        self.before = self.snapshot()
        return self.before

    def verify(self) -> list[str]:
        """Compare the current tree with the baseline.

        Returns:
            Problems (empty means the tree is untouched).
        """
        self.after = self.snapshot()
        problems: list[str] = []
        if self.before is None:
            return ["no baseline snapshot was taken"]
        problems.extend(self.before.diff(self.after))
        for relative in self.after.newer:
            problems.append(f"written during the run (mtime newer than start): {relative}")
        return problems


@dataclass
class LegResult:
    """One ``node --test`` invocation.

    Attributes:
        name: ``forward`` / ``reverse``.
        command: The argv that was run (evidence).
        exit_code: Process exit code.
        output: Combined stdout/stderr.
        duration_s: Wall time.
    """

    name: str
    command: tuple[str, ...]
    exit_code: int
    output: str
    duration_s: float

    def summary_line(self) -> str:
        """Extract the TAP counts line(s) for evidence.

        Returns:
            The ``# tests`` / ``# pass`` / ... lines joined with ``" | "``.
        """
        keys = ("tests", "pass", "fail", "skipped", "todo", "cancelled")
        found: list[str] = []
        for line in self.output.splitlines():
            stripped = line.strip().lstrip("#ℹ ").strip()
            for key in keys:
                if re.fullmatch(rf"{key}\s+\d+", stripped):
                    found.append(stripped)
        return " | ".join(found) if found else "no TAP summary found"


@dataclass
class SelfProofRun:
    """Everything one self-proof produced (the evidence payload)."""

    started_at: str
    workdir: Path
    port: int
    attestation: str = ""
    pid_relation: str = ""
    session_before: int = -1
    session_after: int = -1
    wrapper_state: str = ""
    forward: LegResult | None = None
    reverse: LegResult | None = None
    count_check: str = ""
    channel_line: str = ""
    readonly_problems: tuple[str, ...] = ()
    readonly_note: str = ""
    problems: tuple[str, ...] = ()
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_binary() -> str:
    """Return the ``node`` executable path.

    Returns:
        The path from ``PATH`` (empty string when missing — reported, not guessed).
    """
    return shutil.which("node") or ""


def _run_node(*, pattern: str, env: dict[str, str], cwd: Path, timeout_s: float) -> tuple[int, str, float]:
    """Run ``node --test <pattern>`` and capture everything.

    Args:
        pattern: Glob handed to ``node --test``.
        env: Environment for the child.
        cwd: Working directory (repository root).
        timeout_s: Hard timeout.

    Returns:
        ``(exit_code, combined_output, duration)``.
    """
    command = [t for t in (_node_binary(), "--test", pattern) if t]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output, time.monotonic() - started
    except subprocess.TimeoutExpired as error:
        partial = (error.stdout or "") + (error.stderr or "")
        if isinstance(partial, bytes):  # pragma: no cover - text=True should prevent this
            partial = partial.decode("utf-8", "replace")
        return _gate_io.EXIT_RUNNER_NOT_GREEN, partial + "\n[e2e] TIMEOUT", time.monotonic() - started


def _probe_refused(url_path: str, timeout_s: float = 5.0) -> str:
    """Probe a URL and return a one-line description of the transport outcome.

    Args:
        url_path: Absolute URL.
        timeout_s: Per-request timeout.

    Returns:
        ``"HTTP <status>"`` when something answered, else the exception class.
    """
    try:
        with urllib.request.urlopen(url_path, timeout=timeout_s) as response:
            return f"HTTP {int(response.status)}"
    except urllib.error.HTTPError as error:
        return f"HTTP {int(error.code)}"
    except urllib.error.URLError as error:
        return f"URLError({error.reason})"
    except OSError as error:
        return f"OSError({error})"


def _register_once(base_url: str, *, timeout_s: float = 30.0) -> tuple[int, str]:
    """Register one throw-away user and report the raw ``X-E2E-Nonce`` fingerprint.

    S-4's "a real write happened" must not depend on the runner's internals: the
    orchestrator performs **one** write itself and counts the table around it, so
    the delta is exactly one row by construction.  (The runner registers once per
    test file — three processes — which is why its own delta is three and is only
    recorded as information.)

    Args:
        base_url: Live backend base URL.
        timeout_s: Per-request timeout.

    Returns:
        ``(http_status, nonce fingerprint or a marker)``.
    """
    import hashlib
    import json as json_module

    username = f"e2e_session_proof_{uuid.uuid4().hex[:12]}"
    payload = json_module.dumps(
        {
            "username": username,
            "email": f"{username}@example.com",
            "password": "E2e-Passw0rd!23",
            "display_name": "session proof",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/v1/auth/register", data=payload, method="POST"
    )
    request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            nonce = response.headers.get(launcher.NONCE_HEADER, "")
            fingerprint = (
                hashlib.sha256(nonce.encode("utf-8")).hexdigest()[:12] if nonce else "absent"
            )
            return int(response.status), fingerprint
    except urllib.error.HTTPError as error:
        return int(error.code), "http-error"


def _channel_line(output: str) -> str:
    """Extract the SSE coverage diagnostic from the TAP output.

    Args:
        output: Combined runner output.

    Returns:
        The coverage line, or a marker when the case never reported one.
    """
    for line in output.splitlines():
        if "sse coverage:" in line:
            return line.strip().lstrip("#ℹ ").strip()
    return "sse coverage: NOT REPORTED"


def _evidence_path(repo_root: Path) -> Path:
    """Resolve the evidence markdown inside the V0.0.2 ledger directory.

    Args:
        repo_root: Repository root.

    Returns:
        ``docs/V1.0/V0.0.2-*/03-台账/真后端自证-原始输出.md`` (first match).
    """
    matches = sorted(repo_root.glob("docs/V1.0/V0.0.2-*/03-台账"))
    if matches:
        return matches[0] / Path(EVIDENCE_RELATIVE).name
    return repo_root / "output" / "e2e" / Path(EVIDENCE_RELATIVE).name  # pragma: no cover


def _write_evidence(run: SelfProofRun, repo_root: Path) -> Path:
    """Write the evidence markdown (raw output embedded, never a ``.log``).

    Args:
        run: The finished run.
        repo_root: Repository root.

    Returns:
        The path written.
    """
    target = _evidence_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# 真后端自证 · 原始输出（自动生成，请勿手改）",
        "",
        f"- 生成时间（UTC）：`{run.started_at}`",
        f"- 工作目录：`{run.workdir.as_posix()}`",
        f"- 端口：`{run.port}`",
        f"- 退出码：`{run.exit_code}`",
        "",
        "> 本文件由 `python scripts/selfproof/run_selfproof.py` 覆盖写入。",
        "> `*.log` 被 `.gitignore` 忽略，故原始输出**内嵌**在此（K-8）。",
        "> 措辞红线（裁定 D-1）：`X-E2E-Nonce` 由**我们仓内的包装层**产生，证明的是",
        "> 「这条响应来自本 runner spawn 的那个进程」，**不等于**「Python 后端自身实现了",
        "> nonce 协议」。",
        "",
        "## 1 · 三证（nonce / attest / DB 行增量）",
        "",
        "```text",
        f"attest: {run.attestation}",
        f"pid relation: {run.pid_relation}",
        f"session rows: before={run.session_before} after={run.session_after}"
        f" delta={run.session_after - run.session_before if run.session_before >= 0 and run.session_after >= 0 else 'n/a'}",
        f"wrapper state: {run.wrapper_state}",
        "```",
        "",
        "## 2 · forward 段（DoD#4 四用例）",
        "",
    ]
    if run.forward is not None:
        lines.extend(
            [
                f"- 命令：`{' '.join(run.forward.command)}`",
                f"- 退出码：`{run.forward.exit_code}`，耗时 `{run.forward.duration_s:.1f}s`",
                f"- 计数：`{run.forward.summary_line()}`",
                f"- S-5 外检：`{run.count_check}`",
                f"- 通道矩阵：`{run.channel_line}`",
                "",
                "```text",
                run.forward.output.rstrip(),
                "```",
                "",
            ]
        )
    lines.extend(["## 3 · reverse 段（kill 后必须 ECONNREFUSED）", ""])
    if run.reverse is not None:
        lines.extend(
            [
                f"- 命令：`{' '.join(run.reverse.command)}`",
                f"- 退出码：`{run.reverse.exit_code}`，耗时 `{run.reverse.duration_s:.1f}s`",
                f"- 计数：`{run.reverse.summary_line()}`",
                "",
                "```text",
                run.reverse.output.rstrip(),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## 4 · 只读自证（`_old` 零字节写入）",
            "",
            "```text",
            run.readonly_note or "(no note)",
            "```",
            "",
            "## 5 · 结论",
            "",
            "```text",
            *(run.problems if run.problems else ("no problem recorded",)),
            f"exit={run.exit_code}",
            "```",
            "",
        ]
    )
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Build and parse the CLI.

    Args:
        argv: Arguments without the program name.

    Returns:
        The namespace.
    """
    parser = argparse.ArgumentParser(
        prog="run_selfproof.py",
        description=(
            "S-6: boot the real legacy backend, run the four DoD#4 cases over HTTP, kill "
            "it, require ECONNREFUSED on the reverse leg, and prove the read-only tree "
            "was never written."
        ),
    )
    parser.add_argument("--port", type=int, default=launcher.DEFAULT_PORT, help="TCP port (forward and reverse share it)")
    parser.add_argument("--legacy-root", type=Path, default=None, help="read-only legacy tree")
    parser.add_argument("--legacy-python", type=Path, default=None, help="interpreter with fastapi/uvicorn")
    parser.add_argument("--workdir", type=Path, default=None, help="scratch directory (default output/e2e/selfproof-<ts>)")
    parser.add_argument("--boot-timeout", type=float, default=90.0, help="seconds to wait for /health")
    parser.add_argument("--leg-timeout", type=float, default=300.0, help="seconds per node leg")
    parser.add_argument("--keep", action="store_true", help="keep the scratch workdir")
    parser.add_argument("--no-evidence", action="store_true", help="do not write the evidence markdown")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``2`` / ``30``–``36`` / ``51``–``53`` (design §3.3).
    """
    arguments = _parse_args(argv)
    repo_root = _REPO_ROOT
    legacy_root = launcher.resolve_legacy_root(arguments.legacy_root)
    legacy_python = launcher.resolve_legacy_python(legacy_root, arguments.legacy_python)
    node = _node_binary()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    workdir = (
        Path(arguments.workdir).expanduser().resolve()
        if arguments.workdir
        else repo_root / "output" / "e2e" / f"selfproof-{stamp}"
    )

    guard = ReadonlyGuard(legacy_root, started_ns=time.time_ns())
    run = SelfProofRun(
        started_at=_gate_io.utc_now_iso(),
        workdir=workdir,
        port=int(arguments.port),
    )

    _gate_io.log(TAG, f"self-proof (S-6) at {run.started_at}")
    _gate_io.log(TAG, f"repo={repo_root.as_posix()} legacy={legacy_root.as_posix()}")
    _gate_io.log(TAG, f"workdir={workdir.as_posix()} port={run.port} node={node or 'MISSING'}")

    # --- G-1..G-6 ---------------------------------------------------------
    problems = launcher.check_prerequisites(
        legacy_root=legacy_root, python=legacy_python, port=run.port, require_port=True
    )
    if node == "":
        problems.append("G-6: node not found")
    if problems:
        for problem in problems:
            _gate_io.log(TAG, f"PRECONDITION FAIL: {problem}")
        run.problems = tuple(problems)
        run.exit_code = _gate_io.EXIT_LAUNCH_TIMEOUT
        _gate_io.log(TAG, "VERDICT: BLOCKED (51) — segment II cannot start, nothing was proven")
        if not arguments.no_evidence:
            _write_evidence(run, repo_root)
        return run.exit_code

    baseline = guard.take_before()
    _gate_io.log(
        TAG,
        f"read-only baseline: {len(baseline.files)} file(s) in {len(READONLY_SUBTREES)} subtree(s), "
        f"{len(baseline.newer)} newer-than-start file(s) already present",
    )

    # --- start the real backend ------------------------------------------
    nonce = uuid.uuid4().hex
    process = launcher.BackendProcess(
        port=run.port,
        nonce=nonce,
        db_source=legacy_root / "wbtime-ai_local.db",
        workdir=workdir,
        python=legacy_python,
        legacy_root=legacy_root,
    )
    try:
        process.start(timeout_s=float(arguments.boot_timeout))
    except PermissionError as error:
        run.problems = (str(error),)
        run.exit_code = _gate_io.EXIT_PORT_BUSY
        _gate_io.log(TAG, f"VERDICT: PORT BUSY (52) — {error}")
        if not arguments.no_evidence:
            _write_evidence(run, repo_root)
        return run.exit_code
    except (TimeoutError, OSError) as error:
        run.problems = (str(error),)
        run.exit_code = _gate_io.EXIT_LAUNCH_TIMEOUT
        _gate_io.log(TAG, f"VERDICT: LAUNCH FAILED (51) — {error}")
        if not arguments.no_evidence:
            _write_evidence(run, repo_root)
        return run.exit_code

    exit_code = _gate_io.EXIT_OK
    try:
        # --- second proof: attestation ------------------------------------
        attestation = process.attest()
        run.attestation = attestation.render()
        run.wrapper_state = attestation.wrapper
        if attestation.nonce != nonce:
            run.problems += ("attestation nonce does not match the run nonce",)
        if attestation.pid == process.pid:
            run.pid_relation = "direct (attest.pid == spawned pid)"
        elif attestation.ppid == process.pid:
            run.pid_relation = (
                f"trampoline (attest.ppid == spawned pid {process.pid}; the venv python.exe "
                "redirector inserts one process — measured, not hidden)"
            )
        else:
            run.pid_relation = (
                f"UNVERIFIED (attest.pid={attestation.pid} attest.ppid={attestation.ppid} "
                f"spawned={process.pid})"
            )
            run.problems += ("attestation pid is neither the spawned pid nor its direct child",)
        _gate_io.log(TAG, f"attest: {run.attestation}")
        _gate_io.log(TAG, f"pid relation: {run.pid_relation}")

        # --- third proof: a real write (one register => exactly one row) ---
        run.session_before = launcher.count_session_rows(workdir / "run.db")
        status, nonce_fingerprint = _register_once(f"http://127.0.0.1:{run.port}")
        run.session_after = launcher.count_session_rows(workdir / "run.db")
        write_delta = run.session_after - run.session_before
        _gate_io.log(
            TAG,
            f"session proof: register HTTP {status} nonce={nonce_fingerprint} "
            f"rows {run.session_before} -> {run.session_after} (delta={write_delta})",
        )
        if status != 201 or write_delta != 1:
            run.problems += (
                f"session proof failed: HTTP {status}, row delta {write_delta} (expected 201 / +1)",
            )
            exit_code = _gate_io.EXIT_RUNNER_NOT_GREEN

        # --- forward leg ---------------------------------------------------
        environment = dict(os.environ)
        environment.update(
            {
                "E2E_BASE_URL": f"http://127.0.0.1:{run.port}",
                "E2E_RUN_NONCE": nonce,
                "E2E_LEG": "forward",
                "E2E_LEGACY_ROOT": str(legacy_root),
                "E2E_LEGACY_PYTHON": str(legacy_python),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        environment.pop("E2E_PORT", None)

        code, output, duration = _run_node(
            pattern=FORWARD_GLOB, env=environment, cwd=repo_root, timeout_s=float(arguments.leg_timeout)
        )
        run.forward = LegResult(
            name="forward",
            command=(node, "--test", FORWARD_GLOB),
            exit_code=code,
            output=output,
            duration_s=duration,
        )
        run.channel_line = _channel_line(output)
        _gate_io.log(TAG, f"forward: exit={code} {run.forward.summary_line()} ({duration:.1f}s)")
        _gate_io.log(TAG, run.channel_line)
        if code != 0:
            run.problems += (f"forward leg exit={code}",)
            exit_code = code if code in (30, 31, 32, 33, 34) else _gate_io.EXIT_RUNNER_NOT_GREEN

        # --- S-5: re-check the TAP counts out of process ------------------
        tap_file = workdir / "forward.tap.txt"
        tap_file.write_text(output, encoding="utf-8")
        counts_module = (repo_root / "packages" / "e2e" / "lib" / "counts.mjs").as_posix()
        count_environment = dict(os.environ)
        count_environment.update(
            {
                "E2E_COUNTS_MODULE": Path(counts_module).as_uri(),
                "E2E_TAP_FILE": str(tap_file),
                "E2E_EXPECTED_CASES": str(4),
            }
        )
        completed = subprocess.run(
            [node, "--input-type=module", "-e", COUNT_CHECK_SCRIPT],
            cwd=str(repo_root),
            env=count_environment,
            capture_output=True,
            text=True,
            timeout=60.0,
            check=False,
        )
        run.count_check = ((completed.stdout or "") + (completed.stderr or "")).strip()
        _gate_io.log(TAG, f"S-5 count check: exit={completed.returncode} :: {run.count_check}")
        if completed.returncode != 0:
            run.problems += ("S-5 count check failed",)
            exit_code = _gate_io.EXIT_RUNNER_COUNT

        # --- the runner wrote too: record how much (3 files => 3 registers) --
        runner_rows = launcher.count_session_rows(workdir / "run.db")
        _gate_io.log(
            TAG,
            f"session rows after the forward leg: {runner_rows} "
            f"(runner delta={runner_rows - run.session_after}; one register per test file)",
        )
        if runner_rows <= run.session_after:
            run.problems += ("the forward leg wrote nothing to the session table",)
            exit_code = _gate_io.EXIT_RUNNER_NOT_GREEN

        # --- kill ----------------------------------------------------------
        closed = process.terminate_and_wait(timeout_s=15.0)
        leftover = _probe_refused(f"http://127.0.0.1:{run.port}/health")
        _gate_io.log(TAG, f"kill: port closed={closed} probe_after_kill={leftover}")
        if not closed:
            run.problems += ("the port was still open after SIGTERM",)
            exit_code = _gate_io.EXIT_PORT_STILL_OPEN

        # --- reverse leg ---------------------------------------------------
        reverse_environment = dict(environment)
        reverse_environment["E2E_LEG"] = "reverse"
        reverse_code, reverse_output, reverse_duration = _run_node(
            pattern=REVERSE_GLOB,
            env=reverse_environment,
            cwd=repo_root,
            timeout_s=float(arguments.leg_timeout),
        )
        run.reverse = LegResult(
            name="reverse",
            command=(node, "--test", REVERSE_GLOB),
            exit_code=reverse_code,
            output=reverse_output,
            duration_s=reverse_duration,
        )
        _gate_io.log(TAG, f"reverse: exit={reverse_code} {run.reverse.summary_line()} ({reverse_duration:.1f}s)")
        if reverse_code != 0:
            run.problems += (f"reverse leg exit={reverse_code} (red cause not legal, or the port answered)",)
            exit_code = reverse_code if reverse_code in (30, 31, 32, 33, 34) else _gate_io.EXIT_RUNNER_BAD_CAUSE
    finally:
        if not process.terminate_and_wait(timeout_s=10.0):  # pragma: no cover - already closed
            _gate_io.log(TAG, "WARNING: could not confirm the port was closed")

    # --- reverse proof of read-only ---------------------------------------
    readonly_problems = guard.verify()
    run.readonly_problems = tuple(readonly_problems)
    run.readonly_note = (
        "snapshot subtrees: " + ", ".join(READONLY_SUBTREES) + "\n"
        f"files compared: {len(guard.before.files) if guard.before else 0}\n"
        f"files newer than the run start: {len(guard.after.newer) if guard.after else 0}\n"
        + ("diff: (empty — zero bytes written)\n" if not readonly_problems else "\n".join(readonly_problems) + "\n")
    )
    _gate_io.log(
        TAG,
        f"read-only self-proof: {len(readonly_problems)} problem(s), "
        f"newer-than-start files={len(guard.after.newer) if guard.after else -1}",
    )
    for problem in readonly_problems:
        _gate_io.log(TAG, f"READONLY VIOLATION: {problem}")
    if readonly_problems:
        run.problems += tuple(readonly_problems)
        exit_code = _gate_io.EXIT_READONLY_DIRTY

    run.exit_code = exit_code
    if not arguments.no_evidence:
        written = _write_evidence(run, repo_root)
        _gate_io.log(TAG, f"evidence: {written.as_posix()}")
    if not arguments.keep and workdir.is_dir():
        shutil.rmtree(workdir, ignore_errors=True)

    if exit_code == _gate_io.EXIT_OK:
        _gate_io.log(
            TAG,
            "VERDICT: PASS (0) — forward 4/4 green on the real backend, reverse red with a "
            "legal cause, session +1, read-only tree untouched",
        )
    else:
        _gate_io.log(TAG, f"VERDICT: FAIL ({exit_code}) — {len(run.problems)} problem(s)")
        for problem in run.problems:
            _gate_io.log(TAG, f"  - {problem}")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
