"""Reproducibility bootstrap for extracting contracts from the legacy Python repo.

This module is the single place that knows *how to talk to the legacy tree*:

* where the source root is (``--source`` > ``WBTIME_SOURCE`` > default),
* which ``*/src`` directories must be on ``PYTHONPATH``,
* which interpreter must be used (the legacy ``.venv``),
* how to normalise a path so that a **Windows** Python can actually open it.

Why an explicit ``PYTHONPATH`` instead of relying on the venv's editable install
-------------------------------------------------------------------------------
The legacy venv ships ``_editable_impl_wbtime_ai_*.pth`` files whose entire
content is a *hard-coded absolute path* pointing at the **new** project
(``D:\\WBT\\WBTimeAI\\packages\\*``), not at the legacy tree.  Importing through
those ``.pth`` entries therefore fails with ``ModuleNotFoundError`` (or, worse,
silently imports a different tree).  Every extractor must therefore prepend the
legacy ``*/src`` directories to ``PYTHONPATH`` explicitly.

Why the drive-letter form
-------------------------
Git Bash hands out MSYS paths (``/d/WBT/WBTimeAI_old``).  A Windows CPython
interpreter resolves such a string relative to the *current drive root*, i.e.
``/d/WBT`` becomes ``D:\\d\\WBT`` -- which does not exist.  Paths passed to a
Windows interpreter must therefore be normalised to ``D:/WBT/...``
(drive letter, forward slashes).  :func:`to_native_source_path` does that.

Only the Python standard library is used here.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "BootstrapError",
    "ExtractContext",
    "DEFAULT_SOURCE",
    "APP_NAMES",
    "PACKAGES_DIRNAME",
    "repo_root",
    "script_dir",
    "contracts_dir",
    "to_native_source_path",
    "collapse_slashes",
    "resolve_source",
    "enumerate_source_import_dirs",
    "build_pythonpath",
    "resolve_python",
    "same_interpreter",
    "install_import_paths",
    "can_import",
    "child_env",
    "make_context",
    "describe_pythonpath",
]

#: Fallback source root when neither ``--source`` nor ``WBTIME_SOURCE`` is set.
DEFAULT_SOURCE = "D:/WBT/WBTimeAI_old"

#: Environment variable that overrides :data:`DEFAULT_SOURCE`.
SOURCE_ENV_VAR = "WBTIME_SOURCE"

#: Legacy layout: ``<source>/packages/<name>/src``.
PACKAGES_DIRNAME = "packages"

#: Legacy layout: ``<source>/apps/<name>/src``.  Order is kept stable on purpose.
APP_NAMES: tuple[str, ...] = ("api", "cli", "worker")

#: Set to ``1`` before re-executing under the legacy interpreter (loop guard).
REEXEC_ENV_VAR = "WBTIME_EXTRACT_REEXEC"

_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


class BootstrapError(RuntimeError):
    """Raised when the legacy tree or its interpreter cannot be located."""


@dataclasses.dataclass(frozen=True)
class ExtractContext:
    """Everything an exporter needs, resolved once and passed down.

    Attributes:
        source: Absolute legacy source root, drive-letter/forward-slash form.
        python_executable: Interpreter that can import the ``wbtime_ai_*`` packages.
        pythonpath: ``os.pathsep``-joined import roots for the legacy tree.
        repo_root: Root of the new (contract target) repository.
        contracts_dir: Directory that receives frozen artifacts.
        script_dir: Directory that holds this extraction toolkit.
    """

    source: str
    python_executable: str
    pythonpath: str
    repo_root: Path
    contracts_dir: Path
    script_dir: Path


# ---------------------------------------------------------------------------
# Repository layout helpers (work for any checkout, no absolute paths baked in)
# ---------------------------------------------------------------------------


def script_dir() -> Path:
    """Return the directory containing this file (``scripts/extract-from-py``)."""
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    """Return the repository root (two levels above :func:`script_dir`)."""
    return script_dir().parent.parent


def contracts_dir() -> Path:
    """Return the contract output directory (``<repo>/contracts``)."""
    return repo_root() / "contracts"


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------


def collapse_slashes(value: str) -> str:
    """Collapse runs of ``/`` into one, preserving a leading UNC ``//`` prefix."""
    prefix = ""
    rest = value
    if rest.startswith("//"):
        prefix, rest = "//", rest[2:]
    out: list[str] = []
    for char in rest:
        if char == "/" and out and out[-1] == "/":
            continue
        out.append(char)
    return prefix + "".join(out)


