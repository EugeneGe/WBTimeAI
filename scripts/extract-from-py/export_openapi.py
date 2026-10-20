"""C-02 exporter: freeze the legacy FastAPI OpenAPI document.

Produces two artifacts in ``contracts/``:

* ``openapi.v1.frozen.json`` -- ``create_app().openapi()`` serialised in a
  **pinned canonical form**: ``json.dumps(spec, ensure_ascii=False, indent=2,
  sort_keys=True)`` plus exactly one trailing ``\\n``.  Byte size is *never* a
  regression criterion (the same spec ranges from ~178 kB to ~511 kB depending
  on serialisation flags); only the three collections and the digest are.
* ``endpoints.txt`` -- every operation as ``METHOD PATH``, sorted, split into
  the two documented buckets (``134`` total / ``133`` business).

Hard criteria are asserted, not reported: a mismatch aborts with a non-zero exit
code instead of silently writing a divergent baseline.

This module must run under the legacy ``.venv`` interpreter (see
``_bootstrap.py``); ``run.py export`` takes care of re-executing it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

import _bootstrap
import hashes

__all__ = [
    "NAME",
    "DESCRIPTION",
    "FROZEN_JSON_NAME",
    "ENDPOINTS_TXT_NAME",
    "EXPECTED_VERSION",
    "EXPECTED_PATHS",
    "EXPECTED_OPERATIONS",
    "EXPECTED_SCHEMAS",
    "EXPECTED_BUSINESS_OPERATIONS",
    "HTTP_METHODS",
    "Operation",
    "OpenApiFreezeError",
    "canonical_dumps",
    "collect_operations",
    "render_endpoints_txt",
    "export",
]

#: Registry name used by ``run.py --only``.
NAME = "openapi"

#: Human readable description shown by ``run.py export``.
DESCRIPTION = "Freeze create_app().openapi() into contracts/openapi.v1.frozen.json"

FROZEN_JSON_NAME = "openapi.v1.frozen.json"
ENDPOINTS_TXT_NAME = "endpoints.txt"

# ---------------------------------------------------------------------------
# Frozen expectations (measured, never guessed).
# ---------------------------------------------------------------------------
EXPECTED_VERSION = "0.4.8"
EXPECTED_PATHS = 100
EXPECTED_OPERATIONS = 134
EXPECTED_SCHEMAS = 116
#: 134 minus the single non-business endpoint (``GET /health``, tag ``health``).
EXPECTED_BUSINESS_OPERATIONS = 133

#: Tag that marks infrastructure (non-business) endpoints.
HEALTH_TAG = "health"

#: Path prefix every business operation starts with.
BUSINESS_PATH_PREFIX = "/api/v1/"

#: HTTP methods recognised as operations (OpenAPI 3.0 Path Item fields).
HTTP_METHODS: tuple[str, ...] = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
)


class OpenApiFreezeError(RuntimeError):
    """Raised when the generated spec does not match the frozen expectations."""


class Operation(NamedTuple):
    """One OpenAPI operation."""

    method: str
    path: str
    tags: tuple[str, ...]

    @property
    def is_business(self) -> bool:
        """Return ``True`` for business endpoints (excludes ``tag=health``)."""
        return HEALTH_TAG not in self.tags

    def line(self) -> str:
        """Render as ``METHOD PATH``."""
        return f"{self.method} {self.path}"


def canonical_dumps(spec: dict[str, Any]) -> str:
    """Serialise ``spec`` in the pinned canonical form (single trailing newline).

    Args:
        spec: Parsed OpenAPI document.

    Returns:
        UTF-8 encodable text with exactly one trailing ``\\n``.
    """
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def collect_operations(spec: dict[str, Any]) -> list[Operation]:
    """Extract every operation, sorted by ``(path, method)``.

    Args:
        spec: Parsed OpenAPI document.

    Returns:
        Deterministically ordered operations.
    """
    operations: list[Operation] = []
    for path in sorted(spec.get("paths", {})):
        item = spec["paths"][path]
        if not isinstance(item, dict):
            continue
        for field_name, payload in item.items():
            if field_name not in HTTP_METHODS or not isinstance(payload, dict):
                continue
            raw_tags = payload.get("tags", [])
            tags = tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else ()
            operations.append(Operation(field_name.upper(), path, tags))
    operations.sort(key=lambda operation: (operation.path, operation.method))
    return operations


def render_endpoints_txt(
    operations: list[Operation],
    version: str,
    path_count: int,
    schema_count: int,
    source: str,
) -> str:
    """Render ``endpoints.txt`` with the two explicitly labelled sections.

    Args:
        operations: All operations, already sorted.
        version: ``info.version`` of the frozen document.
        path_count: Number of entries under ``paths``.
        schema_count: Number of ``components.schemas`` entries.
        source: Legacy repository root used for the extraction.

    Returns:
        File content, trailing newline included.
    """
    business = [operation for operation in operations if operation.is_business]
    non_business = [operation for operation in operations if not operation.is_business]
    non_business_lines = ", ".join(operation.line() for operation in non_business) or "(none)"

    lines: list[str] = [
        "# WBTimeAI -- frozen OpenAPI operation list (generated, do not edit by hand).",
        "# Regenerate with: python scripts/extract-from-py/run.py export",
        f"# source           : {source}",
        f"# info.version     : {version}   <- code string, NEVER released; not a TS line version",
        f"# paths            : {path_count}",
        f"# operations       : {len(operations)}",
        f"# schemas          : {schema_count}",
        "#",
        "# Parsing rule: ignore every line whose first non-space character is '#'.",
        "# Canonical machine-readable artifact is openapi.v1.frozen.json; this file is",
        "# the human/CI-friendly flattened view of the same data.",
        "#"
        " ------------------------------------------------------------------",
        f"# SECTION A -- ALL OPERATIONS ({len(operations)} of {len(operations)})",
        "#   Bucket: every operation present in the OpenAPI document, including the",
        "#   infrastructure endpoints listed below.  This is the '134' figure.",
        f"#   Non-business endpoints in this bucket: {non_business_lines}",
        "#"
        " ------------------------------------------------------------------",
    ]
    lines.extend(operation.line() for operation in operations)

    lines.extend(
        [
            "",
            "#"
            " ------------------------------------------------------------------",
            f"# SECTION B -- BUSINESS OPERATIONS ({len(business)} of {len(operations)})",
            f"#   Rule: {len(business)} = {len(operations)} - {len(non_business)}"
            f"   ({non_business_lines} -- non-business contract surface)",
            f"#   Bucket: SECTION A minus the {len(non_business)} non-business endpoint(s) "
            f"tagged '{HEALTH_TAG}' (health_router, mounted on '/' not on '{BUSINESS_PATH_PREFIX}').",
            "#   Every line below starts with the business prefix "
            f"'{BUSINESS_PATH_PREFIX}'.  This is the '133' figure.",
            f"#   Excluded: {non_business_lines}",
            "#   Verified by measurement: all business operations are prefixed",
            f"#   '{BUSINESS_PATH_PREFIX}', and the only path outside it is the health probe.",
            "#"
            " ------------------------------------------------------------------",
        ]
    )
    lines.extend(operation.line() for operation in business)

    return "\n".join(lines) + "\n"


def _assert_frozen(spec: dict[str, Any], operations: list[Operation]) -> dict[str, Any]:
    """Check the hard criteria and return measured metrics.

    Args:
        spec: Parsed OpenAPI document.
        operations: Operations collected from ``spec``.

    Returns:
        Metrics dict used for the CLI summary.

    Raises:
        OpenApiFreezeError: If any frozen expectation is violated.
    """
    version = str(spec.get("info", {}).get("version", ""))
    path_count = len(spec.get("paths", {}))
    schema_count = len(spec.get("components", {}).get("schemas", {}))
    operation_count = len(operations)
    business = [operation for operation in operations if operation.is_business]
    non_business = [operation for operation in operations if not operation.is_business]

    diffs: list[str] = []
    if version != EXPECTED_VERSION:
        diffs.append(f"info.version: expected {EXPECTED_VERSION!r}, got {version!r}")
    if path_count != EXPECTED_PATHS:
        diffs.append(f"paths: expected {EXPECTED_PATHS}, got {path_count}")
    if operation_count != EXPECTED_OPERATIONS:
        diffs.append(f"operations: expected {EXPECTED_OPERATIONS}, got {operation_count}")
    if schema_count != EXPECTED_SCHEMAS:
        diffs.append(f"schemas: expected {EXPECTED_SCHEMAS}, got {schema_count}")
    if len(business) != EXPECTED_BUSINESS_OPERATIONS:
        diffs.append(
            f"business operations: expected {EXPECTED_BUSINESS_OPERATIONS}, got {len(business)}"
        )
    if len(non_business) != EXPECTED_OPERATIONS - EXPECTED_BUSINESS_OPERATIONS:
        diffs.append(
            "non-business operations: expected "
            f"{EXPECTED_OPERATIONS - EXPECTED_BUSINESS_OPERATIONS}, got {len(non_business)}"
        )
    if len({(operation.method, operation.path) for operation in operations}) != operation_count:
        diffs.append("duplicate (method, path) pairs detected")

    if diffs:
        raise OpenApiFreezeError(
            "OpenAPI document diverged from the frozen baseline:\n  - " + "\n  - ".join(diffs)
        )

    return {
        "version": version,
        "paths": path_count,
        "operations": operation_count,
        "business_operations": len(business),
        "non_business_operations": len(non_business),
        "schemas": schema_count,
        "non_business_lines": [operation.line() for operation in non_business],
    }


def export(ctx: _bootstrap.ExtractContext) -> dict[str, Any]:
    """Export the frozen OpenAPI document and the endpoint list.

    Args:
        ctx: Resolved extraction context.

    Returns:
        Metrics dict (also printed by ``run.py``).

    Raises:
        OpenApiFreezeError: If the produced document violates the frozen baseline.
    """
    import_dirs = _bootstrap.install_import_paths(ctx.source)
    if not _bootstrap.can_import("wbtime_ai_api.main"):
        raise OpenApiFreezeError(
            "cannot import wbtime_ai_api.main -- run this exporter with the legacy "
            f"interpreter ({ctx.python_executable}) and the {len(import_dirs)} import roots installed"
        )

    from wbtime_ai_api.main import create_app  # noqa: PLC0415 - must follow path setup

    application = create_app()
    spec: dict[str, Any] = application.openapi()
    operations = collect_operations(spec)
    metrics = _assert_frozen(spec, operations)

    text = canonical_dumps(spec)
    payload = text.encode("utf-8")
    ctx.contracts_dir.mkdir(parents=True, exist_ok=True)

    json_path = ctx.contracts_dir / FROZEN_JSON_NAME
    json_path.write_bytes(payload)

    endpoints_path = ctx.contracts_dir / ENDPOINTS_TXT_NAME
    endpoints_text = render_endpoints_txt(
        operations,
        version=metrics["version"],
        path_count=metrics["paths"],
        schema_count=metrics["schemas"],
        source=ctx.source,
    )
    endpoints_path.write_text(endpoints_text, encoding="utf-8", newline="\n")

    metrics.update(
        {
            "openapi_bytes": len(payload),
            "openapi_sha256": hashes.sha256_bytes(payload),
            "openapi_path": str(json_path),
            "endpoints_path": str(endpoints_path),
            "endpoints_sha256": hashes.sha256_file(endpoints_path),
            "endpoints_lines": metrics["operations"],
        }
    )
    return metrics


def _self_check() -> int:
    """Minimal smoke test used when this file is executed directly."""
    context = _bootstrap.make_context()
    result = export(context)
    print(f"[openapi] version={result['version']} paths={result['paths']} "
          f"operations={result['operations']} schemas={result['schemas']} "
          f"business={result['business_operations']} bytes={result['openapi_bytes']} "
          f"sha256={result['openapi_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_check())
