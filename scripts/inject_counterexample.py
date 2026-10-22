"""T04 — the counterexample engine: clone -> tamper -> re-pin -> judge the gate.

What this script proves (and what it refuses to prove)
-----------------------------------------------------
A gate that is never red is not a gate.  This engine takes a *named* tamper from
:mod:`inject_cases`, applies it inside a **temporary clone** of the repository
(``contracts/`` **and** ``scripts/`` — see §11.1 below), re-pins the whole ledger
chain exactly like a deliberate attacker would, and then insists on three facts:

1. the **target gate goes red** (otherwise ``EXIT_FAKE_GREEN`` / ``10``);
2. the red carries the **declared reason** (diff kind / criterion id / object
   name), not just any red (otherwise ``EXIT_FALSE_REFUTATION`` / ``11``);
3. for the "self-consistent" cases, the *integrity* gate ``run.py check`` and the
   nominated sibling gates stay **green on the same clone** — that is the whole
   argument for "semantic gates see what a sha256 ledger cannot"; a failure here
   means the case's premise is false and is reported as
   ``EXIT_CASE_UNEVALUABLE`` / ``12``, never as a pass.

Why the toolkit is cloned too (design §11.1 — the thing T03 measured)
--------------------------------------------------------------------
``run.py check`` is *not* purely mechanical: ``contract_manifest.verify``
hard-codes ``245`` ddl objects, ``2`` raw hnsw entries and
``migration_count == 10`` as **code constants**.  Re-pinning only the ledgers
therefore leaves ``check`` red for a mechanical reason, and "check stayed green"
would be a lie.  Every case that asserts integrity clones ``scripts/`` as well;
the self-consistent case also rewrites those constants (see
:func:`inject_cases.ddl_hnsw_deleted_consistent`).

What this script is not
-----------------------
It never judges whether the *product* is correct, it never touches the real
``contracts/`` or ``D:/WBT/WBTimeAI_old``, and it never relaxes
``must_be_red``: a case with an empty expectation set is **INVALID** (``12``),
because "no expectation declared" and "the expectation held" must not be the
same exit code.

Exit codes (design §3.3 — the 10/11/12 band belongs to this script)
------------------------------------------------------------------
``0``   every selected case is red for the declared reason
``10``  fake green — the target gate *stayed green* on a tampered clone
``11``  false refutation — red, but the declared reason never appeared
``12``  case not evaluable — clone/tamper/load failure, empty expectation set,
        or a sibling gate that was supposed to stay green went red
``2``   usage error
``9``   ``--self-test`` failed

CLI::

    python -B scripts/inject_counterexample.py --list
    python -B scripts/inject_counterexample.py --all
    python -B scripts/inject_counterexample.py --case sse-channel-dropped --keep
    python -B scripts/inject_counterexample.py --all --json
    python -B scripts/inject_counterexample.py --self-test

Python: standard library only (``施工纪律`` §4.9: no third-party imports).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)
import inject_cases  # noqa: E402  (the registry: pure data + mutators)

__all__ = [
    "TAG",
    "InjectionResult",
    "GateSpec",
    "GATES",
    "clone_repo",
    "reseal",
    "run_case",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "inject"

#: Directories that must never be copied into a clone.
#:
#: ``node_modules`` is on the list because of the V0.3.1 spike gate: pnpm lays
#: ``apps/api/node_modules`` out as a forest of **symlinks** into the workspace
#: root store, and :func:`shutil.copytree` follows them by default — which would
#: inline half the workspace into the clone and leave ``@wbtime/db`` unresolvable.
#: :func:`prepare_v031_clone` links the two ``node_modules`` directories instead.
_CLONE_IGNORE: Final[tuple[str, ...]] = (
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
)

#: Files that must never be copied into a clone.
_CLONE_IGNORE_GLOBS: Final[tuple[str, ...]] = ("*.pyc", "*.pyo", "*.tmp", "*.bak")

#: Default timeout for one gate subprocess (seconds).  Each gate measures < 1 s on
#: the reference machine; the ceiling exists so a hung gate cannot fake a red.
DEFAULT_TIMEOUT_S: Final[float] = 120.0


class CaseError(RuntimeError):
    """Raised when a case cannot be evaluated at all (``EXIT_CASE_UNEVALUABLE``)."""


# ---------------------------------------------------------------------------
# Gate table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateSpec:
    """How to invoke one gate inside a cloned repository.

    Attributes:
        key: Registry key used by :mod:`inject_cases`.
        script: Script path relative to the clone's repository root.  Empty for
            interpreter-driven gates whose ``build_argv`` already names the
            target (see :attr:`interpreter`).
        build_argv: ``(contracts, legacy_root) -> argument list`` (without the
            interpreter and, for Python gates, without the script path).
        label: Human label for the evidence lines.
        red_codes: Exit codes that mean "this gate evaluated the input and said
            red".  **Not** always ``1``: design §3.3 gives ``verify_semantics``
            ``2`` for a semantic contradiction and ``oracle_recompute`` ``20``.
            Treating those as "usage error" would mislabel a correct refutation
            as "not evaluable", so the table is explicit instead of guessed.
        unevaluable_codes: Exit codes that mean "this gate never judged the
            input" (usage error, unreadable artifacts, failed self-test).
        interpreter: ``"python"`` (default) or ``"node"``.  Node gates bypass the
            ``-B`` bytecode flag and resolve the binary from ``PATH``.
        clone_dirs: Repository-relative directories copied into the clone.
            The five contract gates only need ``contracts`` + ``scripts``; the
            V0.3.1 spike gate additionally needs ``apps/api`` (the implementation
            under test) and ``output`` (the DDL the API test harness reads).
        prepare: ``(clone_root, source_repo) -> None`` hook run right after the
            clone, before the control run.  Used to wire ``node_modules`` into
            the clone without copying 383 MiB of pnpm store.
        reseals: Whether the contract ledger chain must be re-pinned after the
            tamper.  ``False`` for gates that judge source code rather than
            ``contracts/`` artifacts.
    """

    key: str
    script: str
    build_argv: Callable[[Path, Path], list[str]]
    label: str
    red_codes: tuple[int, ...]
    unevaluable_codes: tuple[int, ...]
    interpreter: str = "python"
    clone_dirs: tuple[str, ...] = ("contracts", "scripts")
    prepare: Callable[[Path, Path], None] | None = None
    reseals: bool = True


def _argv_contracts_only(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for gates that only read ``contracts/``.

    Args:
        contracts: Contracts directory inside the clone.
        legacy: Legacy root (unused).

    Returns:
        The argument list.
    """
    del legacy
    return ["--contracts", str(contracts)]


