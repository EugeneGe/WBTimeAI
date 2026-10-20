"""T05 / S-1 — the frontend-baseline scan: prove that "no `msw` in scope" is a
real, non-vacuous statement.

What S-1 has to answer
----------------------
S-1 is not "we ran a linter".  It is the structural claim behind DoD#4/#5:

    the e2e runner executes against a **real** backend because no mock library
    (`msw`) can exist inside the surface it is allowed to touch.

That claim is only worth something if three things hold at once, and the design
(§1.7.2 «三条硬机制») makes each of them mandatory:

============================  ==================================================
``MIN_FILES`` floor           an empty (or nearly empty) scan surface must be
                              ``INVALID(EMPTY)``, never PASS — an empty glob is
                              vacuously true and that is the bug this version
                              exists to kill (K-11)
per-root three-state report   every root reports ``OK(n)`` / ``ABSENT(declared)``
                              / ``INVALID(...)`` **separately**; folding them into
                              one boolean is how a single empty root hides behind
                              a healthy one
declared-absence registry     a root that legitimately does not exist yet must be
                              *registered* with an owner; a missing registration is
                              ``INVALID``, not a skip
============================  ==================================================

Scan surface — **redefined in V0.1.0 (user-approved, see below)**
-----------------------------------------------------------------
V0.0.2 scanned ``packages/*/**`` (every package).  That premise died the moment
V0.1.0 landed: the repo now holds **eight** business packages whose *non-empty
dependencies are normal* (``@sinclair/typebox``, ``pino``, ``drizzle-orm`` …), so
the old surface reported **9 violations / EXIT 1** on a perfectly healthy tree::

    VIOLATION: packages/*/**: non-empty dependencies in packages/{config,contracts,
               core,domain,event,logging,ports}/package.json
    VIOLATION: contracts/frontend-baseline/**: present but registered ABSENT
    VIOLATION: apps/**: msw declared or imported in apps/web/package.json

"Zero dependencies" was only ever a *proxy* for what S-1 actually claims: **the
e2e runner talks to a real backend, so no mock library can exist on the surface it
is allowed to touch**.  Narrowing the surface restores the real claim instead of
disabling it (disabling it — option B — would leave CI permanently red; whitelisting
the offending packages — option C — would hide a genuine ``msw`` hit inside them).

``packages/e2e/**`` — **the whole package**, not just ``tests/e2e/**``.  S-1 asks
"can `msw` live in *the runner*?", and `msw` can be declared in ``package.json``
*or* imported from ``lib/``.  Scanning only the test directory would miss the
lib-import case.  ``node_modules/**`` is excluded (vendored dependencies are not
our source).  This package **must stay zero-dependency** — that is the load-bearing
premise, and it is now asserted on the one package where it is meaningful.

``contracts/frontend-baseline/**`` — the second root.  It could not exist in
V0.0.2 (adding a file under ``contracts/`` broke ``manifest.sha256``); V0.1.0
produces it (``openapi.subset.json`` / ``sse.channels.json`` / ``error-codes.ts``),
so it is registered **OK** and coverage becomes **2/2 roots effective**.

``apps/web/**`` — an explicit exclusion.  ``msw`` is a *direct dependency of the
app shell* and ``src/**`` ships its own unit tests that legitimately use it.  The
exclusion widened from ``apps/web/src/**`` to the whole app in V0.1.0 because the
``msw`` **declaration lives in ``apps/web/package.json``**, which the narrow
exclusion did not cover.  The exclusion must be *present and effective*; if it
disappears, the app silently joins the scanned surface.

Exit codes (design §3.3)::

    0   the selected stance passes (default: 口径 Y, absence-registered)
    1   violation: INVALID(EMPTY), msw hit, setupServer, non-zero deps,
        an unregistered absent root, or ``--strict`` (口径 X) with an absent root
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)

__all__ = [
    "TAG",
    "MIN_FILES",
    "SCAN_ROOTS",
    "EXCLUDE_GLOBS",
    "RootReport",
    "RegistryEntry",
    "S1Registry",
    "scan",
    "evaluate",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "fbaseline"

#: Lower bound on files the code root must really contain.  Declared **once** in
#: the whole file on purpose: the S-7 meta gate mutates this exact assignment into
#: ``0`` and requires the mutation anchor to be unique.
MIN_FILES = 6

#: The two scan roots, in report order.  V0.1.0 narrowed the code root from every
#: package to the e2e runner alone: business packages legitimately carry runtime
#: dependencies, and asserting "zero deps" on them was never what S-1 claimed.
SCAN_ROOTS: Final[tuple[str, ...]] = (
    "packages/e2e/**",
    "contracts/frontend-baseline/**",
)

#: Roots removed from the scanned surface on purpose (must stay in sync with the
#: registry document, otherwise a present ``apps/web`` joins the surface).  Widened
#: from ``apps/web/src/**`` in V0.1.0 because the ``msw`` declaration sits in
#: ``apps/web/package.json``, outside the old narrow exclusion.
EXCLUDE_GLOBS: Final[tuple[str, ...]] = ("apps/web/**",)

#: The implicit third surface: application shells.  Not a scan root (it carries no
#: coverage weight), but it must be *seen* so the exclusion cannot silently rot.
APPS_GLOB: Final[str] = "apps/**"

#: Vendored dependencies are not our source.
NODE_MODULES: Final[str] = "node_modules"

#: Where the declared-absence registry lives (found by glob: the version directory
#: name must never be hard-coded).
REGISTRY_GLOB: Final[str] = "docs/**/03-台账/S-1-扫描面登记.md"

#: Per-root minimum: the code root uses :data:`MIN_FILES`; a present contract root
#: only has to be non-empty (its size is governed by the V0.1.0 deriver).
ROOT_MIN_FILES: Final[dict[str, int]] = {
    "packages/e2e/**": MIN_FILES,
    "contracts/frontend-baseline/**": 1,
}

#: States a root report can carry.  ``OK`` and ``ABSENT`` are the two legal ones;
#: ``INVALID`` never passes (K-11).
STATE_OK: Final[str] = "OK"
STATE_ABSENT: Final[str] = "ABSENT"
STATE_INVALID: Final[str] = "INVALID"

#: Registry row states.
REGISTRY_OK: Final[str] = "OK"
REGISTRY_ABSENT: Final[str] = "ABSENT"

#: A dependency key that means "msw is declared".
MSW_DEP_RE: Final[re.Pattern[str]] = re.compile(r"^(?:msw|@mswjs/[A-Za-z0-9._-]+)$")

#: `msw` imported / required (the lib-import case a tests-only glob would miss).
MSW_IMPORT_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?:from\s*['"]msw(?:/[^'"]*)?['"]"""
    r"""|require\(\s*['"]msw(?:/[^'"]*)?['"]"""
    r"""|import\s*['"]msw(?:/[^'"]*)?['"])"""
)

