"""CLI entry point for the contract extraction toolkit (C-01).

Sub-commands
------------
``export``
    Run every registered exporter against the legacy tree, then regenerate
    ``contracts/manifest.sha256``.
``check``
    Verify ``contracts/manifest.sha256`` byte-for-byte.  Deliberately does **not**
    touch the legacy tree, so the frozen baseline stays verifiable after
    ``D:/WBT/WBTimeAI_old`` is deleted.

Exit codes
----------
``0``
    Success / all digests match.
``1``
    ``check`` found a problem, or an exporter failed.
``2``
    Bootstrap problem (source tree or interpreter missing, bad arguments).

Only the Python standard library is used here.  Extractor modules are discovered
by convention (see :func:`discover_exporters`) so that sibling work such as
``ddl/`` can register itself **without** this file depending on it.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

import _bootstrap
import contract_manifest
import hashes

__all__ = [
    "PROG",
    "EXPORTER_PREFIX",
    "EXPORTER_ENTRY_NAMES",
    "Exporter",
    "discover_exporters",
    "main",
]

PROG = "extract-from-py"

#: Local modules named ``export_<name>.py`` are picked up as exporters.
EXPORTER_PREFIX = "export_"

#: Attributes an optional exporter package may expose (in priority order).
EXPORTER_ENTRY_NAMES: tuple[str, ...] = ("EXPORTERS", "exporters", "EXPORTER", "export")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BOOTSTRAP_ERROR = 2


class Exporter:
    """A named exporter bound to a callable ``export(ctx) -> dict``.

    Attributes:
        name: Registry name, used by ``--only`` and in log lines.
        description: One-line explanation printed by ``export``.
        run: Callable performing the export.
    """

    def __init__(self, name: str, description: str, run: Callable[[_bootstrap.ExtractContext], Any]) -> None:
        self.name = str(name)
        self.description = str(description)
        self.run = run

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Exporter(name={self.name!r})"


# ---------------------------------------------------------------------------
# Exporter discovery
# ---------------------------------------------------------------------------


def _load_module_from_file(path: Path) -> ModuleType:
    """Import a standalone module by file path under a private name."""
    module_name = f"_wbtime_extract_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _coerce_exporters(
    label: str,
    payload: Any,
    name_hint: str | None = None,
    description_hint: str | None = None,
) -> list[Exporter]:
    """Normalise whatever an exporter module exposes into :class:`Exporter` objects.

    Args:
        label: Fallback name (usually the module or package name).
        payload: ``EXPORTERS`` / ``exporters`` / ``EXPORTER`` / ``export`` value.
        name_hint: Module-level ``NAME`` to prefer over ``label``.
        description_hint: Module-level ``DESCRIPTION`` to prefer over the default.

    Returns:
        Zero or more exporters, in declaration order.
    """
    if payload is None:
        return []
    if isinstance(payload, Exporter):
        chosen = name_hint or payload.name
        return [Exporter(chosen, description_hint or payload.description, payload.run)]
    if callable(payload):
        chosen = name_hint or label
        return [Exporter(chosen, description_hint or chosen, payload)]
    if isinstance(payload, (list, tuple)):
        exporters: list[Exporter] = []
        for item in payload:
            exporters.extend(_coerce_exporters(label, item, name_hint, description_hint))
        return exporters
    # An object with an ``export`` attribute (duck-typed exporter instance).
    method = getattr(payload, "export", None)
    if callable(method):
        name = str(name_hint or getattr(payload, "NAME", label))
        description = str(description_hint or getattr(payload, "DESCRIPTION", name))
        return [Exporter(name, description, method)]
    return []


def discover_exporters(script_directory: Path | None = None) -> tuple[list[Exporter], list[str]]:
    """Find all exporters, built-in first then optional packages.

    A module ``export_<x>.py`` in the toolkit directory registers itself through a
    module-level ``export(ctx)`` callable (plus optional ``NAME`` / ``DESCRIPTION``).

    A sub-directory that looks like a package (``__init__.py`` present) and does
    **not** start with ``_`` is treated as optional: it is imported only when it
    exists and imports cleanly, and may expose ``EXPORTERS`` / ``exporters`` /
    ``EXPORTER`` / ``export``.  Any import failure is reported as a skip, never as
    a hard error -- this is what keeps parallel work such as ``ddl/`` decoupled.

    Args:
        script_directory: Directory to scan; defaults to the toolkit directory.

    Returns:
        ``(exporters, notes)`` where ``notes`` are human-readable skip messages.
    """
    directory = Path(script_directory) if script_directory else _bootstrap.script_dir()
    exporters: list[Exporter] = []
    notes: list[str] = []

    if not directory.is_dir():
        return exporters, [f"toolkit directory not found: {directory}"]

    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

    for path in sorted(directory.glob(f"{EXPORTER_PREFIX}*.py")):
        try:
            module = _load_module_from_file(path)
        except Exception as error:  # noqa: BLE001 - report and continue
            notes.append(f"skip built-in exporter {path.name}: {error}")
            continue
        name = str(getattr(module, "NAME", path.stem[len(EXPORTER_PREFIX):]))
        description = str(getattr(module, "DESCRIPTION", ""))
        entry = getattr(module, "export", None)
        if not callable(entry):
            notes.append(f"skip built-in exporter {path.name}: no callable 'export(ctx)'")
            continue
        exporters.append(Exporter(name, description or name, entry))

    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name.startswith(("_", ".")) or child.name == "__pycache__":
            continue
        if not (child / "__init__.py").is_file():
            continue
        label = child.name
        found: list[Any] = []
        imported = False
        for candidate_name in (f"{label}.exporter", label):
            try:
                module = __import__(candidate_name, fromlist=["*"])
            except Exception as error:  # noqa: BLE001 - optional module, keep going
                notes.append(f"skip optional module {candidate_name}: {error}")
                continue
            imported = True
            for attribute in EXPORTER_ENTRY_NAMES:
                if hasattr(module, attribute):
                    found.append(getattr(module, attribute))
                    break
            if found:
                break
        if not imported:
            continue
        if not found:
            notes.append(f"skip optional module {label}: none of {', '.join(EXPORTER_ENTRY_NAMES)} present")
            continue
        name_hint = getattr(module, "NAME", None)
        description_hint = getattr(module, "DESCRIPTION", None)
        for payload in found:
            exporters.extend(
                _coerce_exporters(
                    label,
                    payload,
                    str(name_hint) if name_hint else None,
                    str(description_hint) if description_hint else None,
                )
            )

    # Second pass: loose ``<subdir>/export_*.py`` modules, loaded by file path.
    # This lets a sibling directory ship a standalone script (no package setup)
    # and still be picked up, as long as it exposes a module-level ``export(ctx)``.
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name.startswith(("_", ".")) or child.name == "__pycache__":
            continue
        for path in sorted(child.glob(f"{EXPORTER_PREFIX}*.py")):
            # Make sibling modules of the sub-directory importable while loading.
            injected = str(child) not in sys.path
            if injected:
                sys.path.insert(0, str(child))
            try:
                module = _load_module_from_file(path)
            except Exception as error:  # noqa: BLE001 - optional module, keep going
                notes.append(f"skip optional script {child.name}/{path.name}: {error}")
                continue
            finally:
                if injected and str(child) in sys.path:
                    sys.path.remove(str(child))
            entry = getattr(module, "export", None)
            if not callable(entry):
                notes.append(
                    f"skip optional script {child.name}/{path.name}: no callable 'export(ctx)' "
                    f"(expose export(ctx) or add {child.name}/exporter.py to run inside 'export')"
                )
                continue
            name = str(getattr(module, "NAME", path.stem[len(EXPORTER_PREFIX):]))
            description = str(getattr(module, "DESCRIPTION", "")) or name
            exporters.append(Exporter(name, description, entry))

    # De-duplicate by name while preserving the first definition.
    unique: list[Exporter] = []
    seen: set[str] = set()
    for exporter in exporters:
        if exporter.name in seen:
            notes.append(f"skip duplicate exporter name {exporter.name!r}")
            continue
        seen.add(exporter.name)
        unique.append(exporter)

    return unique, notes


# ---------------------------------------------------------------------------
# Output helpers (ASCII only: Windows consoles default to a legacy code page)
# ---------------------------------------------------------------------------


def _echo(message: str = "") -> None:
    """Print a line to stdout without relying on the console code page."""
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _echo_err(message: str) -> None:
    """Print a line to stderr."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _print_paths(source: str) -> None:
    """Print the resolved import roots (reproducibility evidence)."""
    pairs = _bootstrap.describe_pythonpath(source)
    _echo(f"  PYTHONPATH segments: {len(pairs)}")
    for index, directory in pairs:
        _echo(f"    [{index:02d}] {directory}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_check(contracts: Path) -> int:
    """Verify both ledgers; never touches the legacy tree."""
    _echo(f"[check] contracts dir: {contracts.as_posix()}")
    if not contracts.is_dir():
        _echo_err(f"[check] FAILED: contracts directory not found: {contracts.as_posix()}")
        return EXIT_FAILURE

    result = hashes.verify_manifest(contracts)
    dual_ok, dual_problems = contract_manifest.verify(contracts, _bootstrap.repo_root())

    problems = list(result.problems) + list(dual_problems)
    if problems:
        for problem in problems:
            _echo_err(f"[check] FAILED: {problem}")
        _echo_err(
            f"[check] {len(problems)} problem(s) "
            f"(sha256 ledger {len(result.problems)}, dual ledger {len(dual_problems)}), "
            f"{result.checked} entr(ies) checked"
        )
        return EXIT_FAILURE

    _echo(f"[check] OK: {result.checked} artifact(s) match {hashes.MANIFEST_NAME}")
    _echo(f"[check] OK: dual ledger consistent ({contract_manifest.MANIFEST_JSON_NAME})")

    for path in hashes.iter_artifact_files(contracts):
        digest = hashes.sha256_file(path)
        _echo(f"  {digest[:12]}  {path.relative_to(contracts).as_posix()}")
    return EXIT_OK


def _maybe_reexec(argv: Sequence[str]) -> int | None:
    """Re-run this command under the legacy interpreter when needed.

    Returns:
        ``None`` when the current interpreter is already correct (caller should
        continue in-process), otherwise the child exit code.
    """
    if os.environ.get(_bootstrap.REEXEC_ENV_VAR) == "1":
        return None
    try:
        wanted = _bootstrap.resolve_python(_bootstrap.resolve_source(_extract_source_option(argv)))
    except _bootstrap.BootstrapError as error:
        _echo_err(f"[export] {error}")
        return EXIT_BOOTSTRAP_ERROR

    if _bootstrap.same_interpreter(sys.executable, wanted):
        return None
    if _bootstrap.can_import("wbtime_ai_api.main"):
        # Already usable (e.g. launched from a properly configured env).
        return None

    _echo(f"[export] re-executing under legacy interpreter: {wanted}")
    environment = _bootstrap.child_env(_bootstrap.resolve_source(_extract_source_option(argv)))
    environment[_bootstrap.REEXEC_ENV_VAR] = "1"
    import subprocess  # noqa: PLC0415 - only needed on the re-exec path

    completed = subprocess.run(  # noqa: S603 - deliberate, argv is internal
        [wanted, str(Path(__file__).resolve()), *argv],
        env=environment,
        cwd=str(_bootstrap.repo_root()),
        check=False,
    )
    return completed.returncode


def _extract_source_option(argv: Sequence[str]) -> str | None:
    """Pull ``--source`` out of a raw argv list before full parsing."""
    tokens = list(argv)
    for index, token in enumerate(tokens):
        if token == "--source" and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--source="):
            return token.split("=", 1)[1]
    return None


def cmd_export(
    source: str | None,
    output_dir: str | None,
    only: list[str] | None,
) -> int:
    """Run every selected exporter, then rebuild the manifest."""
    try:
        context = _bootstrap.make_context(source=source, output_dir=output_dir)
    except _bootstrap.BootstrapError as error:
        _echo_err(f"[export] {error}")
        return EXIT_BOOTSTRAP_ERROR

    _echo(f"[export] source: {context.source}")
    _echo(f"[export] interpreter: {context.python_executable}")
    _echo(f"[export] contracts: {context.contracts_dir.as_posix()}")
    _print_paths(context.source)

    exporters, notes = discover_exporters(context.script_dir)
    for note in notes:
        _echo(f"  note: {note}")
    if not exporters:
        _echo_err("[export] FAILED: no exporters discovered")
        return EXIT_FAILURE

    selected = exporters
    if only:
        wanted = {name.strip() for name in only if name.strip()}
        unknown = wanted - {exporter.name for exporter in exporters}
        if unknown:
            _echo_err(f"[export] FAILED: unknown exporter(s): {', '.join(sorted(unknown))}")
            _echo_err(f"[export] available: {', '.join(exporter.name for exporter in exporters)}")
            return EXIT_BOOTSTRAP_ERROR
        selected = [exporter for exporter in exporters if exporter.name in wanted]

    failures: list[str] = []
    for exporter in selected:
        _echo(f"[export] running {exporter.name}: {exporter.description}")
        try:
            result = exporter.run(context)
        except Exception as error:  # noqa: BLE001 - one exporter must not hide others
            failures.append(f"{exporter.name}: {error}")
            _echo_err(f"[export] FAILED {exporter.name}: {error}")
            continue
        _report_exporter(exporter.name, result)

    if failures:
        _echo_err(f"[export] {len(failures)} exporter(s) failed; manifest not updated")
        return EXIT_FAILURE

    # Object ledger first: it must be on disk before the sha256 ledger so that
    # manifest.sha256 covers contract-manifest.json itself.
    try:
        object_ledger, payload = contract_manifest.write(context.contracts_dir, context.repo_root)
    except contract_manifest.ManifestConsistencyError as error:
        _echo_err(f"[export] FAILED to build {contract_manifest.MANIFEST_JSON_NAME}: {error}")
        return EXIT_FAILURE
    objects = payload["objects"]
    by_source: dict[str, int] = {}
    for item in objects:
        key = str(item["source"])
        by_source[key] = by_source.get(key, 0) + 1
    pending = [item["id"] for item in payload["criteria"] if item["status"] == "pending"]
    _echo(
        f"[export] contract manifest: {object_ledger.name} objects={len(objects)} "
        f"by_source={by_source} criteria={len(payload['criteria'])} pending={pending or 'none'}"
    )

    manifest = hashes.write_manifest(context.contracts_dir)
    _echo(f"[export] manifest written: {manifest.as_posix()}")
    verification = hashes.verify_manifest(context.contracts_dir)
    if not verification.ok:
        for problem in verification.problems:
            _echo_err(f"[export] FAILED: {problem}")
        return EXIT_FAILURE
    _echo(f"[export] OK: {verification.checked} artifact(s) recorded and verified")

    dual_ok, dual_problems = contract_manifest.verify(context.contracts_dir, context.repo_root)
    if not dual_ok:
        for problem in dual_problems:
            _echo_err(f"[export] FAILED (dual ledger): {problem}")
        return EXIT_FAILURE
    _echo(f"[export] OK: dual ledger consistent ({len(objects)} object record(s))")
    for path in hashes.iter_artifact_files(context.contracts_dir):
        digest = hashes.sha256_file(path)
        _echo(f"  {digest[:12]}  {path.relative_to(context.contracts_dir).as_posix()}")
    return EXIT_OK


def _report_exporter(name: str, result: Any) -> None:
    """Print a compact summary of one exporter result."""
    if not isinstance(result, dict):
        _echo(f"  [ok] {name}")
        return
    # Exporters that produce a large, self-describing artifact (C-04 / C-05)
    # supply a one-line ``summary`` instead of the OpenAPI-shaped metric keys.
    if "summary" in result:
        _echo(f"  [ok] {name} {result['summary']}")
        return
    pairs = []
    for key in (
        "version",
        "paths",
        "operations",
        "business_operations",
        "schemas",
        "openapi_bytes",
    ):
        if key in result:
            pairs.append(f"{key}={result[key]}")
    if "openapi_sha256" in result:
        pairs.append(f"sha256={str(result['openapi_sha256'])[:12]}")
    if pairs:
        _echo(f"  [ok] {name} " + " ".join(pairs))
    else:
        _echo(f"  [ok] {name}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--source",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help=f"legacy repository root (default: ${_bootstrap.SOURCE_ENV_VAR} or {_bootstrap.DEFAULT_SOURCE})",
    )
    common.add_argument(
        "--contracts-dir",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="contract output directory (default: <repo>/contracts)",
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Extract frozen contracts from the legacy WBTimeAI Python tree.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{export,check}")

    export_parser = subparsers.add_parser(
        "export",
        parents=[common],
        help="run all exporters and regenerate contracts/manifest.sha256",
    )
    export_parser.add_argument(
        "--only",
        metavar="NAMES",
        default=None,
        help="comma separated exporter names to run (default: all)",
    )

    check_parser = subparsers.add_parser(
        "check",
        parents=[common],
        help="verify contracts/manifest.sha256 without the legacy tree",
    )
    check_parser.set_defaults(command="check")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` ok, ``1`` verification/export failure,
        ``2`` bootstrap or usage error).
    """
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser()
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exit_error:  # argparse already printed usage
        return int(exit_error.code or EXIT_BOOTSTRAP_ERROR)

    command = getattr(args, "command", None)
    source = getattr(args, "source", None)
    contracts_option = getattr(args, "contracts_dir", None)

    if command == "check":
        contracts = (
            Path(contracts_option).resolve() if contracts_option else _bootstrap.contracts_dir()
        )
        return cmd_check(contracts)

    if command == "export":
        reexec_code = _maybe_reexec(raw_args)
        if reexec_code is not None:
            return reexec_code
        only_option = getattr(args, "only", None)
        only = [name for name in only_option.split(",")] if only_option else None
        return cmd_export(source=source, output_dir=contracts_option, only=only)

    parser.print_help(sys.stdout)
    return EXIT_BOOTSTRAP_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