def _argv_openapi_legacy(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for the OpenAPI gate against the static legacy scan.

    ``--candidate file`` compares the frozen document with itself and is
    therefore structurally incapable of failing; the injection targets the
    external static scan over the demanded collections that §10.7 measured as
    fully covered (``paths`` 100/100, ``operations`` 134/134).  ``schemas`` is
    deliberately **not** demanded: the static scan cannot reproduce FastAPI's
    transitive ``response_model`` graph, and demanding it would make the red
    come from a declared degradation instead of from the deleted path.

    Args:
        contracts: Contracts directory inside the clone.
        legacy: Read-only legacy repository root.

    Returns:
        The argument list.
    """
    return [
        "--contracts",
        str(contracts),
        "--frozen",
        str(contracts / inject_cases.OPENAPI_FROZEN),
        "--candidate",
        "legacy",
        "--legacy-root",
        str(legacy),
        "--require",
        "paths,operations",
    ]


def _argv_oracle(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for the external-oracle gate (O-A tier).

    Args:
        contracts: Contracts directory inside the clone.
        legacy: Read-only legacy repository root.

    Returns:
        The argument list.
    """
    return [
        "--oracle",
        "legacy",
        "--contracts",
        str(contracts),
        "--legacy-root",
        str(legacy),
    ]


def _argv_v031_spike(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for the V0.3.1 spike carrier (a **Node** gate).

    ``--experimental-sqlite`` is mandatory: the project cannot install
    ``better-sqlite3``, so ``apps/api`` tests use ``node:sqlite``.  The path is
    repository-relative because the gate runs with ``cwd=<clone root>`` — exactly
    the G031-4 · S2 command from the construction chain,只是跑在克隆里.

    Args:
        contracts: Contracts directory (unused — the carrier reads it itself).
        legacy: Legacy root (unused).

    Returns:
        The argument list, **including** the script path (this gate has no
        separate ``script`` field).
    """
    del contracts, legacy
    return ["--experimental-sqlite", "--test", inject_cases.V031_CARRIER]


def _argv_v031_watermark(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for the V0.3.1 watermark carrier (a **Node** gate).

    D6 游标缺口（水位归属）判据载体，与 :func:`_argv_v031_spike` 同款：
    ``--experimental-sqlite`` 强制 + 仓库相对路径（gate 以 ``cwd=<clone root>``
    运行）。载体文件由 QA 落盘（``apps/api/tests/sse-watermark.test.mjs``），
    执行者 ≠ 判定者（P1-3）。

    Args:
        contracts: Contracts directory (unused — the carrier reads it itself).
        legacy: Legacy root (unused).

    Returns:
        The argument list, **including** the script path.
    """
    del contracts, legacy
    return ["--experimental-sqlite", "--test", inject_cases.V031_WATERMARK_CARRIER]


def prepare_v031_clone(clone: Path, source_repo: Path) -> None:
    """Wire ``node_modules`` into a clone without copying the pnpm store.

    ``apps/api`` tests import built output (``../dist/...``) and workspace
    packages (``@wbtime/db`` …).  Both are reachable through the *real* trees,
    which the case only ever **reads**.  Copying the 383 MiB store per case is
    not an option, so the two ``node_modules`` directories are linked instead.

    On Windows this needs a directory junction/symlink; on POSIX a plain symlink.
    Both are created with the target being an **absolute** path so a relative
    re-interpretation inside the clone cannot silently point somewhere else.

    Args:
        clone: Clone repository root.
        source_repo: Real repository root (read-only source).

    Raises:
        CaseError: A link cannot be created.
    """
    for relative in ("node_modules", "apps/api/node_modules"):
        source = source_repo / Path(*relative.split("/"))
        link = clone / Path(*relative.split("/"))
        if not source.is_dir():
            raise CaseError(f"prepare: missing source directory {source.as_posix()}")
        if link.exists() or link.is_symlink():
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(source, target_is_directory=True)
        except OSError as error:
            raise CaseError(
                f"prepare: cannot link {link.as_posix()} -> {source.as_posix()}: {error}. "
                "On Windows this needs Developer Mode or a junction-capable account."
            ) from error


def _argv_run_check(contracts: Path, legacy: Path) -> list[str]:
    """Arguments for the integrity gate ``run.py check``.

    Args:
        contracts: Contracts directory inside the clone.
        legacy: Legacy root (unused — ``check`` never reads it).

    Returns:
        The argument list.
    """
    del legacy
    return ["check", "--contracts-dir", str(contracts)]


#: Every gate this engine can target, keyed by :data:`inject_cases.GATE_KEYS`.
GATES: Final[dict[str, GateSpec]] = {
    "check_ddl_parity": GateSpec(
        key="check_ddl_parity",
        script="scripts/check_ddl_parity.py",
        build_argv=_argv_contracts_only,
        label="three-source DDL parity",
        red_codes=(1,),
        unevaluable_codes=(2, 9),
    ),
    "verify_semantics": GateSpec(
        key="verify_semantics",
        script="scripts/verify_semantics.py",
        build_argv=_argv_contracts_only,
        label="semantic criteria C1-C23 + S1",
        red_codes=(2,),
        unevaluable_codes=(3, 4),
    ),
    "compare_openapi_legacy": GateSpec(
        key="compare_openapi_legacy",
        script="scripts/compare_openapi.py",
        build_argv=_argv_openapi_legacy,
        label="frozen OpenAPI vs static legacy scan",
        red_codes=(1,),
        unevaluable_codes=(2, 9),
    ),
    "oracle_recompute": GateSpec(
        key="oracle_recompute",
        script="scripts/oracle_recompute.py",
        build_argv=_argv_oracle,
        label="external oracle (O-A legacy) recompute",
        red_codes=(20,),
        unevaluable_codes=(2, 9, 21, 22),
    ),
    "run_check": GateSpec(
        key="run_check",
        script="scripts/extract-from-py/run.py",
        build_argv=_argv_run_check,
        label="integrity: sha256 + dual ledger",
        red_codes=(1,),
        unevaluable_codes=(2,),
    ),
    "v031_spike": GateSpec(
        key="v031_spike",
        script="",
        build_argv=_argv_v031_spike,
        label="V0.3.1 spike carrier (node --test)",
        # `node --test` exits 1 when at least one assertion failed.  Anything
        # else (module load crash, bad flag, missing runner) means the gate never
        # judged the input and must never be read as a refutation.
        red_codes=(1,),
        unevaluable_codes=(2, 9),
        interpreter="node",
        clone_dirs=("contracts", "scripts", "apps/api", "output"),
        prepare=prepare_v031_clone,
        reseals=False,
    ),
    "v031_watermark": GateSpec(
        key="v031_watermark",
        script="",
        build_argv=_argv_v031_watermark,
        label="V0.3.1 D6 watermark carrier (node --test)",
        # 与 `v031_spike` 同口径：exit 1 = 至少一条断言红（真红）；其余退出码
        # （模块加载崩溃 / 旗标错 / runner 缺失）一律不可判，绝不读作反驳。
        red_codes=(1,),
        unevaluable_codes=(2, 9),
        interpreter="node",
        clone_dirs=("contracts", "scripts", "apps/api", "output"),
        prepare=prepare_v031_clone,
        reseals=False,
    ),
}


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one subprocess run.

    Attributes:
        exit_code: Process exit code (``-1`` when it could not be started).
        output: Combined stdout + stderr.
        seconds: Wall-clock duration.
        argv: The command line, for evidence.
    """

    exit_code: int
    output: str
    seconds: float
    argv: tuple[str, ...] = ()

    def tail(self, lines: int = 12) -> str:
        """Return the last ``lines`` non-empty output lines joined by `` | ``.

        Args:
            lines: How many trailing lines to keep.

        Returns:
            A single line suitable for an evidence row.
        """
        kept = [line for line in self.output.splitlines() if line.strip()]
        return " | ".join(kept[-lines:]) if kept else ""

    def red_lines(self, limit: int = 8) -> str:
        """Return the output lines that carry the red verdict, joined by `` | ``.

        The last N lines of a gate are usually summary lines; the *reason* sits on
        the lines that say FAIL / MISMATCH / DIFF / mismatch.  Both are kept so the
        ledger can quote a red without pasting 30 lines of green.

        Args:
            limit: Maximum number of red lines to keep.

        Returns:
            A single line, or the tail when no red marker is found.
        """
        markers = ("FAIL", "MISMATCH", "DIFF", "mismatch", "INVALID", "missing:", "extra:")
        kept = [
            line.strip()
            for line in self.output.splitlines()
            if line.strip() and any(marker in line for marker in markers)
        ]
        if not kept:
            return self.tail(limit)
        return " | ".join(kept[:limit]) + f" | (last) {self.tail(2)}"


def run_command(argv: Sequence[str], *, cwd: Path, timeout_s: float) -> CommandResult:
    """Run one command and capture its combined output.

    Args:
        argv: Full command line (interpreter first).
        cwd: Working directory (the clone's repository root).
        timeout_s: Hard timeout; a timeout is reported as exit ``-1``.

    Returns:
        A :class:`CommandResult`.
    """
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTHONPATH", None)  # a stray path would defeat the clone
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or ""
        if isinstance(partial, bytes):  # pragma: no cover - text=True normally
            partial = partial.decode("utf-8", "replace")
        return CommandResult(
            exit_code=-1,
            output=str(partial) + f"\nTIMEOUT after {timeout_s}s",
            seconds=time.monotonic() - started,
            argv=tuple(argv),
        )
    except OSError as error:
        return CommandResult(
            exit_code=-1,
            output=f"cannot start {argv[0]!r}: {error}",
            seconds=time.monotonic() - started,
            argv=tuple(argv),
        )
    return CommandResult(
        exit_code=int(completed.returncode),
        output=completed.stdout or "",
        seconds=time.monotonic() - started,
        argv=tuple(argv),
    )


def gate_argv(gate: GateSpec, repo: Path, contracts: Path, legacy: Path) -> list[str]:
    """Build the full command line for one gate inside a clone.

    Args:
        gate: Gate specification.
        repo: Clone repository root.
        contracts: Contracts directory inside the clone.
        legacy: Read-only legacy repository root (real tree, never cloned).

    Returns:
        ``[python, -B, <script>, *args]`` for interpreter ``"python"``, or
        ``[node, *args]`` for interpreter ``"node"`` (where ``args`` already
        contains the script path — see :meth:`GateSpec.build_argv`).
    """
    if gate.interpreter == "node":
        executable = shutil.which("node") or "node"
        return [executable, *gate.build_argv(contracts, legacy)]
    return [
        sys.executable,
        "-B",
        str(repo / Path(*gate.script.split("/"))),
        *gate.build_argv(contracts, legacy),
    ]


def run_gate(gate_key: str, repo: Path, contracts: Path, legacy: Path, timeout_s: float) -> CommandResult:
    """Run one registered gate against a cloned contracts directory.

    Args:
        gate_key: Key into :data:`GATES`.
        repo: Clone repository root.
        contracts: Contracts directory inside the clone.
        legacy: Read-only legacy repository root.
        timeout_s: Hard timeout.

    Returns:
        The command result.
    """
    gate = GATES[gate_key]
    return run_command(gate_argv(gate, repo, contracts, legacy), cwd=repo, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Cloning and re-pinning
# ---------------------------------------------------------------------------


def _ignore_factory() -> Callable[[str, list[str]], set[str]]:
    """Build the ``copytree`` ignore callable.

    Returns:
        A callable dropping caches and compiled artifacts.
    """

    def _ignore(directory: str, names: list[str]) -> set[str]:
        del directory
        dropped: set[str] = set()
        for name in names:
            if name in _CLONE_IGNORE:
                dropped.add(name)
                continue
            if any(name.endswith(suffix.lstrip("*")) for suffix in _CLONE_IGNORE_GLOBS):
                dropped.add(name)
        return dropped

    return _ignore


def clone_repo(source_repo: Path, destination: Path, directories: Sequence[str] = ("contracts", "scripts")) -> None:
    """Clone the given repository-relative trees into a fresh scratch repository.

    ``contracts/`` and ``scripts/`` are the baseline pair: ``contracts/`` because
    that is what the contract gates judge, ``scripts/`` because ``run.py check``
    depends on code constants that live there (§11.1) and because the gates
    themselves must run *from the clone* so a gate mutation cannot escape the
    scratch directory.

    The V0.3.1 spike gate adds ``apps/api`` (the implementation it tampers with)
    and ``output`` (``output/ddl.sqlite.sql``, read by the API test harness).
    ``node_modules`` is never copied — :func:`prepare_v031_clone` links it.

    Args:
        source_repo: Real repository root (read-only source).
        destination: Scratch repository root to create.
        directories: Repository-relative directories to copy.

    Raises:
        CaseError: A required source directory is missing, or the copy failed.
    """
    ignore = _ignore_factory()
    destination.mkdir(parents=True, exist_ok=True)
    for relative in directories:
        source = source_repo / Path(*relative.split("/"))
        if not source.is_dir():
            raise CaseError(f"missing source directory: {source.as_posix()}")
        target = destination / Path(*relative.split("/"))
        try:
            shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)
        except OSError as error:
            raise CaseError(f"cannot clone {source.as_posix()}: {error}") from error
    (destination / "output").mkdir(exist_ok=True)


def _load_clone_hashes(repo: Path) -> Any:
    """Import the clone's own ``hashes`` module (no drift, no second truth).

    Using the *cloned* module means the ledger format is by construction the one
    ``run.py check`` will verify — re-implementing ``iter_artifact_files`` here
    would create a second definition of "which files are artifacts".

    Args:
        repo: Clone repository root.

    Returns:
        The imported module.

    Raises:
        CaseError: The module cannot be imported.
    """
    module_path = repo / "scripts" / "extract-from-py" / "hashes.py"
    module_name = f"_inject_hashes_{abs(hash(module_path.as_posix()))}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise CaseError(f"cannot import {module_path.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001 - reported as "not evaluable"
        raise CaseError(f"cannot import {module_path.as_posix()}: {error}") from error
    return module


def reseal(contracts: Path, repo: Path) -> int:
    """Re-pin the whole ledger chain against the current bytes on disk.

    Two writes, in this order:

    1. ``contract-manifest.json``: every ``objects[].sha256`` and
       ``schema.object_count`` recomputed from disk;
    2. ``manifest.sha256``: regenerated with the clone's own ``hashes`` module, so
       it also covers the (just rewritten) object ledger.

    This is what "a deliberate attacker would do" looks like, and it is required
    by design §5-T04 要点 ①: without it every case would only re-prove that
    ``run.py check`` hashes files.

    Args:
        contracts: Contracts directory inside the clone.
        repo: Clone repository root.

    Returns:
        How many artifact digests were re-pinned.

    Raises:
        CaseError: A recorded object vanished from disk, or a write failed.
    """
    hashes = _load_clone_hashes(repo)
    manifest_path = contracts / "contract-manifest.json"
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise CaseError(f"cannot read {manifest_path.as_posix()}: {error}") from error
    except json.JSONDecodeError as error:
        raise CaseError(f"invalid JSON in {manifest_path.as_posix()}: {error}") from error
    if not isinstance(document, dict):
        raise CaseError(f"{manifest_path.as_posix()}: top level is not an object")

    objects = document.get("objects")
    if not isinstance(objects, list):
        raise CaseError(f"{manifest_path.as_posix()}: missing objects[] array")

    resealed = 0
    for item in objects:
        if not isinstance(item, dict):
            raise CaseError(f"{manifest_path.as_posix()}: malformed objects[] entry")
        relative = str(item.get("path", ""))
        target = contracts / Path(*relative.split("/"))
        if not target.is_file():
            raise CaseError(
                f"{relative}: recorded in the object ledger but missing on disk "
                "(a case must not delete contract files)"
            )
        item["sha256"] = hashes.sha256_file(target)
        resealed += 1

    schema_block = document.get("schema")
    if isinstance(schema_block, dict):
        schema_block["object_count"] = len(objects)

    try:
        manifest_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        hashes.write_manifest(contracts)
    except OSError as error:
        raise CaseError(f"cannot re-pin the ledger chain: {error}") from error
    return resealed


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------


@dataclass
class InjectionResult:
    """The judgement for one case.

    Attributes:
        case_id: Registry id.
        target_gate: Gate key that had to go red.
        gate_exit: Observed exit code of the target gate.
        red: Whether the gate reported a red at all.
        matched: Declared tokens that appeared in the output.
        missing: Declared tokens that never appeared (empty ⇒ reason correct).
        control_exit: Exit code of the same gate on the *untouched* clone.
        integrity_exit: Exit code of ``run.py check`` on the tampered clone.
        sibling: ``{gate_key: exit_code}`` for gates that had to stay green.
        mutation: One-line description of what the mutator changed.
        verdict: ``PASS`` / ``FAKE-GREEN`` / ``FALSE-REFUTATION`` / ``UNEVALUABLE`` / ``INVALID``.
        exit_code: ``0`` / ``10`` / ``11`` / ``12``.
        note: Why the verdict is what it is.
        output_tail: The red-carrying lines of the target gate output (evidence).
        output_full: The complete target gate output (only printed with ``--full``).
        scratch: Scratch directory used by this case.
        seconds: Wall-clock duration.
    """

    case_id: str
    target_gate: str
    gate_exit: int
    red: bool
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    control_exit: int
    integrity_exit: int
    sibling: dict[str, int] = field(default_factory=dict)
    mutation: str = ""
    verdict: str = "UNEVALUABLE"
    exit_code: int = _gate_io.EXIT_CASE_UNEVALUABLE
    note: str = ""
    output_tail: str = ""
    output_full: str = ""
    scratch: str = ""
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view (``--json``).

        Returns:
            The record as a plain dict.
        """
        return {
            "case_id": self.case_id,
            "target_gate": self.target_gate,
            "gate_exit": self.gate_exit,
            "red": self.red,
            "matched_tokens": list(self.matched),
            "missing_tokens": list(self.missing),
            "control_exit": self.control_exit,
            "integrity_exit": self.integrity_exit,
            "sibling_exits": dict(self.sibling),
            "mutation": self.mutation,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "note": self.note,
            "output_tail": self.output_tail,
            "output_full": self.output_full,
            "scratch": self.scratch,
            "seconds": round(self.seconds, 3),
        }


def judge(
    case: inject_cases.InjectionCase,
    *,
    gate_exit: int,
    red: bool,
    output: str,
    integrity_exit: int | None,
    sibling: dict[str, int] | None = None,
) -> tuple[str, int, tuple[str, ...], tuple[str, ...], str]:
    """Decide the verdict for one case from raw observations.

    Split out of :func:`run_case` on purpose: the decision table is the part that
    must never be relaxed, so it is unit-tested by ``--self-test`` without any
    cloning or subprocess.

    Decision order (first match wins):

    1. empty expectation set -> ``INVALID`` / ``12`` (no expectation is not a pass);
    2. no red at all: exit ``0`` -> ``FAKE-GREEN`` / ``10`` (the injected red did
       not happen); any other non-red exit -> ``UNEVALUABLE`` / ``12``;
    3. any declared token missing -> ``FALSE-REFUTATION`` / ``11``;
    4. a sibling gate that had to stay green went red -> ``UNEVALUABLE`` / ``12``
       (the case's premise is false; this is *not* a pass);
    5. ``run.py check`` red although the case claims integrity -> ``UNEVALUABLE`` / ``12``;
    6. otherwise -> ``PASS`` / ``0``.

    Args:
        case: The case being judged.
        gate_exit: Target gate exit code (for the evidence rows only).
        red: Whether that exit code means "this gate found a difference" for
            *this* gate (see :attr:`GateSpec.red_codes` — it is ``1`` for parity
            but ``2`` for ``verify_semantics`` and ``20`` for the oracle).
        output: Combined stdout/stderr of the target gate.
        integrity_exit: ``run.py check`` exit code, or ``None`` when the case does
            not claim integrity.
        sibling: Exit codes of the gates in ``case.must_stay_green``.

    Returns:
        ``(verdict, exit_code, matched, missing, note)``.
    """
    siblings = sibling or {}
    tokens = tuple(case.must_be_red)
    matched = tuple(token for token in tokens if token in output)
    missing = tuple(token for token in tokens if token not in output)

    if not tokens:
        return (
            "INVALID",
            _gate_io.EXIT_CASE_UNEVALUABLE,
            (),
            (),
            "must_be_red is empty: a case with no declared expectation is INVALID, never a pass",
        )
    if not red:
        if gate_exit == 0:
            return (
                "FAKE-GREEN",
                _gate_io.EXIT_FAKE_GREEN,
                matched,
                missing,
                f"target gate exited 0 on a tampered clone (must_be_red={list(tokens)})",
            )
        return (
            "UNEVALUABLE",
            _gate_io.EXIT_CASE_UNEVALUABLE,
            matched,
            missing,
            f"target gate did not evaluate the case (exit={gate_exit})",
        )
    if missing:
        return (
            "FALSE-REFUTATION",
            _gate_io.EXIT_FALSE_REFUTATION,
            matched,
            missing,
            f"red, but the declared reason never appeared: missing={list(missing)}",
        )
    red_siblings = {key: code for key, code in siblings.items() if code != 0}
    if red_siblings:
        return (
            "UNEVALUABLE",
            _gate_io.EXIT_CASE_UNEVALUABLE,
            matched,
            missing,
            f"gate(s) that had to stay green went red on the clone: {red_siblings}",
        )
    if integrity_exit is not None and integrity_exit != 0:
        return (
            "UNEVALUABLE",
            _gate_io.EXIT_CASE_UNEVALUABLE,
            matched,
            missing,
            "run.py check went red on the clone although the case claims integrity "
            "(toolkit constants not synced? see design §11.1)",
        )
    return (
        "PASS",
        _gate_io.EXIT_OK,
        matched,
        missing,
        "red for the declared reason; integrity stayed green on the clone",
    )


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------


def run_case(
    case: inject_cases.InjectionCase,
    *,
    repo_root: Path,
    legacy_root: Path,
    scratch_root: Path,
    timeout_s: float,
    keep: bool,
    verbose: bool,
) -> InjectionResult:
    """Evaluate one injection case end to end.

    Args:
        case: Registry entry.
        repo_root: Real repository root (cloned, never written).
        legacy_root: Read-only legacy root passed to the gates that need it.
        scratch_root: Directory in which the per-case clone is created.
        timeout_s: Hard timeout per gate invocation.
        keep: Keep the scratch directory after the run.
        verbose: Echo the clone paths and control runs.

    Returns:
        The :class:`InjectionResult` (never raises for an ordinary case failure).
    """
    started = time.monotonic()
    gate_key = case.target_gate
    if gate_key not in GATES:
        return InjectionResult(
            case_id=case.case_id,
            target_gate=gate_key,
            gate_exit=-1,
            red=False,
            matched=(),
            missing=tuple(case.must_be_red),
            control_exit=-1,
            integrity_exit=-1,
            verdict="UNEVALUABLE",
            exit_code=_gate_io.EXIT_CASE_UNEVALUABLE,
            note=f"unknown target gate {gate_key!r} (known: {sorted(GATES)})",
        )

    scratch = Path(tempfile.mkdtemp(prefix=f"wbtime-inject-{case.case_id}-", dir=str(scratch_root)))
    clone = scratch / "repo"
    contracts = clone / "contracts"

    try:
        try:
            clone_repo(repo_root, clone, GATES[gate_key].clone_dirs)
            if GATES[gate_key].prepare is not None:
                GATES[gate_key].prepare(clone, repo_root)
        except CaseError as error:
            return InjectionResult(
                case_id=case.case_id,
                target_gate=gate_key,
                gate_exit=-1,
                red=False,
                matched=(),
                missing=tuple(case.must_be_red),
                control_exit=-1,
                integrity_exit=-1,
                verdict="UNEVALUABLE",
                exit_code=_gate_io.EXIT_CASE_UNEVALUABLE,
                note=f"clone/prepare failed: {error}",
                scratch=scratch.as_posix(),
                seconds=time.monotonic() - started,
            )
        if verbose:
            _gate_io.log(TAG, f"  clone: {clone.as_posix()}")

        # Step 0 — the control run.  A gate that is already red on an untouched
        # clone would make the whole case meaningless, so this is checked first.
        control = run_gate(gate_key, clone, contracts, legacy_root, timeout_s)
        if control.exit_code != 0:
            return InjectionResult(
                case_id=case.case_id,
                target_gate=gate_key,
                gate_exit=control.exit_code,
                red=True,
                matched=(),
                missing=tuple(case.must_be_red),
                control_exit=control.exit_code,
                integrity_exit=-1,
                verdict="UNEVALUABLE",
                exit_code=_gate_io.EXIT_CASE_UNEVALUABLE,
                note=(
                    "control run is already red on the untouched clone: "
                    f"exit={control.exit_code} :: {control.tail(4)}"
                    + (
                        # The spike carrier is red *by design* until the V0.3.1
                        # implementation lands.  Without this marker the note
                        # would read like a broken case rather than like the
                        # "implementation missing" state it actually is — and
                        # "unevaluable because red" must never be confused with
                        # "unevaluable because the case is mis-wired".
                        f" | {inject_cases.MARKER_IMPL_NOT_LANDED}: 判据载体当前处在"
                        "「生产实现未落地」的预期红证状态（红证见 "
                        "docs/V1.0/V0.3.1-子Agent委派M1/03-台账/spike-red-evidence-2026-10-23.md）；"
                        "待实现落地、控制组转绿后本用例方可判 —— 12 不是绿"
                        if GATES[gate_key].interpreter == "node"
                        else ""
                    )
                ),
                output_tail=control.tail(12),
                scratch=scratch.as_posix(),
                seconds=time.monotonic() - started,
            )

        # Step 1 — tamper.
        try:
            mutation = case.mutator(contracts, clone)
        except inject_cases.MutationError as error:
            return InjectionResult(
                case_id=case.case_id,
                target_gate=gate_key,
                gate_exit=-1,
                red=False,
                matched=(),
                missing=tuple(case.must_be_red),
                control_exit=control.exit_code,
                integrity_exit=-1,
                verdict="UNEVALUABLE",
                exit_code=_gate_io.EXIT_CASE_UNEVALUABLE,
                note=f"mutation could not be applied: {error}",
                scratch=scratch.as_posix(),
                seconds=time.monotonic() - started,
            )

        # Step 2 — re-pin the whole ledger chain (design §5-T04 要点 ①).
        #
        # Skipped for gates that judge *source code* instead of `contracts/`
        # artifacts: there is no ledger to re-pin, and rewriting the clone's
        # contract digests would be noise in the evidence line.
        if GATES[gate_key].reseals:
            try:
                resealed = reseal(contracts, clone)
            except CaseError as error:
                return InjectionResult(
                    case_id=case.case_id,
                    target_gate=gate_key,
                    gate_exit=-1,
                    red=False,
                    matched=(),
                    missing=tuple(case.must_be_red),
                    control_exit=control.exit_code,
                    integrity_exit=-1,
                    mutation=mutation,
                    verdict="UNEVALUABLE",
                    exit_code=_gate_io.EXIT_CASE_UNEVALUABLE,
                    note=f"re-pin failed: {error}",
                    scratch=scratch.as_posix(),
                    seconds=time.monotonic() - started,
                )
        else:
            resealed = 0

        # Step 3 — the target gate.
        target = run_gate(gate_key, clone, contracts, legacy_root, timeout_s)

        # Step 4 — the gates that had to stay green (the "right gate" argument).
        sibling: dict[str, int] = {}
        for sibling_key in case.must_stay_green:
            result = run_gate(sibling_key, clone, contracts, legacy_root, timeout_s)
            sibling[sibling_key] = result.exit_code
            if verbose:
                _gate_io.log(
                    TAG,
                    f"  sibling {sibling_key}: exit={result.exit_code} :: {result.tail(2)}",
                )

        # Step 5 — integrity (``run.py check`` must not see the tamper).
        integrity_exit: int | None = None
        if case.checks_integrity:
            integrity = run_gate("run_check", clone, contracts, legacy_root, timeout_s)
            integrity_exit = integrity.exit_code
            if verbose:
                _gate_io.log(TAG, f"  integrity run.py check: exit={integrity.exit_code}")

        verdict, exit_code, matched, missing, note = judge(
            case,
            gate_exit=target.exit_code,
            red=target.exit_code in GATES[gate_key].red_codes,
            output=target.output,
            integrity_exit=integrity_exit,
            sibling=sibling,
        )
        return InjectionResult(
            case_id=case.case_id,
            target_gate=gate_key,
            gate_exit=target.exit_code,
            red=target.exit_code != 0,
            matched=matched,
            missing=missing,
            control_exit=control.exit_code,
            integrity_exit=integrity_exit if integrity_exit is not None else -1,
            sibling=sibling,
            mutation=mutation + f" | re-pinned {resealed} object digest(s)",
            verdict=verdict,
            exit_code=exit_code,
            note=note,
            output_tail=target.red_lines(8),
            output_full=target.output,
            scratch=scratch.as_posix(),
            seconds=time.monotonic() - started,
        )
    finally:
        if keep:
            _gate_io.log(TAG, f"  kept: {scratch.as_posix()}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_case(
    result: InjectionResult, case: inject_cases.InjectionCase, *, full: bool = False
) -> None:
    """Print one case as a block of evidence lines.

    Args:
        result: The judgement.
        case: The registry entry (for the expectation prose).
        full: Also echo the complete target-gate output (used to quote evidence
            into ``03-台账/反例注入记录.md``).
    """
    _gate_io.log(TAG, f"case={result.case_id} dod={case.dod} gate={result.target_gate}")
    _gate_io.log(TAG, f"  expect: {case.expected_reason}")
    _gate_io.log(TAG, f"  mutate: {result.mutation}")
    _gate_io.log(
        TAG,
        f"  control(unmutated)=exit {result.control_exit}  "
        f"target(tampered)=exit {result.gate_exit}  "
        f"tokens {len(result.matched)}/{len(case.must_be_red)} matched",
    )
    if result.sibling:
        joined = ", ".join(f"{key}={code}" for key, code in sorted(result.sibling.items()))
        _gate_io.log(TAG, f"  sibling gates that must stay green: {joined}")
    _gate_io.log(
        TAG,
        f"  integrity: run.py check exit={result.integrity_exit} "
        f"({'GREEN on the clone' if result.integrity_exit == 0 else 'NOT GREEN'})",
    )
    for token in result.missing:
        _gate_io.log(TAG, f"  MISSING TOKEN: {token!r}")
    if result.output_tail:
        _gate_io.log(TAG, f"  red output: {result.output_tail}")
    if full and result.output_full:
        _gate_io.log(TAG, "  ---- target gate output (verbatim) ----")
        for line in result.output_full.splitlines():
            _gate_io.log(TAG, f"  | {line}")
    _gate_io.log(TAG, f"  VERDICT: {result.verdict} (exit {result.exit_code}) — {result.note}")


def summarize(results: Sequence[InjectionResult]) -> int:
    """Fold per-case exit codes into one process exit code.

    ``10`` (fake green) outranks ``11`` (false refutation), which outranks ``12``
    (not evaluable): the most serious finding must be the number CI reports.

    Args:
        results: The per-case results.

    Returns:
        ``0`` when every case passed, otherwise the most serious code.
    """
    codes = {result.exit_code for result in results}
    for code in (
        _gate_io.EXIT_FAKE_GREEN,
        _gate_io.EXIT_FALSE_REFUTATION,
        _gate_io.EXIT_CASE_UNEVALUABLE,
    ):
        if code in codes:
            return code
    return _gate_io.EXIT_OK


# ---------------------------------------------------------------------------
# Self-test (judge only — no cloning, no subprocess)
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Prove the decision table is not vacuous.

    Eight probes, all unit-level on :func:`judge` plus one registry audit:

    1. green gate on a tampered clone -> ``10`` (fake green);
    2. red with the wrong reason -> ``11``;
    3. empty ``must_be_red`` -> ``12`` (INVALID, never a pass);
    4. correct red but ``run.py check`` also red -> ``12`` (premise false);
    5. correct red but a sibling gate red -> ``12`` (premise false);
    6. correct red + integrity green -> ``0``;
    7. a usage error (not a red for that gate) -> ``12``;
    8. ``verify_semantics``'s red code ``2`` must count as a red, not as usage;
    plus registry sanity (>= 5 cases, unique ids, known gates, non-empty
    expectations).

    Returns:
        ``0`` when every probe behaves, ``9`` otherwise.
    """
    cases = inject_cases.CASES
    sample = cases[0]
    probes: list[tuple[str, bool, str]] = []

    def record(label: str, actual: int, expected: int, detail: str = "") -> None:
        probes.append((f"{label} (want {expected}, got {actual}{'; ' + detail if detail else ''})", actual == expected, detail))

    verdict, code, _, _, _ = judge(
        sample, gate_exit=0, red=False, output="VERDICT: PASS", integrity_exit=0
    )
    record("green-on-tampered-is-fake-green", code, _gate_io.EXIT_FAKE_GREEN, verdict)

    verdict, code, _, _, _ = judge(
        sample, gate_exit=1, red=True, output="DIFF something-else: x", integrity_exit=0
    )
    record("red-for-wrong-reason", code, _gate_io.EXIT_FALSE_REFUTATION, verdict)

    hollow = inject_cases.InjectionCase(
        case_id="__empty__",
        dod="self-test",
        target_gate=sample.target_gate,
        expected_reason="none",
        description="no expectation declared",
        must_be_red=(),
        mutator=sample.mutator,
    )
    verdict, code, _, _, _ = judge(
        hollow, gate_exit=0, red=False, output="VERDICT: PASS", integrity_exit=0
    )
    record("empty-expectations-are-invalid", code, _gate_io.EXIT_CASE_UNEVALUABLE, verdict)

    good_output = " ".join(sample.must_be_red)
    verdict, code, _, _, _ = judge(
        sample, gate_exit=1, red=True, output=good_output, integrity_exit=1
    )
    record("integrity-red-invalidates-case", code, _gate_io.EXIT_CASE_UNEVALUABLE, verdict)

    verdict, code, _, _, _ = judge(
        sample,
        gate_exit=1,
        red=True,
        output=good_output,
        integrity_exit=0,
        sibling={"verify_semantics": 2},
    )
    record("sibling-red-invalidates-case", code, _gate_io.EXIT_CASE_UNEVALUABLE, verdict)

    verdict, code, _, _, _ = judge(
        sample,
        gate_exit=1,
        red=True,
        output=good_output,
        integrity_exit=0,
        sibling={"verify_semantics": 0},
    )
    record("correct-red-is-pass", code, _gate_io.EXIT_OK, verdict)

    verdict, code, _, _, _ = judge(
        sample, gate_exit=2, red=False, output="usage error", integrity_exit=None
    )
    record("usage-error-is-unevaluable", code, _gate_io.EXIT_CASE_UNEVALUABLE, verdict)

    verdict, code, _, _, _ = judge(
        sample, gate_exit=2, red=True, output=good_output, integrity_exit=0
    )
    record("verify-semantics-red-code-2-is-a-real-red", code, _gate_io.EXIT_OK, verdict)

    # Registry sanity: an empty or mis-wired registry must not look like success.
    ids = [case.case_id for case in cases]
    # The registry grew from 5 contract cases to 5 + 4 V031 cases (3 spike
    # carriers + 1 watermark carrier).  A count change alone is not a
    # regression, but an *unexplained* one is: the probe pins the exact size so
    # an accidental case loss cannot hide behind "more cases were added anyway".
    record("registry-has-9-cases", len(cases), 9, f"ids={ids}")
    record("registry-ids-unique", len(set(ids)) == len(ids), True)
    record(
        "registry-targets-known-gates",
        all(case.target_gate in GATES for case in cases),
        True,
        f"gates={[case.target_gate for case in cases]}",
    )
    record(
        "registry-expectations-nonempty",
        all(case.must_be_red for case in cases),
        True,
    )
    record(
        "registry-gate-keys-match-engine-table",
        set(inject_cases.GATE_KEYS) == set(GATES),
        True,
        f"registry={sorted(inject_cases.GATE_KEYS)} engine={sorted(GATES)}",
    )
    record(
        "registry-stay-green-gates-known",
        all(key in GATES for case in cases for key in case.must_stay_green),
        True,
    )

    _gate_io.log(TAG, "self-test: decision table + registry")
    failures = 0
    for description, ok, _ in probes:
        _gate_io.log(TAG, f"  {'PASS' if ok else 'FAIL'}  {description}")
        if not ok:
            failures += 1
    _gate_io.log(TAG, f"self-test: {len(probes) - failures}/{len(probes)} passed")
    if failures:
        _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({failures} probe(s))")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, "SELFTEST VERDICT: PASS (the judge can say 0/10/11/12 for the right inputs)")
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
        prog="inject_counterexample.py",
        description=(
            "Apply named contract tampers to a temporary clone, re-pin the whole "
            "ledger chain, and insist the target gate goes red for the declared "
            "reason while integrity stays green."
        ),
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", metavar="ID", action="append", default=None, help="case id (repeatable)")
    selection.add_argument("--all", action="store_true", help="run every registered case")
    selection.add_argument("--list", action="store_true", help="list the registry and exit")
    parser.add_argument(
        "--exclude-case",
        metavar="ID",
        action="append",
        default=None,
        help=(
            "drop a case from the selection (repeatable).  ONLY for the transitional "
            "window in which a suite's production implementation has not landed yet: "
            "excluded cases are re-listed as EXCLUDED in the summary so an exclusion "
            "can never silently hide a red.  Prefer fixing the implementation."
        ),
    )
    parser.add_argument("--keep", action="store_true", help="keep the per-case scratch clones")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--self-test", action="store_true", help="unit-test the decision table (exit 9 on failure)")
    parser.add_argument("--scratch-root", type=Path, default=None, metavar="DIR", help="where to create clones (default: a temp dir)")
    parser.add_argument("--legacy-root", type=Path, default=None, metavar="DIR", help="read-only legacy root (default: $E2E_LEGACY_ROOT or D:/WBT/WBTimeAI_old)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="per-gate timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="echo clone paths, control runs and sibling exits")
    parser.add_argument("--full", action="store_true", help="echo the complete target-gate output per case")
    return parser


def _list_registry(as_json: bool) -> int:
    """Print the registry (``--list``).

    Args:
        as_json: Emit JSON instead of log lines.

    Returns:
        ``0``.
    """
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "case_id": case.case_id,
                        "dod": case.dod,
                        "target_gate": case.target_gate,
                        "expected_reason": case.expected_reason,
                        "must_be_red": list(case.must_be_red),
                        "must_stay_green": list(case.must_stay_green),
                        "checks_integrity": case.checks_integrity,
                    }
                    for case in inject_cases.CASES
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return _gate_io.EXIT_OK
    _gate_io.log(TAG, f"registry: {len(inject_cases.CASES)} case(s); victims={inject_cases.victims()}")
    for index, case in enumerate(inject_cases.CASES, start=1):
        _gate_io.log(TAG, f"  {index}. {case.case_id}  ({case.dod})")
        _gate_io.log(TAG, f"     gate    : {case.target_gate} — {GATES[case.target_gate].label}")
        _gate_io.log(TAG, f"     expect  : {case.expected_reason}")
        _gate_io.log(TAG, f"     tokens  : {list(case.must_be_red)}")
        stay = list(case.must_stay_green) or ["(none)"]
        _gate_io.log(TAG, f"     green   : {stay}   integrity={'yes' if case.checks_integrity else 'no'}")
    return _gate_io.EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``10`` / ``11`` / ``12`` / ``2`` / ``9`` (design §3.3).
    """
    parser = _build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    if arguments.self_test:
        return _self_test()
    if arguments.list:
        return _list_registry(as_json=bool(arguments.json))

    repo_root = _SCRIPTS_DIR.parent
    legacy_root = (
        Path(arguments.legacy_root).expanduser().resolve()
        if arguments.legacy_root
        else _gate_io.GatePaths.resolve(repo_root=repo_root).legacy_root
    )
    if not legacy_root.is_dir():
        _gate_io.log(TAG, f"INVALID: legacy root not available ({legacy_root.as_posix()}) — no external truth, no injection")
        return _gate_io.EXIT_CASE_UNEVALUABLE

    if arguments.all:
        selected = list(inject_cases.CASES)
    elif arguments.case:
        unknown = [name for name in arguments.case if name not in inject_cases.CASE_BY_ID]
        if unknown:
            _gate_io.log(TAG, f"ERROR: unknown case(s) {unknown}; try --list")
            return _gate_io.EXIT_USAGE
        selected = [inject_cases.CASE_BY_ID[name] for name in arguments.case]
    else:
        _gate_io.log(TAG, "ERROR: choose --all, --case ID, --list or --self-test")
        return _gate_io.EXIT_USAGE

    excluded = list(arguments.exclude_case or [])
    if excluded:
        unknown = [name for name in excluded if name not in inject_cases.CASE_BY_ID]
        if unknown:
            _gate_io.log(TAG, f"ERROR: unknown --exclude-case id(s) {unknown}; try --list")
            return _gate_io.EXIT_USAGE
        before = len(selected)
        selected = [case for case in selected if case.case_id not in excluded]
        for name in excluded:
            _gate_io.log(TAG, f"EXCLUDED (transitional opt-out, not a pass): {name}")
        _gate_io.log(TAG, f"selection: {before} -> {len(selected)} case(s) after exclusions")

    if not selected:  # pragma: no cover - argparse makes this unreachable
        _gate_io.log(TAG, "INVALID: empty case selection (K-11)")
        return _gate_io.EXIT_CASE_UNEVALUABLE

    scratch_root = (
        Path(arguments.scratch_root).expanduser().resolve()
        if arguments.scratch_root
        else Path(tempfile.mkdtemp(prefix="wbtime-inject-root-"))
    )
    scratch_root.mkdir(parents=True, exist_ok=True)

    _gate_io.log(
        TAG,
        f"run: {len(selected)} case(s)  repo={repo_root.as_posix()}  legacy={legacy_root.as_posix()}  "
        f"scratch={scratch_root.as_posix()}  at {_gate_io.utc_now_iso()}",
    )

    results: list[InjectionResult] = []
    try:
        for case in selected:
            result = run_case(
                case,
                repo_root=repo_root,
                legacy_root=legacy_root,
                scratch_root=scratch_root,
                timeout_s=float(arguments.timeout),
                keep=bool(arguments.keep),
                verbose=bool(arguments.verbose),
            )
            results.append(result)
            if not arguments.json:
                render_case(result, case, full=bool(arguments.full))
    finally:
        if not arguments.keep:
            shutil.rmtree(scratch_root, ignore_errors=True)

    exit_code = summarize(results)
    passed = sum(1 for result in results if result.exit_code == _gate_io.EXIT_OK)

    if arguments.json:
        print(
            json.dumps(
                {
                    "generated_at": _gate_io.utc_now_iso(),
                    "repo_root": repo_root.as_posix(),
                    "legacy_root": legacy_root.as_posix(),
                    "cases": [result.as_dict() for result in results],
                    "summary": {
                        "total": len(results),
                        "passed": passed,
                        "fake_green": sum(1 for r in results if r.exit_code == _gate_io.EXIT_FAKE_GREEN),
                        "false_refutation": sum(1 for r in results if r.exit_code == _gate_io.EXIT_FALSE_REFUTATION),
                        "unevaluable": sum(1 for r in results if r.exit_code == _gate_io.EXIT_CASE_UNEVALUABLE),
                        "exit_code": exit_code,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    _gate_io.log(TAG, f"SUMMARY: {passed}/{len(results)} case(s) went red for the declared reason")
    if exit_code == _gate_io.EXIT_OK:
        _gate_io.log(TAG, "VERDICT: PASS (0) — every injected red happened, for the right reason")
    elif exit_code == _gate_io.EXIT_FAKE_GREEN:
        _gate_io.log(TAG, "VERDICT: FAKE-GREEN (10) — at least one tampered clone stayed green")
    elif exit_code == _gate_io.EXIT_FALSE_REFUTATION:
        _gate_io.log(TAG, "VERDICT: FALSE-REFUTATION (11) — red, but not for the declared reason")
    else:
        _gate_io.log(TAG, "VERDICT: UNEVALUABLE (12) — at least one case could not be judged")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
