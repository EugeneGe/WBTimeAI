"""T1-01 / ⑤-a — the frontend zero-change gate: prove that ``apps/web/src/**`` is
byte-identical to the archived original, and prove it by comparison, not by
memory.

What ⑤-a has to answer
----------------------
DoD#3 says "前端业务代码 0 改动".  Read literally that is a claim about 243
files, and a claim about files can only be settled by comparing files.  So this
gate answers four separate questions, and it answers each one out loud:

==============================  ===============================================
per-file ``git hash-object``    every file on the candidate side must hash to
                                the same blob as its namesake on the archived
                                side.  242/243 equal is 0, not "基本相等".
raw-bytes cross-check           a hash taken through git is a hash of what git
                                would *store*, and git stores the output of
                                clean filters.  The two repositories carry
                                different ``.gitattributes`` (the legacy tree
                                has ``* text=auto eol=lf``), so a lone
                                ``git hash-object`` equality can in principle
                                be produced by two files that differ on disk.
                                The raw digest is what closes that hole; a
                                divergence between the two verdicts is
                                ``INVALID(filter-masked)``, never a pass.
``git diff --stat``             after the migration commit, any edit to a
                                tracked file under ``apps/web/src/**`` has to
                                show up here.  This is reported together with
                                whether the tree is tracked at all, because an
                                empty diff over an *untracked* tree proves
                                nothing (see the MIN_FILES note).
``MIN_FILES`` floor             an empty (or nearly empty) scan surface must be
                                ``INVALID(EMPTY)`` and exit non-zero.  An empty
                                glob satisfies "every file matches" vacuously;
                                that is the K-11 defect this file exists to make
                                impossible to reintroduce.
==============================  ===============================================

Three-state reporting (per root, never folded)
----------------------------------------------
Every root reports exactly one of ``OK(n)`` / ``ABSENT(declared; owner=...)`` /
``INVALID(reason)`` **on its own line**, and the summary counts the effective
roots.  Folding three roots into one boolean is how a dead root hides behind two
healthy ones.

Roots::

    apps/web/src/**              the candidate (required for ⑤-a)
    _old/apps/web/src/**         the read-only archive (required: it *is* the
                                 baseline; without it ⑤-a is unanswerable, so its
                                 absence is INVALID, never a skip)
    contracts/frontend-baseline/**  this task's other half — genuinely allowed
                                 not to exist yet, and therefore the one root
                                 where ``ABSENT(declared)`` is a legal state

Absence is only legal when the root is **registered**: an absent root that no
declared-absence registry knows about is ``INVALID(unregistered-absence)``, not
a skip.

Exit codes::

    0   PASS (or PARTIAL with ``--allow-declared-absence``)
    1   violation: hash/bytes mismatch, non-empty diff, INVALID root, or PARTIAL
        without the allowance flag
    2   usage error, or an artifact that cannot be loaded
    9   ``--self-test`` failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)

__all__ = [
    "TAG",
    "MIN_FILES",
    "SCAN_ROOTS",
    "REQUIRED_ROOTS",
    "ROOT_MIN_FILES",
    "RootReport",
    "collect_relative_files",
    "compare_trees",
    "evaluate",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "fdiff"

#: Lower bound on files a source root must really contain.  Declared **once** in
#: the whole file on purpose — this assignment is the mutation anchor for the
#: positive proof in ``--self-test`` case 5 (with the floor at 0 an emptied tree
#: reports green, which is exactly what the floor exists to prevent).
MIN_FILES = 200

#: Suffix beneath the two comparison roots.  ⑤-a constrains the business code,
#: not the config files sitting next to it.
WEB_SRC_REL: Final[str] = "apps/web/src"

#: The three scan roots, in report order.
ROOT_NEW: Final[str] = "apps/web/src/**"
ROOT_LEGACY: Final[str] = "_old/apps/web/src/**"
ROOT_BASELINE: Final[str] = "contracts/frontend-baseline/**"

SCAN_ROOTS: Final[tuple[str, ...]] = (ROOT_NEW, ROOT_LEGACY, ROOT_BASELINE)

#: Roots whose absence makes ⑤-a unanswerable.  They may never report ABSENT.
REQUIRED_ROOTS: Final[frozenset[str]] = frozenset({ROOT_NEW, ROOT_LEGACY})

#: Per-root minimum file count.
ROOT_MIN_FILES: Final[dict[str, int]] = {
    ROOT_NEW: MIN_FILES,
    ROOT_LEGACY: MIN_FILES,
    ROOT_BASELINE: 1,
}

#: States a root report can carry.
STATE_OK: Final[str] = "OK"
STATE_ABSENT: Final[str] = "ABSENT"
STATE_INVALID: Final[str] = "INVALID"

#: Where the declared-absence registry lives (found by glob: the version
#: directory name must never be hard-coded).
REGISTRY_GLOB: Final[str] = "docs/**/03-台账/*-扫描面登记.md"

#: Vendored dependencies are not our source.
NODE_MODULES: Final[str] = "node_modules"

#: How many paths to hand to one ``git hash-object`` invocation.  Windows
#: command lines are far shorter than Linux ones.
HASH_CHUNK: Final[int] = 200


@dataclass(frozen=True)
class RootReport:
    """One root's three-state result.

    Attributes:
        root: Canonical root pattern.
        state: ``OK`` / ``ABSENT`` / ``INVALID``.
        files: How many files the scan really matched (0 when absent).
        declared_owner: Owner from the registry (``-`` when unregistered).
        reason: Human readable explanation of a non-OK state.
    """

    root: str
    state: str
    files: int
    declared_owner: str = "-"
    reason: str = ""

    @property
    def effective(self) -> bool:
        """Whether this root really took effect (``OK`` and non-vacuous)."""
        return self.state == STATE_OK

    def render(self) -> str:
        """Render the per-root evidence line.

        Returns:
            e.g. ``root apps/web/src/**  OK(files=243)``.
        """
        if self.state == STATE_OK:
            body = f"OK(files={self.files})"
        elif self.state == STATE_ABSENT:
            body = f"ABSENT(declared; owner={self.declared_owner})"
        else:
            body = f"INVALID({self.reason})"
        return f"root {self.root:<32} {body}"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def collect_relative_files(directory: Path) -> list[str]:
    """List every regular file under ``directory`` as a POSIX relative path.

    Args:
        directory: Tree to walk.  A missing directory yields an empty list
            (the caller distinguishes "absent" from "empty" by ``is_dir``).

    Returns:
        Sorted relative paths, ``node_modules`` excluded.
    """
    if not directory.is_dir():
        return []
    found: list[str] = []
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if NODE_MODULES in path.relative_to(directory).parts:
            continue
        found.append(path.relative_to(directory).as_posix())
    return sorted(found)


def _raw_digests(directory: Path, relatives: Sequence[str]) -> dict[str, str]:
    """SHA-256 the on-disk bytes of the listed files.

    Args:
        directory: Tree holding the files.
        relatives: POSIX relative paths inside it.

    Returns:
        relative → hex digest.  Unreadable files are recorded as ``"<unreadable>"``
        rather than dropped, so a permission problem surfaces as a mismatch.
    """
    digests: dict[str, str] = {}
    for relative in relatives:
        target = directory / Path(*relative.split("/"))
        try:
            digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            digests[relative] = "<unreadable>"
    return digests


def _git_hash_objects(relatives: Sequence[str], cwd: Path) -> dict[str, str]:
    """Run ``git hash-object`` over the listed files, in chunks.

    The ``cwd`` matters: git resolves each relative path against it and picks the
    containing repository (and therefore that repository's ``.gitattributes``)
    from there.  The two sides of ⑤-a live in two different repositories, so they
    must be hashed from their own directories.

    Args:
        relatives: POSIX relative paths inside ``cwd``.
        cwd: Directory to run from.

    Returns:
        relative → blob hash.  Files git could not hash are recorded as
        ``"<git-error>"``; a caller that ignores those would be scoring a
        comparison that never happened.

    Raises:
        RuntimeError: git is unavailable or failed on a whole chunk.
    """
    digests: dict[str, str] = {}
    total = len(relatives)
    for start in range(0, max(total, 1), HASH_CHUNK):
        if start >= total:
            break
        chunk = list(relatives[start : start + HASH_CHUNK])
        try:
            completed = subprocess.run(
                ["git", "hash-object", *chunk],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:  # git not installed / not executable
            raise RuntimeError(f"git unavailable: {exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"git hash-object failed (rc={completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != len(chunk):
            raise RuntimeError(
                f"git hash-object returned {len(lines)} hashes for {len(chunk)} files"
            )
        for relative, digest in zip(chunk, lines):
            digests[relative] = digest
    return digests


#: The runner used by :func:`compare_trees`.  ``--self-test`` swaps in a stub so
#: the five injection cases stay deterministic and need no git repository.
_GIT_RUNNER: Callable[[Sequence[str], Path], dict[str, str]] = _git_hash_objects


@dataclass
class Comparison:
    """The outcome of comparing the two source trees.

    Attributes:
        common: Files present on both sides.
        missing_in_candidate: Present in the archive, absent on our side.
        missing_in_legacy: Present on our side, absent in the archive.
        blob_mismatch: Files whose ``git hash-object`` differs.
        raw_mismatch: Files whose on-disk bytes differ.
        filter_masked: Files where the two verdicts disagree — bytes differ but
            git says equal, i.e. a clean filter hid a real change.
    """

    common: int = 0
    missing_in_candidate: list[str] = field(default_factory=list)
    missing_in_legacy: list[str] = field(default_factory=list)
    blob_mismatch: list[str] = field(default_factory=list)
    raw_mismatch: list[str] = field(default_factory=list)
    filter_masked: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Whether the two trees are really identical."""
        return not (
            self.missing_in_candidate
            or self.missing_in_legacy
            or self.blob_mismatch
            or self.raw_mismatch
            or self.filter_masked
        )


def compare_trees(candidate: Path, legacy: Path) -> Comparison:
    """Compare the candidate source tree against the archived original.

    Args:
        candidate: ``<repo>/apps/web/src``.
        legacy: ``<legacy_root>/apps/web/src``.

    Returns:
        A :class:`Comparison` recording every disagreement.

    Raises:
        RuntimeError: git could not be consulted (the comparison would be
            unfounded, so it is never downgraded to a pass).
    """
    new_files = collect_relative_files(candidate)
    old_files = collect_relative_files(legacy)

    result = Comparison(
        common=len(set(new_files) & set(old_files)),
        missing_in_candidate=sorted(set(old_files) - set(new_files)),
        missing_in_legacy=sorted(set(new_files) - set(old_files)),
    )
    shared = sorted(set(new_files) & set(old_files))

    new_blob = _GIT_RUNNER(shared, candidate)
    old_blob = _GIT_RUNNER(shared, legacy)
    new_raw = _raw_digests(candidate, shared)
    old_raw = _raw_digests(legacy, shared)

    for relative in shared:
        if new_blob.get(relative) != old_blob.get(relative):
            result.blob_mismatch.append(relative)
        if new_raw.get(relative) != old_raw.get(relative):
            result.raw_mismatch.append(relative)
        if (
            new_raw.get(relative) != old_raw.get(relative)
            and new_blob.get(relative) == old_blob.get(relative)
        ):
            result.filter_masked.append(relative)
    return result


# ---------------------------------------------------------------------------
# Declared-absence registry
# ---------------------------------------------------------------------------


@dataclass
class Registry:
    """The parsed declared-absence registry.

    Attributes:
        entries: Normalised root pattern → owner.
        paths: Documents that were read (evidence: an empty list means the
            registry itself is missing, and every ABSENT verdict is then
            unregistered).
    """

    entries: dict[str, str] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    def owner_of(self, root: str) -> str | None:
        """Return the declared owner of ``root``, or ``None`` when unregistered."""
        return self.entries.get(root)


def _normalise_root(text: str) -> str:
    """Strip backticks, whitespace and a trailing parenthetical from a pattern.

    Args:
        text: Raw table cell.

    Returns:
        The normalised pattern.
    """
    value = str(text).strip().strip("`").strip()
    value = re.sub(r"\s*[（(][^（()）]*[)）]\s*$", "", value).strip()
    return value.strip("`").strip()


def load_registry(repo_root: Path) -> Registry:
    """Read every declared-absence registry document under ``docs/``.

    Args:
        repo_root: Repository root.

    Returns:
        A :class:`Registry`.  Absent documents yield an empty registry, which is
        reported as such instead of being treated as "everything is declared".
    """
    registry = Registry()
    for path in sorted(repo_root.glob(REGISTRY_GLOB)):
        if not path.is_file():
            continue
        registry.paths.append(path.relative_to(repo_root).as_posix())
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 4 or not line.strip().startswith("|"):
                continue
            root = _normalise_root(cells[0])
            state = cells[1].strip().upper()
            owner = _normalise_root(cells[2])
            if root and "ABSENT" in state:
                registry.entries[root] = owner or "-"
    return registry


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _classify_root(root: str, directory: Path, registry: Registry, min_files: int) -> RootReport:
    """Produce the three-state report for one root.

    Args:
        root: Canonical root pattern.
        directory: The directory the pattern resolves to.
        registry: Declared-absence registry.
        min_files: Per-root floor.

    Returns:
        The :class:`RootReport`.
    """
    owner = registry.owner_of(root)
    if not directory.is_dir():
        if root in REQUIRED_ROOTS:
            return RootReport(
                root=root,
                state=STATE_INVALID,
                files=0,
                declared_owner=owner or "-",
                reason="required-root-absent",
            )
        if owner is None:
            return RootReport(
                root=root,
                state=STATE_INVALID,
                files=0,
                declared_owner="-",
                reason="unregistered-absence",
            )
        return RootReport(root=root, state=STATE_ABSENT, files=0, declared_owner=owner)

    files = len(collect_relative_files(directory))
    if files < min_files:
        return RootReport(
            root=root,
            state=STATE_INVALID,
            files=files,
            declared_owner=owner or "-",
            reason=f"EMPTY(files={files}<{min_files})",
        )
    return RootReport(root=root, state=STATE_OK, files=files, declared_owner=owner or "-")


def _git_diff_stat(repo_root: Path, pattern: str) -> tuple[str, int]:
    """Run ``git diff --stat`` for one pathspec.

    Args:
        repo_root: Repository to run in.
        pattern: Pathspec (``apps/web/src/**``).

    Returns:
        ``(stdout, returncode)``.  A non-zero return code is returned, not
        swallowed — that is the difference between "no diff" and "diff failed".
    """
    try:
        completed = subprocess.run(
            ["git", "diff", "--stat", "--", pattern],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return f"git unavailable: {exc}", 1
    return completed.stdout, completed.returncode


def _tracked_in_head(repo_root: Path, relative: str) -> bool:
    """Whether ``relative`` exists in ``HEAD`` at all.

    Reported as evidence, because ``git diff`` over an untracked tree is empty
    for a reason that has nothing to do with "unchanged".

    Args:
        repo_root: Repository to run in.
        relative: Path relative to the repository root.

    Returns:
        ``True`` when HEAD lists at least one file under it.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", relative],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    return bool(completed.stdout.strip())


def evaluate(
    *,
    repo_root: Path,
    legacy_root: Path,
    registry: Registry,
    min_files: int = MIN_FILES,
    use_git: bool = True,
) -> tuple[list[RootReport], Comparison, str, int, bool]:
    """Run every ⑤-a assertion.

    Args:
        repo_root: Repository root.
        legacy_root: Read-only legacy repository root.
        registry: Declared-absence registry.
        min_files: Floor for the two source roots; the positive proof in the
            self-test calls this with 0.
        use_git: When ``False``, skip the ``git diff`` / tracking probes (used by
            the self-test, which has no repository).

    Returns:
        ``(reports, comparison, diff_stdout, diff_rc, tracked)``.
    """
    roots = {
        ROOT_NEW: repo_root / WEB_SRC_REL,
        ROOT_LEGACY: legacy_root / WEB_SRC_REL,
        ROOT_BASELINE: repo_root / "contracts" / "frontend-baseline",
    }
    reports = [
        _classify_root(
            root,
            roots[root],
            registry,
            min_files if root in REQUIRED_ROOTS else ROOT_MIN_FILES[root],
        )
        for root in SCAN_ROOTS
    ]

    by_root = {report.root: report for report in reports}
    if by_root[ROOT_NEW].state == STATE_OK and by_root[ROOT_LEGACY].state == STATE_OK:
        comparison = compare_trees(roots[ROOT_NEW], roots[ROOT_LEGACY])
    else:
        comparison = Comparison()

    if use_git:
        diff_stdout, diff_rc = _git_diff_stat(repo_root, WEB_SRC_REL + "/**")
        tracked = _tracked_in_head(repo_root, WEB_SRC_REL)
    else:
        diff_stdout, diff_rc, tracked = "", 0, True
    return reports, comparison, diff_stdout, diff_rc, tracked


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _build_tree(base: Path, names: Sequence[str], *, byte: bytes = b"x") -> None:
    """Create a tree of files, each holding the same content.

    Args:
        base: Root directory of the tree.
        names: Relative POSIX paths.
        byte: Content to write.
    """
    base.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = base / Path(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(byte)


def _stub_git_runner(relatives: Sequence[str], cwd: Path) -> dict[str, str]:
    """A :func:`_git_hash_objects` stand-in: hash the bytes git would see.

    Uses the raw digest so the stub agrees with the raw cross-check by
    construction; the real runner is exercised separately by case 6.

    Args:
        relatives: Relative paths inside ``cwd``.
        cwd: Directory to read from.

    Returns:
        relative → digest.
    """
    digests: dict[str, str] = {}
    for relative in relatives:
        target = cwd / Path(*relative.split("/"))
        try:
            digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            digests[relative] = "<git-error>"
    return digests


def _self_test() -> int:
    """Run the six injection cases.

    1. identical trees            → comparison clean
    2. one byte flipped           → blob + raw mismatch
    3. candidate tree emptied     → INVALID(EMPTY) (the floor is load-bearing)
    4. archive removed            → INVALID(required-root-absent), never a skip
    5. floor lowered to 0         → case 3 turns green (positive proof that the
                                    floor, not luck, is what made it red)
    6. real runner on the real trees → the actual ⑤-a fact, not a simulation

    Returns:
        ``0`` when every case holds, ``9`` otherwise.
    """
    global _GIT_RUNNER
    failures: list[str] = []
    original_runner = _GIT_RUNNER
    _GIT_RUNNER = _stub_git_runner

    names = [f"src/file{index:03d}.tsx" for index in range(10)]
    tiny_registry = Registry(entries={ROOT_BASELINE: "V0.1.0"})

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)

            # case 1 + 2 ------------------------------------------------------
            candidate = tmp_root / "repo" / WEB_SRC_REL
            legacy = tmp_root / "old" / WEB_SRC_REL
            _build_tree(candidate, names)
            _build_tree(legacy, names)
            comparison = compare_trees(candidate, legacy)
            if not comparison.clean or comparison.common != 10:
                failures.append(f"case1 identical trees: {comparison}")
            (candidate / "src" / "file000.tsx").write_bytes(b"y")
            comparison = compare_trees(candidate, legacy)
            if "src/file000.tsx" not in comparison.blob_mismatch:
                failures.append("case2 flipped byte not seen in blob_mismatch")
            if "src/file000.tsx" not in comparison.raw_mismatch:
                failures.append("case2 flipped byte not seen in raw_mismatch")
            if comparison.clean:
                failures.append("case2 flipped byte reported clean")

            # case 3: emptied candidate -------------------------------------
            for name in names:
                (candidate / Path(*name.split("/"))).unlink()
            reports, _cmp, _out, _rc, _tracked = evaluate(
                repo_root=tmp_root / "repo",
                legacy_root=tmp_root / "old",
                registry=tiny_registry,
                min_files=10,
                use_git=False,
            )
            emptied = {report.root: report for report in reports}
            if emptied[ROOT_NEW].state != STATE_INVALID:
                failures.append(f"case3 emptied candidate: {emptied[ROOT_NEW].render()}")
            elif "EMPTY" not in emptied[ROOT_NEW].reason:
                failures.append(f"case3 reason not EMPTY: {emptied[ROOT_NEW].reason}")
            if emptied[ROOT_BASELINE].state != STATE_ABSENT:
                failures.append(f"case3 registered absent baseline: {emptied[ROOT_BASELINE].render()}")
            elif emptied[ROOT_BASELINE].declared_owner != "V0.1.0":
                failures.append(f"case3 baseline owner: {emptied[ROOT_BASELINE].declared_owner}")

            # case 3b: the same absence, unregistered ------------------------
            (
                _r,
                _c,
                _o,
                _rc2,
                _t,
            ) = evaluate(
                repo_root=tmp_root / "repo",
                legacy_root=tmp_root / "old",
                registry=Registry(),
                min_files=10,
                use_git=False,
            )
            unregistered = {report.root: report for report in _r}
            if unregistered[ROOT_BASELINE].state != STATE_INVALID:
                failures.append(f"case3b unregistered absence: {unregistered[ROOT_BASELINE].render()}")
            elif unregistered[ROOT_BASELINE].reason != "unregistered-absence":
                failures.append(f"case3b reason: {unregistered[ROOT_BASELINE].reason}")

            # case 4: archive removed ----------------------------------------
            _build_tree(candidate, names)
            shutil.rmtree(legacy, ignore_errors=True)
            reports, _cmp, _out, _rc, _tracked = evaluate(
                repo_root=tmp_root / "repo",
                legacy_root=tmp_root / "old",
                registry=tiny_registry,
                min_files=10,
                use_git=False,
            )
            archive = {report.root: report for report in reports}
            if archive[ROOT_LEGACY].state != STATE_INVALID:
                failures.append(f"case4 missing archive: {archive[ROOT_LEGACY].render()}")
            elif archive[ROOT_LEGACY].reason != "required-root-absent":
                failures.append(f"case4 archive reason: {archive[ROOT_LEGACY].reason}")

            # case 5: positive proof — the floor is what makes case 3 red -----
            shutil.rmtree(candidate, ignore_errors=True)
            candidate.mkdir(parents=True, exist_ok=True)
            _build_tree(legacy, names)
            reports, _cmp, _out, _rc, _tracked = evaluate(
                repo_root=tmp_root / "repo",
                legacy_root=tmp_root / "old",
                registry=tiny_registry,
                min_files=0,
                use_git=False,
            )
            with_floor = {report.root: report for report in reports}
            if with_floor[ROOT_NEW].state != STATE_OK:
                failures.append(
                    f"case5 floor=0 must let an empty tree through: {with_floor[ROOT_NEW].render()}"
                )
    finally:
        _GIT_RUNNER = original_runner

    # case 6: the real thing --------------------------------------------------
    paths = _gate_io.GatePaths.resolve()
    reports, comparison, _out, _rc, _tracked = evaluate(
        repo_root=paths.repo_root,
        legacy_root=paths.legacy_root,
        registry=load_registry(paths.repo_root),
        use_git=False,
    )
    real = {report.root: report for report in reports}
    for root in (ROOT_NEW, ROOT_LEGACY):
        if real[root].state != STATE_OK:
            failures.append(f"case6 real root {root}: {real[root].render()}")
    if not comparison.clean:
        failures.append(
            "case6 real trees differ: "
            f"blob={len(comparison.blob_mismatch)} raw={len(comparison.raw_mismatch)} "
            f"missing_candidate={len(comparison.missing_in_candidate)} "
            f"missing_legacy={len(comparison.missing_in_legacy)}"
        )
    if comparison.common < MIN_FILES:
        failures.append(f"case6 common files {comparison.common} below floor {MIN_FILES}")

    if failures:
        for problem in failures:
            print(f"self-test FAIL: {problem}")
        return 9
    print(
        "self-test OK (6 cases): identical|flipped|emptied|archive-gone|floor=0|real"
        f"(common={comparison.common})"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector (``None`` → ``sys.argv[1:]``).

    Returns:
        One of the documented exit codes.
    """
    parser = argparse.ArgumentParser(
        prog="check_frontend_diff.py",
        description="⑤-a: prove apps/web/src/** is byte-identical to the archived original.",
    )
    parser.add_argument(
        "--legacy-root",
        default=None,
        help="override the read-only legacy repository root",
    )
    parser.add_argument(
        "--allow-declared-absence",
        action="store_true",
        help="treat a registered ABSENT root as non-fatal (口径 Y)",
    )
    parser.add_argument("--self-test", action="store_true", help="run the injection cases and exit")
    args, extra = parser.parse_known_args(argv)
    if extra:
        _gate_io.log(TAG, f"usage error: unexpected arguments {extra}")
        return 2

    if args.self_test:
        return _self_test()

    paths = _gate_io.GatePaths.resolve(legacy_root=args.legacy_root)
    registry = load_registry(paths.repo_root)
    if not registry.paths:
        _gate_io.log(TAG, f"registry not found: {REGISTRY_GLOB}")
        return 2

    reports, comparison, diff_stdout, diff_rc, tracked = evaluate(
        repo_root=paths.repo_root, legacy_root=paths.legacy_root, registry=registry
    )

    for report in reports:
        _gate_io.log(TAG, report.render())

    violations: list[str] = []
    for report in reports:
        if report.state == STATE_INVALID:
            violations.append(f"{report.root} {report.state}({report.reason})")

    if diff_rc != 0:
        violations.append(f"git diff failed rc={diff_rc}: {diff_stdout.strip()}")
    elif diff_stdout.strip():
        violations.append(f"git diff non-empty: {diff_stdout.strip()}")

    if comparison.blob_mismatch:
        sample = ", ".join(comparison.blob_mismatch[:5])
        violations.append(
            f"blob mismatch n={len(comparison.blob_mismatch)} e.g. {sample}"
        )
    if comparison.raw_mismatch:
        sample = ", ".join(comparison.raw_mismatch[:5])
        violations.append(f"raw bytes mismatch n={len(comparison.raw_mismatch)} e.g. {sample}")
    if comparison.filter_masked:
        sample = ", ".join(comparison.filter_masked[:5])
        violations.append(f"filter-masked n={len(comparison.filter_masked)} e.g. {sample}")
    if comparison.missing_in_candidate:
        sample = ", ".join(comparison.missing_in_candidate[:5])
        violations.append(
            f"missing in candidate n={len(comparison.missing_in_candidate)} e.g. {sample}"
        )
    if comparison.missing_in_legacy:
        sample = ", ".join(comparison.missing_in_legacy[:5])
        violations.append(
            f"missing in archive n={len(comparison.missing_in_legacy)} e.g. {sample}"
        )

    effective = sum(1 for report in reports if report.effective)
    absent = [report for report in reports if report.state == STATE_ABSENT]
    total = len(reports)

    _gate_io.log(
        TAG,
        f"compare common={comparison.common} blob_mismatch={len(comparison.blob_mismatch)} "
        f"raw_mismatch={len(comparison.raw_mismatch)} "
        f"missing_candidate={len(comparison.missing_in_candidate)} "
        f"missing_archive={len(comparison.missing_in_legacy)}",
    )
    _gate_io.log(
        TAG,
        f"git diff --stat -- apps/web/src/** => rc={diff_rc} empty={not diff_stdout.strip()} "
        f"tracked_in_head={tracked}",
    )
    if not tracked:
        _gate_io.log(
            TAG,
            "NOTE apps/web/src is not in HEAD: an empty diff over an untracked tree proves "
            "nothing; the per-file hash comparison is the load-bearing evidence until the "
            "migration commit lands",
        )

    if absent and not args.allow_declared_absence:
        for report in absent:
            _gate_io.log(TAG, f"absent root {report.root} registered owner={report.declared_owner}")
        _gate_io.log(
            TAG,
            f"PARTIAL({effective}/{total} roots effective) — declared absence present; "
            "re-run with --allow-declared-absence to accept it",
        )
        return 1
    if absent:
        _gate_io.log(
            TAG, f"PARTIAL({effective}/{total} roots effective) accepted via --allow-declared-absence"
        )

    if violations:
        for problem in violations:
            _gate_io.log(TAG, f"violation {problem}")
        _gate_io.log(TAG, f"FAIL coverage: {effective}/{total} roots effective")
        return 1

    verdict = "PASS" if effective == total else f"PARTIAL({effective}/{total} roots effective)"
    _gate_io.log(TAG, f"{verdict} coverage: {effective}/{total} roots effective")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