def to_native_source_path(raw: str | os.PathLike[str]) -> str:
    """Normalise ``raw`` into a form a Windows or POSIX Python can open.

    On Windows this converts MSYS paths (``/d/WBT/x``) and backslash paths
    (``D:\\WBT\\x``) into ``D:/WBT/x``.  On POSIX it returns an absolute path.

    Args:
        raw: Path as typed by a human, or as produced by ``pwd -W``/Git Bash.

    Returns:
        Normalised, absolute, forward-slash path string.

    Raises:
        BootstrapError: If ``raw`` is empty.
    """
    text = str(raw).strip()
    if not text:
        raise BootstrapError("empty source path")

    if os.name != "nt":
        return os.path.abspath(os.path.expanduser(text))

    text = text.replace("\\", "/")
    msys = re.match(r"^/([A-Za-z])/(.*)$", text)
    if msys:
        text = f"{msys.group(1).upper()}:/{msys.group(2)}"
    text = collapse_slashes(text)
    # A bare drive ("D:") means "current dir on D:", which is never intended.
    if re.fullmatch(r"[A-Za-z]:", text):
        text = text + "/"
    return text


def resolve_source(explicit: str | None = None) -> str:
    """Resolve the legacy source root.

    Precedence: ``explicit`` (``--source``) > ``$WBTIME_SOURCE`` > :data:`DEFAULT_SOURCE`.

    Args:
        explicit: Value of the ``--source`` CLI option, if provided.

    Returns:
        Normalised absolute source root.

    Raises:
        BootstrapError: If the directory does not exist.
    """
    candidate = explicit or os.environ.get(SOURCE_ENV_VAR) or DEFAULT_SOURCE
    normalised = to_native_source_path(candidate)
    if not os.path.isdir(normalised):
        raise BootstrapError(
            f"legacy source root not found: {normalised!r} "
            f"(pass --source PATH or set ${SOURCE_ENV_VAR})"
        )
    return normalised


# ---------------------------------------------------------------------------
# Import path enumeration
# ---------------------------------------------------------------------------


def enumerate_source_import_dirs(source: str) -> list[str]:
    """List the ``*/src`` directories of the legacy tree that must be importable.

    Layout produced (stable order): every ``packages/<name>/src`` sorted by name,
    followed by ``apps/api/src``, ``apps/cli/src``, ``apps/worker/src`` (only the
    ones that actually exist).

    Args:
        source: Normalised source root.

    Returns:
        Absolute, forward-slash directory paths in deterministic order.
    """
    root = Path(source)
    import_dirs: list[str] = []

    packages_root = root / PACKAGES_DIRNAME
    if packages_root.is_dir():
        for package in sorted(packages_root.iterdir(), key=lambda p: p.name):
            candidate = package / "src"
            if package.is_dir() and candidate.is_dir():
                import_dirs.append(candidate.as_posix())

    for app_name in APP_NAMES:
        candidate = root / "apps" / app_name / "src"
        if candidate.is_dir():
            import_dirs.append(candidate.as_posix())

    if not import_dirs:
        raise BootstrapError(f"no */src directories found under {source!r}")
    return import_dirs


def build_pythonpath(import_dirs: Iterable[str]) -> str:
    """Join import roots with :data:`os.pathsep` (``;`` on Windows)."""
    return os.pathsep.join(import_dirs)


# ---------------------------------------------------------------------------
# Interpreter resolution
# ---------------------------------------------------------------------------