#: `setupServer(...)` — the per-test mock server constructor.
SETUP_SERVER_RE: Final[re.Pattern[str]] = re.compile(r"\bsetupServer\s*\(")

#: Files we are willing to read as text (everything else is skipped, not judged).
TEXT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".mjs", ".cjs", ".js", ".jsx", ".ts", ".tsx", ".json", ".jsonc",
        ".yml", ".yaml", ".md", ".txt", ".html", ".css", ".py", ".sh",
    }
)

#: Upper bound on a file we will scan (a lockfile is not source).
MAX_SCANNED_BYTES: Final[int] = 2 * 1024 * 1024


@dataclass(frozen=True)
class RegistryEntry:
    """One row of ``03-台账/S-1-扫描面登记.md``.

    Attributes:
        root: Normalised root pattern (backticks and trailing parentheticals
            stripped).
        state: ``OK`` or ``ABSENT``.
        owner: Version that owns the root (``V0.0.2`` / ``V0.1.0`` ...).
        reason: Why the root has that state.
    """

    root: str
    state: str
    owner: str
    reason: str

    def render(self) -> str:
        """Return a one-line ASCII-safe rendering.

        Returns:
            ``"<root> <state> owner=<owner>"``.
        """
        return f"{self.root} {self.state} owner={self.owner or '-'}"


