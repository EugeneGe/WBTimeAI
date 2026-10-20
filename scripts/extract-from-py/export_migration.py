"""C-06 exporter: test migration map + conformance skeletons.

Registered automatically by :mod:`run` because this file is named
``export_*.py`` and exposes a module-level ``export(ctx)`` — no change to
``run.py`` was needed, which is exactly what the toolkit's registration contract
promises (see ``scripts/extract-from-py/README.md`` §5).

What it writes (all under ``ctx.contracts_dir``):

``test-migration-map.csv``
    One row per legacy test case with its ①/②/③ disposition.
``conformance/tenant-404.yaml``
``conformance/idempotency.yaml``
``conformance/content-negotiation.yaml``
``conformance/stringly-contracts.yaml``
    Four skeletons; every ``source`` line is verified against the legacy tree.
``test-migration-summary.json``
    Counts + the 1661-vs-1699 caliber registration + input/output digests.

Inputs are the ledgers under ``migration/inputs/``.  ``collect.json`` is
regenerated on demand (≈12 s) when missing; ``outcomes.json`` is **not**
regenerated here because a full legacy run takes tens of minutes and needs
PostgreSQL/Docker — run ``migration/run_suite.py`` for that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import _bootstrap
from migration import build, inventory

__all__ = ["NAME", "DESCRIPTION", "export", "REGENERATE_COLLECT"]

NAME = "migration"

DESCRIPTION = "Test migration map (1699 rows) + conformance skeletons (4 YAML)"

#: Set to ``0`` to forbid regenerating ``collect.json`` during ``export``.
REGENERATE_COLLECT = True


def export(ctx: _bootstrap.ExtractContext) -> dict[str, Any]:
    """Render every C-06 artifact and return a compact status dict.

    Args:
        ctx: Resolved extraction context (source tree + interpreter + contracts
            directory), supplied by ``run.py``.

    Returns:
        A dict consumed by ``run._report_exporter``; ``rows`` / ``bucket_1`` /
        ``bucket_2`` / ``bucket_3`` / ``conformance`` keys end up in the log line.

    Raises:
        migration.inventory.InventoryError: When the collection ledger is absent
            and cannot be regenerated.
        migration.classify.UnmatchedPathError: When a legacy test file has no
            classification rule (strict mode: never emit a silent ``TBD``).
        migration.conformance.SourceVerificationError: When a skeleton source
            reference does not match the legacy tree.
    """
    inputs = inventory.inputs_dir()
    inputs.mkdir(parents=True, exist_ok=True)
    collect_path = inputs / "collect.json"
    outcomes_path = inputs / "outcomes.json"

    regenerated = False
    if REGENERATE_COLLECT and not collect_path.is_file():
        collect_status = inventory.collect_inventory(
            source=ctx.source,
            python_executable=ctx.python_executable,
            pythonpath=ctx.pythonpath,
            destination=collect_path,
        )
        regenerated = True
        print(
            f"  [migration] collect ledger regenerated: "
            f"{collect_status['collected']} items (pytest {collect_status['pytest_version']})"
        )

    result = build.write_artifacts(
        contracts_dir=Path(ctx.contracts_dir),
        source_root=ctx.source,
        collect_path=collect_path,
        outcomes_path=outcomes_path,
        strict=True,
    )
    result["collect_regenerated"] = regenerated
    # ``run.py::_report_exporter`` prints any ``summary`` string verbatim (the
    # convention shared with the envelope / errors / sse exporters).
    result["summary"] = (
        f"rows={result['rows']} files={result['files']} "
        f"bucket=1:{result['bucket_1']}/2:{result['bucket_2']}/3:{result['bucket_3']} "
        f"case_overrides={result['case_overrides']} "
        f"collected={result['collected_raw']} selected={result['selected']} "
        f"outcome_covered={result['outcomes_covered']} "
        f"conformance={len(result['conformance'])} refs={result['conformance_refs']} "
        f"sha256={str(result['map_sha256'])[:12]}"
    )
    return result