def resolve_python(source: str) -> str:
    """Return the legacy ``.venv`` interpreter path.

    Args:
        source: Normalised source root.

    Returns:
        Absolute interpreter path.

    Raises:
        BootstrapError: If no interpreter exists inside the legacy venv.
    """
    root = Path(source)
    if os.name == "nt":
        candidates = [root / ".venv" / "Scripts" / "python.exe"]
    else:
        candidates = [root / ".venv" / "bin" / "python3", root / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.as_posix()
    raise BootstrapError(
        f"legacy interpreter not found under {root / '.venv'!s}; "
        "expected .venv/Scripts/python.exe (Windows) or .venv/bin/python (POSIX)"
    )


def same_interpreter(left: str | None, right: str | None) -> bool:
    """Compare two interpreter paths, tolerating ``\\`` vs ``/`` and case."""
    if not left or not right:
        return False
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


# ---------------------------------------------------------------------------
# In-process import setup
# ---------------------------------------------------------------------------


def install_import_paths(source: str, prepend: bool = True) -> list[str]:
    """Make the legacy packages importable in the *current* process.

    Both ``sys.path`` and ``$PYTHONPATH`` are updated, so that subprocesses
    spawned by an exporter inherit the same view.

    Args:
        source: Normalised source root.
        prepend: When true the legacy roots win over anything else on ``sys.path``.

    Returns:
        The list of import roots that were installed.
    """
    import_dirs = enumerate_source_import_dirs(source)
    if prepend:
        for directory in reversed(import_dirs):
            if directory in sys.path:
                sys.path.remove(directory)
            sys.path.insert(0, directory)
    else:
        for directory in import_dirs:
            if directory not in sys.path:
                sys.path.append(directory)

    merged = build_pythonpath(import_dirs)
    previous = os.environ.get("PYTHONPATH", "")
    if previous:
        merged = merged + os.pathsep + previous
    os.environ["PYTHONPATH"] = merged
    return import_dirs


def can_import(module_name: str) -> bool:
    """Return ``True`` when ``module_name`` is importable in this process."""
    try:
        __import__(module_name)
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False
    return True


def child_env(source: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess environment that can import the legacy packages.

    Args:
        source: Normalised source root.
        base: Base environment; defaults to a copy of ``os.environ``.

    Returns:
        Environment dict with ``PYTHONPATH`` and a UTF-8 stdio encoding.
    """
    env = dict(base if base is not None else os.environ)
    env["PYTHONPATH"] = build_pythonpath(enumerate_source_import_dirs(source))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def describe_pythonpath(source: str) -> list[tuple[int, str]]:
    """Return ``(index, path)`` pairs for diagnostics."""
    return list(enumerate(enumerate_source_import_dirs(source)))


def run_python(
    source: str,
    arguments: Sequence[str],
    cwd: str | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the legacy interpreter with a correctly configured environment.

    Args:
        source: Normalised source root.
        arguments: Arguments forwarded to the interpreter.
        cwd: Working directory for the child process.
        capture: When true, capture stdout/stderr instead of inheriting them.

    Returns:
        The completed process.
    """
    return subprocess.run(  # noqa: S603 - deliberate, arguments are internal
        [resolve_python(source), *arguments],
        cwd=cwd,
        env=child_env(source),
        capture_output=capture,
        text=True,
        encoding="utf-8" if capture else None,
        check=False,
    )


# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------


def make_context(
    source: str | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> ExtractContext:
    """Resolve everything once and return an :class:`ExtractContext`.

    Args:
        source: Value of ``--source``; resolved via :func:`resolve_source`.
        output_dir: Override for the contract output directory.

    Returns:
        A frozen context object.

    Raises:
        BootstrapError: If the source tree or interpreter is missing.
    """
    resolved_source = resolve_source(source)
    contracts = Path(output_dir).resolve() if output_dir else contracts_dir()
    return ExtractContext(
        source=resolved_source,
        python_executable=resolve_python(resolved_source),
        pythonpath=build_pythonpath(enumerate_source_import_dirs(resolved_source)),
        repo_root=repo_root(),
        contracts_dir=contracts,
        script_dir=script_dir(),
    )