@dataclass
class S1Registry:
    """The parsed declared-absence registry.

    Attributes:
        path: Registry document, or ``None`` when the glob found nothing.
        entries: Normalised root → :class:`RegistryEntry`.
        problems: Why the registry cannot be used (empty means usable).
    """

    path: Path | None = None
    entries: dict[str, RegistryEntry] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether the registry can be trusted at all."""
        return self.path is not None and not self.problems

    def lookup(self, root: str) -> RegistryEntry | None:
        """Return the registration for ``root``.

        Args:
            root: Canonical root pattern.

        Returns:
            The entry, or ``None`` when the root is not registered.
        """
        return self.entries.get(normalise_root(root))


@dataclass(frozen=True)
class RootReport:
    """One root's three-state result (design §3.2 ``RootReport``).

    Attributes:
        root: Canonical root pattern.
        state: ``OK`` / ``ABSENT`` / ``INVALID``.
        files: How many files the scan really matched.
        msw_hits: Relative paths where ``msw`` is declared or imported.
        dep_declared: Relative ``package.json`` paths whose deps are non-empty.
        setup_server_files: Relative paths calling ``setupServer``.
        declared_owner: Owner from the registry (``-`` when unregistered).
        reason: Human readable explanation of ``state``.
    """

    root: str
    state: str
    files: int
    msw_hits: tuple[str, ...] = ()
    dep_declared: tuple[str, ...] = ()
    setup_server_files: tuple[str, ...] = ()
    declared_owner: str = "-"
    reason: str = ""

    @property
    def effective(self) -> bool:
        """Whether this root really took effect (``OK`` and non-vacuous)."""
        return self.state == STATE_OK

    def render(self) -> str:
        """Render the per-root evidence line.

        Returns:
            e.g. ``root packages/*/** OK(files=9) msw_hits=0 deps_nonempty=0
            setupServer_files=0``.
        """
        head = f"root {self.root}"
        if self.state == STATE_OK:
            body = (
                f"OK(files={self.files}) msw_hits={len(self.msw_hits)}"
                f" deps_nonempty={len(self.dep_declared)}"
                f" setupServer_files={len(self.setup_server_files)}"
            )
        elif self.state == STATE_ABSENT:
            body = f"ABSENT(declared; owner={self.declared_owner}; reason={self.reason})"
        else:
            body = f"INVALID({self.reason})"
        return f"{head:<40} {body}"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def normalise_root(text: str) -> str:
    """Normalise a root pattern written in prose or in the registry table.

    Strips backticks, surrounding whitespace and a trailing parenthetical such as
    ``（排除）`` or ``(excluded)`` so ``apps/web/src/**`` and
    ```apps/web/src/**`（排除）`` compare equal.

    Args:
        text: Raw cell / constant text.

    Returns:
        The normalised pattern (possibly empty).
    """
    value = str(text).strip().strip("`").strip()
    value = re.sub(r"\s*[（(][^（()）]*[)）]\s*$", "", value).strip()
    return value.strip("`").strip()


def _is_excluded(relative: str, exclusions: Sequence[str]) -> bool:
    """Whether a POSIX relative path falls under one of ``exclusions``.

    Args:
        relative: Path relative to the repository root, POSIX style.
        exclusions: Glob patterns (``apps/web/src/**``).

    Returns:
        ``True`` when the path is excluded from the scanned surface.
    """
    for pattern in exclusions:
        prefix = pattern.split("**", 1)[0].rstrip("/")
        if prefix and (relative == prefix or relative.startswith(prefix + "/")):
            return True
    return False


def _iter_files(root_dir: Path, base: Path) -> Iterable[Path]:
    """Yield every regular file under ``root_dir``, skipping ``node_modules``.

    Args:
        root_dir: Directory to walk.
        base: Repository root, used to compute relative paths.

    Yields:
        Files in deterministic (sorted) order.
    """
    for path in sorted(root_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(base).parts
        if NODE_MODULES in relative_parts:
            continue
        yield path


def _scan_text(path: Path) -> str:
    """Read a file as text when it is small enough, else return ``""``.

    Args:
        path: File to read.

    Returns:
        The decoded text, or an empty string when the file is binary / too large.
    """
    try:
        if path.stat().st_size > MAX_SCANNED_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _scan_package_json(path: Path, base: Path) -> tuple[list[str], list[str]]:
    """Inspect one ``package.json`` for ``msw`` and for non-empty dependencies.

    Args:
        path: The ``package.json`` file.
        base: Repository root (for the relative path in evidence).

    Returns:
        ``(msw_hits, dependency_declarations)`` as relative paths.
    """
    text = _scan_text(path)
    if text == "":
        return [], []
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return [], []
    if not isinstance(document, dict):
        return [], []
    relative = path.relative_to(base).as_posix()

    hits: list[str] = []
    declared: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = document.get(section)
        if not isinstance(block, dict) or not block:
            continue
        declared.append(relative)
        for name in block:
            if MSW_DEP_RE.match(str(name)):
                hits.append(relative)
                break
    return hits, declared


def _scan_surface(
    directory: Path, base: Path, *, exclusions: Sequence[str]
) -> tuple[int, list[str], list[str], list[str]]:
    """Scan one directory tree for the four S-1 facts.

    Args:
        directory: Tree to scan.
        base: Repository root (relative paths in the evidence).
        exclusions: Patterns removed from the surface.

    Returns:
        ``(files, msw_hits, dep_declared, setup_server_files)`` — every list holds
        POSIX relative paths, sorted and de-duplicated.
    """
    files = 0
    msw_hits: set[str] = set()
    dep_declared: set[str] = set()
    setup_server_files: set[str] = set()

    for path in _iter_files(directory, base):
        relative = path.relative_to(base).as_posix()
        if _is_excluded(relative, exclusions):
            continue
        files += 1
        if path.name == "package.json":
            hits, declared = _scan_package_json(path, base)
            msw_hits.update(hits)
            dep_declared.update(declared)
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _scan_text(path)
        if text == "":
            continue
        if MSW_IMPORT_RE.search(text):
            msw_hits.add(relative)
        if SETUP_SERVER_RE.search(text):
            setup_server_files.add(relative)

    return files, sorted(msw_hits), sorted(dep_declared), sorted(setup_server_files)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def load_registry(repo_root: Path) -> S1Registry:
    """Locate and parse the declared-absence registry.

    Args:
        repo_root: Repository root.

    Returns:
        The parsed registry; ``problems`` explains any unusable state (a missing
        registry is a problem, never a skip — G-7).
    """
    matches = sorted(repo_root.glob(REGISTRY_GLOB))
    if not matches:
        return S1Registry(problems=[f"registry not found: {REGISTRY_GLOB}"])
    if len(matches) > 1:
        joined = ", ".join(item.as_posix() for item in matches)
        return S1Registry(problems=[f"ambiguous registry ({len(matches)} matches): {joined}"])

    path = matches[0]
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:  # pragma: no cover - filesystem race
        return S1Registry(path=path, problems=[f"cannot read registry: {error}"])

    entries: dict[str, RegistryEntry] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        root = normalise_root(cells[0])
        state = cells[1].strip().strip("`").upper()
        if not root or state not in (REGISTRY_OK, REGISTRY_ABSENT):
            continue
        entries[root] = RegistryEntry(
            root=root,
            state=state,
            owner=cells[2].strip().strip("`"),
            reason=cells[3].strip(),
        )

    registry = S1Registry(path=path, entries=entries)
    if not entries:
        registry.problems.append("registry has no parsable root rows (K-11: empty => INVALID)")
    return registry


# ---------------------------------------------------------------------------
# Scanning / judging
# ---------------------------------------------------------------------------


def _report_root(root: str, repo_root: Path, registry: S1Registry) -> RootReport:
    """Scan and classify one root.

    Args:
        root: Canonical root pattern.
        repo_root: Repository root.
        registry: Parsed registry.

    Returns:
        The root report.  Never raises: an unreadable root is ``INVALID``.
    """
    minimum = ROOT_MIN_FILES.get(root, 1)
    registration = registry.lookup(root)

    if root.startswith("contracts/"):
        directory = repo_root / "contracts" / "frontend-baseline"
        exists = directory.is_dir()
    else:
        # Derive the concrete directory from the root pattern.  V0.1.0 narrowed the
        # code root to ``packages/e2e/**``; hard-coding ``repo_root / "packages"``
        # here would keep scanning *every* package and re-report the exact false
        # positives the narrowing was meant to remove (measured: 7 violations on a
        # healthy tree, 2026-10-21).
        base = root.split("/**")[0].rstrip("/")
        if base.endswith("/*"):
            base = base[:-2]
        directory = repo_root / base
        exists = directory.is_dir()

    if not exists:
        if registration is not None and registration.state == REGISTRY_ABSENT:
            return RootReport(
                root=root,
                state=STATE_ABSENT,
                files=0,
                declared_owner=registration.owner or "-",
                reason=registration.reason or "declared absent",
            )
        return RootReport(
            root=root,
            state=STATE_INVALID,
            files=0,
            reason=(
                "absent and NOT registered in S-1-扫描面登记.md "
                "(K-11: an unregistered absence is INVALID, never a skip)"
            ),
        )

    files, msw_hits, dep_declared, setup_server_files = _scan_surface(
        directory, repo_root, exclusions=()
    )
    if files == 0:
        return RootReport(
            root=root,
            state=STATE_INVALID,
            files=0,
            reason="EMPTY: scanned 0 file(s) -> vacuous pass refused (K-11)",
        )
    if files < minimum:
        return RootReport(
            root=root,
            state=STATE_INVALID,
            files=files,
            reason=f"EMPTY: scanned {files} file(s) < MIN_FILES floor {minimum}",
        )
    if registration is not None and registration.state == REGISTRY_ABSENT:
        return RootReport(
            root=root,
            state=STATE_INVALID,
            files=files,
            reason=(
                f"present ({files} files) but registered ABSENT by {registration.owner}; "
                "registry and tree disagree"
            ),
        )
    return RootReport(
        root=root,
        state=STATE_OK,
        files=files,
        msw_hits=tuple(msw_hits),
        dep_declared=tuple(dep_declared),
        setup_server_files=tuple(setup_server_files),
        declared_owner=(registration.owner if registration is not None else "-"),
        reason="",
    )


def scan(paths: _gate_io.GatePaths, registry: S1Registry) -> list[RootReport]:
    """Scan every root, one report each (never folded into one boolean).

    Args:
        paths: Resolved roots.
        registry: Parsed registry.

    Returns:
        One :class:`RootReport` per root, in :data:`SCAN_ROOTS` order.
    """
    return [_report_root(root, paths.repo_root, registry) for root in SCAN_ROOTS]


def _exclusion_report(repo_root: Path) -> tuple[str, int, list[str]]:
    """Report the explicit exclusion surface (``apps/web/src/**``).

    Args:
        repo_root: Repository root.

    Returns:
        ``(state, files, violations)`` where state is ``OK`` / ``ABSENT`` /
        ``INVALID`` and violations are human readable reasons.
    """
    apps_dir = repo_root / "apps"
    if not apps_dir.is_dir():
        return STATE_ABSENT, 0, []

    target_rel = "apps/web/src"
    target_dir = repo_root / Path(*target_rel.split("/"))
    covered = _is_excluded(f"{target_rel}/probe.mjs", EXCLUDE_GLOBS)

    # Everything under apps/ that is *not* excluded is in the scanned surface.
    files, msw_hits, _deps, _setup = _scan_surface(apps_dir, repo_root, exclusions=EXCLUDE_GLOBS)
    violations = [f"apps/**: msw declared or imported in {hit}" for hit in msw_hits]

    if target_dir.is_dir() and not covered:
        # The directory exists but nothing excludes it any more: its sources joined
        # the scanned surface, so its hits are real hits (self-test injection 4).
        target_files, target_hits, _d2, _s2 = _scan_surface(target_dir, repo_root, exclusions=())
        files += target_files
        violations.extend(
            f"{target_rel}/**: msw declared or imported in {hit} "
            "(the exclusion for this directory is missing from EXCLUDE_GLOBS)"
            for hit in target_hits
        )
        return STATE_OK, files, violations

    if target_dir.is_dir():
        # Excluded on purpose: counted for evidence, never judged.
        excluded_files, _hits, _d3, _s3 = _scan_surface(target_dir, repo_root, exclusions=())
        return STATE_OK, excluded_files, violations

    return STATE_OK, files, violations


def evaluate(reports: Sequence[RootReport], *, strict: bool) -> list[str]:
    """Fold the per-root reports into the violation list.

    Args:
        reports: Per-root reports, in report order.
        strict: 口径 X — every root must really exist (an ``ABSENT`` root fails).

    Returns:
        Violation lines; empty means the selected stance passes.
    """
    violations: list[str] = []
    for report in reports:
        if report.state == STATE_INVALID:
            violations.append(f"{report.root}: {report.reason}")
            continue
        if report.state == STATE_ABSENT:
            if report.declared_owner in ("", "-"):
                violations.append(
                    f"{report.root}: absent without a declared owner "
                    "(K-11: unregistered absence => INVALID)"
                )
            elif strict:
                violations.append(
                    f"{report.root}: absent but --strict (口径 X) requires every root to exist"
                )
            continue
        for hit in report.msw_hits:
            violations.append(f"{report.root}: msw declared or imported in {hit}")
        for hit in report.setup_server_files:
            violations.append(f"{report.root}: setupServer(...) call in {hit} (mock server)")
        for hit in report.dep_declared:
            violations.append(
                f"{report.root}: non-empty dependencies in {hit} "
                "(zero dependencies is the premise of S-1, design §6)"
            )
    return violations


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render(
    paths: _gate_io.GatePaths,
    registry: S1Registry,
    reports: Sequence[RootReport],
    violations: Sequence[str],
    *,
    strict: bool,
    exclusion_state: str,
    exclusion_files: int,
    exclusion_violations: Sequence[str],
) -> None:
    """Print the whole evidence block (one line per fact, K-7).

    Args:
        paths: Resolved roots.
        registry: Parsed registry.
        reports: Per-root reports.
        violations: Folded violations.
        strict: Whether 口径 X was requested.
        exclusion_state: State of the ``apps/**`` surface.
        exclusion_files: How many files the exclusion covers.
        exclusion_violations: Violations coming from the exclusion surface.
    """
    _gate_io.log(TAG, f"repo={paths.repo_root.as_posix()}  at {_gate_io.utc_now_iso()}")
    if registry.path is None:
        _gate_io.log(TAG, "registry: NOT FOUND (" + "; ".join(registry.problems) + ")")
    else:
        _gate_io.log(
            TAG,
            f"registry: {registry.path.as_posix()} entries={len(registry.entries)}"
            + ("" if registry.usable else " problems=" + "; ".join(registry.problems)),
        )
    for report in reports:
        _gate_io.log(TAG, report.render())
        for hit in report.msw_hits:
            _gate_io.log(TAG, f"  msw: {hit}")
        for hit in report.setup_server_files:
            _gate_io.log(TAG, f"  setupServer: {hit}")
        for hit in report.dep_declared:
            _gate_io.log(TAG, f"  deps: {hit}")

    if exclusion_state == STATE_ABSENT:
        _gate_io.log(
            TAG, f"exclusion {EXCLUDE_GLOBS[0]:<27} ABSENT(expected until V0.1.0)"
        )
    else:
        _gate_io.log(
            TAG,
            f"exclusion {EXCLUDE_GLOBS[0]:<27} OK(files={exclusion_files} excluded on purpose)",
        )

    effective = sum(1 for report in reports if report.effective)
    for reason in list(violations) + list(exclusion_violations):
        _gate_io.log(TAG, f"VIOLATION: {reason}")
    for problem in registry.problems:
        _gate_io.log(TAG, f"VIOLATION: registry unusable: {problem}")

    stance = "口径X(--strict, literal coverage)" if strict else "口径Y(absence-registered)"
    if violations or exclusion_violations or registry.problems:
        _gate_io.log(
            TAG,
            f"VERDICT: INVALID ({len(violations) + len(exclusion_violations) + len(registry.problems)}"
            f" violation(s), stance={stance})",
        )
    else:
        _gate_io.log(
            TAG,
            f"VERDICT: PASS (coverage-limited, stance={stance}) - "
            f"S-1 is PARTIAL({effective}/{len(reports)} root(s) effective), not a full pass",
        )
    # The last line is always the coverage line: "PASS" alone is forbidden (§1.7.2).
    _gate_io.log(TAG, f"S1 coverage: {effective}/{len(reports)} roots effective")


# ---------------------------------------------------------------------------
# Self-test — five injections on a throw-away clone
# ---------------------------------------------------------------------------


def _copy_tree(source: Path, target: Path) -> None:
    """Copy a directory tree, ignoring ``node_modules``/``__pycache__``.

    Args:
        source: Directory to copy.
        target: Destination (created).
    """
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(NODE_MODULES, "__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )


def _prepare_clone(repo_root: Path, registry: S1Registry) -> Path:
    """Build a throw-away clone holding what the gate needs to run.

    Args:
        repo_root: Real repository root (read-only source).
        registry: The real registry, copied to the same relative location.

    Returns:
        The clone root.

    Raises:
        RuntimeError: The real ``packages/`` tree is missing (cannot self-test).
    """
    scratch = Path(tempfile.mkdtemp(prefix="wbtime-s1-"))
    clone = scratch / "repo"
    clone.mkdir(parents=True, exist_ok=True)

    packages = repo_root / "packages"
    if not packages.is_dir():
        raise RuntimeError(f"cannot self-test: {packages.as_posix()} is missing")
    _copy_tree(packages, clone / "packages")

    # The contract root is a *real* scan root since V0.1.0.  Cloning only
    # ``packages/`` made every self-test case red for the wrong reason (the missing
    # root, not the injection), which is how four injections silently stopped
    # proving anything — measured 2/6 on 2026-10-21.  A fixture must contain every
    # root the gate reports on, or the test measures the fixture.
    contract_root = repo_root / "contracts" / "frontend-baseline"
    if contract_root.is_dir():
        _copy_tree(contract_root, clone / "contracts" / "frontend-baseline")

    # ``apps/`` is the excluded surface; the exclusion cases need it to exist.
    apps_root = repo_root / "apps"
    if apps_root.is_dir():
        _copy_tree(apps_root, clone / "apps")

    scripts = clone / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "scripts" / "check_frontend_baseline.py", scripts)
    shutil.copy2(repo_root / "scripts" / "_gate_io.py", scripts)

    if registry.path is not None:
        relative = registry.path.relative_to(repo_root)
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(registry.path, destination)
    return clone


def _run_gate(clone: Path, *extra: str) -> tuple[int, str]:
    """Run the cloned gate and capture its combined output.

    Args:
        clone: Clone root.
        extra: Extra CLI arguments.

    Returns:
        ``(exit_code, output)``.
    """
    import subprocess

    command = [
        sys.executable,
        "-B",
        str(clone / "scripts" / "check_frontend_baseline.py"),
        "--repo-root",
        str(clone),
        *extra,
    ]
    completed = subprocess.run(
        command, cwd=str(clone), capture_output=True, text=True, timeout=120, check=False
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _replace_once(path: Path, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` exactly once (mutation helper).

    Args:
        path: File to rewrite.
        old: Anchor text, must occur exactly once.
        new: Replacement.

    Raises:
        RuntimeError: The anchor is missing or ambiguous.
    """
    text = path.read_text(encoding="utf-8")
    occurrences = text.count(old)
    if occurrences != 1:
        raise RuntimeError(
            f"mutation anchor occurs {occurrences} time(s) in {path.as_posix()}, expected 1"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _self_test(repo_root: Path, registry: S1Registry) -> int:
    """Run the five injections that prove the gate can move in both directions.

    The injections (design §1.7.2-c, plus one floor proof):

    1. ``"msw": "^2"`` in ``packages/e2e/package.json`` -> red;
    2. empty ``tests/e2e/`` (4 of 9 files gone) -> ``INVALID`` (not green);
    3. drop the ``ABSENT`` registration row -> red;
    4. add ``apps/web/src/msw-setup.mjs`` -> excluded (green), then remove the
       exclusion -> red;
    5. empty ``packages/`` **and** the floor lowered to ``0`` -> green, which is
       exactly the fake green the floor exists to prevent.

    Args:
        repo_root: Real repository root.
        registry: The real registry.

    Returns:
        ``0`` when every injection behaved, ``9`` otherwise.
    """
    checks: list[tuple[str, bool, str]] = []

    def record(label: str, ok: bool, detail: str) -> None:
        checks.append((label, ok, detail))
        _gate_io.log(TAG, f"  {'PASS' if ok else 'FAIL'}  {label} :: {detail}")

    # --- control: the untouched clone must be PASS -------------------------
    clone = _prepare_clone(repo_root, registry)
    code, output = _run_gate(clone)
    record(
        "control clone is PASS",
        code == 0 and "S1 coverage:" in output,
        f"exit={code} last={output.strip().splitlines()[-1] if output.strip() else ''}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # --- 1: msw declared in package.json -> red ---------------------------
    clone = _prepare_clone(repo_root, registry)
    package_json = clone / "packages" / "e2e" / "package.json"
    document = json.loads(package_json.read_text(encoding="utf-8"))
    document.setdefault("devDependencies", {})["msw"] = "^2"
    package_json.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    code, output = _run_gate(clone)
    record(
        "inject msw into package.json -> red",
        code == 1 and "msw" in output,
        f"exit={code}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # --- 2: empty tests/e2e -> INVALID (never green) ----------------------
    clone = _prepare_clone(repo_root, registry)
    shutil.rmtree(clone / "packages" / "e2e" / "tests", ignore_errors=True)
    code, output = _run_gate(clone)
    record(
        "empty tests/e2e -> INVALID",
        code == 1 and "INVALID" in output and "EMPTY" in output,
        f"exit={code}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # --- 3: registration disagrees with the tree -> red -------------------
    # V0.1.0 note: the old form of this injection *deleted* the ``ABSENT`` row for
    # ``contracts/frontend-baseline/**``.  That root now exists and is registered
    # ``OK``, so deleting its row leaves an unregistered-but-present root — which
    # the gate deliberately allows (only an unregistered **absence** is INVALID).
    # The injection therefore stopped moving the gate (measured ``exit=0``).
    # Replaced by the equivalent, equally strict assertion: mark a *present* root
    # as ``ABSENT`` and require red (registry and tree disagree).  Strength is
    # preserved, not relaxed.
    clone = _prepare_clone(repo_root, registry)
    clone_registry = clone / registry.path.relative_to(repo_root) if registry.path else None
    anchor = "| `contracts/frontend-baseline/**` | OK |"
    if clone_registry is not None and clone_registry.is_file():
        try:
            _replace_once(
                clone_registry,
                anchor,
                "| `contracts/frontend-baseline/**` | ABSENT |",
            )
        except RuntimeError as error:
            record("registry says ABSENT while the tree exists -> red", False, str(error))
        else:
            code, output = _run_gate(clone)
            record(
                "registry says ABSENT while the tree exists -> red",
                code == 1 and "INVALID" in output,
                f"exit={code}",
            )
    else:  # pragma: no cover - registry missing means the control already failed
        record("registry says ABSENT while the tree exists -> red", False, "registry not in clone")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # --- 4: apps/web/src exclusion ---------------------------------------
    clone = _prepare_clone(repo_root, registry)
    weird = clone / "apps" / "web" / "src"
    weird.mkdir(parents=True, exist_ok=True)
    (weird / "msw-setup.mjs").write_text(
        "import { setupServer } from 'msw/node';\nexport const server = setupServer();\n",
        encoding="utf-8",
    )
    code_excluded, output_excluded = _run_gate(clone)
    _replace_once(
        clone / "scripts" / "check_frontend_baseline.py",
        f'EXCLUDE_GLOBS: Final[tuple[str, ...]] = ("{EXCLUDE_GLOBS[0]}",)',
        "EXCLUDE_GLOBS: Final[tuple[str, ...]] = ()",
    )
    code_removed, output_removed = _run_gate(clone)
    record(
        "apps/web/src excluded, dropping the exclusion -> red",
        code_excluded == 0 and code_removed == 1 and "msw" in output_removed,
        f"excluded={code_excluded} removed={code_removed}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # --- 5: floor proof — MIN_FILES=0 on an empty tree is green -----------
    clone = _prepare_clone(repo_root, registry)
    # 5 files left: under the floor, but **not** empty, so the only thing that can
    # refuse it is the floor itself (the zero-file rule is a separate guard).
    shutil.rmtree(clone / "packages" / "e2e" / "tests", ignore_errors=True)
    code_floor, output_floor = _run_gate(clone)
    _replace_once(
        clone / "scripts" / "check_frontend_baseline.py",
        f"MIN_FILES = {MIN_FILES}",
        "MIN_FILES = 0",
    )
    code_open, output_open = _run_gate(clone)
    record(
        "floor proof: 5-file tree is INVALID, MIN_FILES=0 turns it green",
        code_floor == 1 and "EMPTY" in output_floor and code_open == 0,
        f"floor6={code_floor} floor0={code_open}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    failures = [label for label, ok, _ in checks if not ok]
    _gate_io.log(TAG, f"self-test: {len(checks) - len(failures)}/{len(checks)} passed")
    if failures:
        _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({len(failures)} injection(s))")
        return _gate_io.EXIT_SELFTEST
    _gate_io.log(TAG, "SELFTEST VERDICT: PASS (the gate moves in both directions)")
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
        prog="check_frontend_baseline.py",
        description=(
            "S-1: per-root three-state scan of the frontend surface (no msw, no mock "
            "server, zero dependencies), with a MIN_FILES floor so an empty glob can "
            "never pass."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=None, metavar="DIR", help="repository root")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="口径 X: literal coverage, every declared root must exist (exit 1 otherwise)",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--self-test", action="store_true", help="run the five injections (exit 9 on failure)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``1`` / ``2`` / ``9`` (design §3.3).
    """
    parser = _build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = (
        Path(arguments.repo_root).expanduser().resolve()
        if arguments.repo_root is not None
        else _SCRIPTS_DIR.parent
    )
    if not repo_root.is_dir():
        _gate_io.log(TAG, f"ERROR: repo root does not exist: {repo_root.as_posix()}")
        return _gate_io.EXIT_USAGE

    registry = load_registry(repo_root)
    if arguments.self_test:
        try:
            return _self_test(repo_root, registry)
        except (RuntimeError, OSError) as error:
            _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({error})")
            return _gate_io.EXIT_SELFTEST

    paths = _gate_io.GatePaths.resolve(repo_root=repo_root)
    reports = scan(paths, registry)
    exclusion_state, exclusion_files, exclusion_violations = _exclusion_report(repo_root)
    violations = evaluate(reports, strict=bool(arguments.strict))

    if arguments.json:
        print(
            json.dumps(
                {
                    "generated_at": _gate_io.utc_now_iso(),
                    "repo_root": repo_root.as_posix(),
                    "strict": bool(arguments.strict),
                    "registry": {
                        "path": registry.path.as_posix() if registry.path else None,
                        "entries": {key: entry.render() for key, entry in registry.entries.items()},
                        "problems": registry.problems,
                    },
                    "roots": [
                        {
                            "root": report.root,
                            "state": report.state,
                            "files": report.files,
                            "msw_hits": list(report.msw_hits),
                            "dep_declared": list(report.dep_declared),
                            "setup_server_files": list(report.setup_server_files),
                            "declared_owner": report.declared_owner,
                            "reason": report.reason,
                        }
                        for report in reports
                    ],
                    "exclusion": {
                        "root": EXCLUDE_GLOBS[0],
                        "state": exclusion_state,
                        "files": exclusion_files,
                        "violations": exclusion_violations,
                    },
                    "violations": violations,
                    "coverage": {
                        "effective": sum(1 for report in reports if report.effective),
                        "total": len(reports),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    render(
        paths,
        registry,
        reports,
        violations,
        strict=bool(arguments.strict),
        exclusion_state=exclusion_state,
        exclusion_files=exclusion_files,
        exclusion_violations=exclusion_violations,
    )
    if violations or exclusion_violations or registry.problems:
        return _gate_io.EXIT_VIOLATION
    return _gate_io.EXIT_OK


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
