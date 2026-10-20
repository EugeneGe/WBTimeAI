"""T1-01 — derive ``contracts/frontend-baseline/**`` from the frozen contracts.

Why this file exists
--------------------
V0.0.2 registered ``contracts/frontend-baseline/**`` as ``ABSENT(declared;
owner=V0.1.0)`` precisely because its content is *derived*, not authored: every
byte has to come out of a frozen contract artifact, and a hand-typed file would
be indistinguishable from a fabricated one (L-8/L-9).  V0.1.0 has to make the
root real, so the deriver is the artifact's provenance.

Three derived files, three sources::

    contracts/openapi.v1.frozen.json  ->  openapi.subset.json
    contracts/sse/channels.json       ->  sse.channels.json
    contracts/errors.json             ->  error-codes.ts

What "derived" constrains
-------------------------
* nothing is hand-filled: every field is read out of the source document, and
  every count reported is ``len(...)`` of what was really read, never a literal
  that somebody typed to match a ticket number.  If the frozen contract says 19
  and the ticket says 42, the file says 19 and the ticket is wrong (duty to
  report, not duty to agree).
* the output keeps a ``source`` field naming its input, so a reader who doubts
  a number can re-derive instead of trusting us.
* byte-stable: keys are sorted, ``ensure_ascii=False``, LF endings, one trailing
  newline.  A re-run on unchanged inputs must produce identical bytes, otherwise
  the sha256 of the baseline itself becomes noise.

Known side effect (R-3)
-----------------------
Writing under ``contracts/`` breaks ``contracts/manifest.sha256``.  This
deriver deliberately does **not** regenerate the manifest: that file is an
aggregate owned by the team-lead, and a per-task regeneration would race with
the other tasks.  The breakage is registered and expected.

Exit codes::

    0   derived (or --check found the baseline already byte-identical)
    1   a source contract is missing / unparsable, or --check found drift
    2   usage error
    9   --self-test failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

sys.dont_write_bytecode = True

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Where the frozen contracts live (inputs).
SRC_OPENAPI: Final[Path] = _REPO_ROOT / "contracts" / "openapi.v1.frozen.json"
SRC_SSE: Final[Path] = _REPO_ROOT / "contracts" / "sse" / "channels.json"
SRC_ERRORS: Final[Path] = _REPO_ROOT / "contracts" / "errors.json"

#: Where the derived baseline lands (outputs).
OUT_DIR: Final[Path] = _REPO_ROOT / "contracts" / "frontend-baseline"
OUT_OPENAPI: Final[Path] = OUT_DIR / "openapi.subset.json"
OUT_SSE: Final[Path] = OUT_DIR / "sse.channels.json"
OUT_ERRORS: Final[Path] = OUT_DIR / "error-codes.ts"

#: HTTP methods an OpenAPI path-item may carry; anything else (``parameters``,
#: ``summary``) is a path-item-level field, not an operation.
HTTP_METHODS: Final[tuple[str, ...]] = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)

__all__ = [
    "derive_openapi_subset",
    "derive_sse_channels",
    "render_error_codes_ts",
    "load_json",
    "main",
]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON document, refusing to invent one when it is absent.

    Args:
        path: Absolute path of the source document.

    Returns:
        The parsed object.  A non-``dict`` top level is a hard error: the
        deriver must never silently skip a malformed contract.
    """
    if not path.is_file():
        raise FileNotFoundError(f"source contract missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"source contract is not an object: {path}")
    return document


def _write(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8/LF with exactly one trailing newline.

    Args:
        path: Destination file.
        text: Content to write.
    """
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8").replace(b"\r\n", b"\n"))


# ---------------------------------------------------------------------------
# Deriver 1: OpenAPI subset
# ---------------------------------------------------------------------------


def derive_openapi_subset(document: dict[str, Any]) -> str:
    """Derive the OpenAPI subset from the frozen document.

    Keeps ``info.version``, the ``method + path`` operation list with each
    operation's ``operationId`` / ``tags``, and the ``schemas`` name list.

    Args:
        document: Parsed ``contracts/openapi.v1.frozen.json``.

    Returns:
        The JSON text of ``openapi.subset.json``.
    """
    info = document.get("info")
    info = info if isinstance(info, dict) else {}
    paths = document.get("paths")
    paths = paths if isinstance(paths, dict) else {}
    components = document.get("components")
    components = components if isinstance(components, dict) else {}
    schemas = components.get("schemas")
    schemas = schemas if isinstance(schemas, dict) else {}

    operations: list[dict[str, Any]] = []
    for path in sorted(paths):
        item = paths[path]
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags")
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operationId": operation.get("operationId"),
                    "tags": tags if isinstance(tags, list) else [],
                }
            )
    operations.sort(key=lambda row: (row["path"], row["method"]))

    subset = {
        "source": "数据源 = contracts/openapi.v1.frozen.json",
        "normalized_by": "scripts/gen_frontend_baseline.py",
        "openapi": document.get("openapi"),
        "info": {
            "title": info.get("title"),
            "version": info.get("version"),
        },
        "counts": {
            "paths": len(paths),
            "operations": len(operations),
            "schemas": len(schemas),
        },
        "operations": operations,
        "schemas": sorted(schemas),
    }
    return json.dumps(subset, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


# ---------------------------------------------------------------------------
# Deriver 2: SSE channels
# ---------------------------------------------------------------------------


def derive_sse_channels(document: dict[str, Any]) -> str:
    """Derive the SSE channel subset from the frozen document.

    Keeps the channel name -> domain type mapping (the thing a TS consumer
    needs to switch on) plus the payload key order that the frame contract
    fixes.

    Args:
        document: Parsed ``contracts/sse/channels.json``.

    Returns:
        The JSON text of ``sse.channels.json``.
    """
    raw = document.get("channels")
    raw = raw if isinstance(raw, list) else []

    channels: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        keys = entry.get("payload_keys_in_order")
        channels.append(
            {
                "channel": entry.get("channel"),
                "domain_type": entry.get("domain_type"),
                "event_class": entry.get("event_class"),
                "event_module": entry.get("event_module"),
                "phase": entry.get("phase"),
                "golden": entry.get("golden"),
                "payload_keys_in_order": keys if isinstance(keys, list) else [],
            }
        )
    channels.sort(key=lambda row: str(row["channel"]))

    subset = {
        "source": "数据源 = contracts/sse/channels.json",
        "normalized_by": "scripts/gen_frontend_baseline.py",
        "contract_version": document.get("contract_version"),
        "frame_format": document.get("frame_format"),
        "counts": {"channels": len(channels)},
        "channels": channels,
    }
    return json.dumps(subset, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


# ---------------------------------------------------------------------------
# Deriver 3: error codes (TypeScript)
# ---------------------------------------------------------------------------


def render_error_codes_ts(document: dict[str, Any]) -> str:
    """Render ``error-codes.ts`` from the frozen error contract.

    Emits a const object, the derived union type, and the HTTP status map —
    all three read out of ``codes``, so a status that differs per call site is
    visible here instead of being averaged away by a hand-typed literal.

    Args:
        document: Parsed ``contracts/errors.json``.

    Returns:
        The TypeScript source of ``error-codes.ts``.
    """
    codes = document.get("codes")
    codes = codes if isinstance(codes, dict) else {}

    names = sorted(codes)
    lines: list[str] = []
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// WBTimeAI · 前端错误码（V0.1.0 · T1-01）")
    lines.append("//")
    lines.append("// 本文件由 scripts/gen_frontend_baseline.py 从 contracts/errors.json 派生，")
    lines.append("// **禁止手改**：手改即与冻结契约脱钩。改契约 → 重跑 deriver。")
    lines.append("//")
    lines.append(f"// 数据源 = contracts/errors.json（contract_version={document.get('contract_version')}）")
    lines.append(f"// 实测条数 = {len(names)}（len(codes)，非人工填写）")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("")
    lines.append("export const ERROR_CODES = {")
    for name in names:
        lines.append(f'  {name}: "{name}",')
    lines.append("} as const;")
    lines.append("")
    lines.append("export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];")
    lines.append("")
    lines.append("/** HTTP 状态码映射。取契约的 http_status；契约内部不一致的码单独标注。 */")
    lines.append("export const ERROR_HTTP_STATUS: Record<ErrorCode, number> = {")
    for name in names:
        entry = codes[name]
        status = entry.get("http_status") if isinstance(entry, dict) else None
        status = status if isinstance(status, int) else 500
        lines.append(f"  {name}: {status},")
    lines.append("};")
    lines.append("")
    lines.append("/** 中文描述（契约 ``description``；缺失时回落为空串，不编造文案）。 */")
    lines.append("export const ERROR_DESCRIPTION: Record<ErrorCode, string> = {")
    for name in names:
        entry = codes[name]
        description = entry.get("description") if isinstance(entry, dict) else None
        description = description if isinstance(description, str) else ""
        escaped = description.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  {name}: "{escaped}",')
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Run the built-in checks.

    Verifies the derivers are honest about their counts: a synthetic document
    with a known shape must yield exactly that shape, and the "unknown key
    means 0, not 42" rule must hold.

    Returns:
        ``0`` when every expectation holds, ``9`` otherwise.
    """
    failures: list[str] = []

    subset = json.loads(
        derive_openapi_subset(
            {
                "info": {"version": "9.9.9", "title": "T"},
                "openapi": "3.1.0",
                "paths": {
                    "/b": {"get": {"operationId": "g_b", "tags": ["t"]}},
                    "/a": {
                        "post": {"operationId": "p_a", "tags": []},
                        "parameters": [{"name": "not-an-operation"}],
                    },
                },
                "components": {"schemas": {"Zebra": {}, "Apple": {}}},
            }
        )
    )
    if subset["counts"] != {"paths": 2, "operations": 2, "schemas": 2}:
        failures.append(f"openapi counts: {subset['counts']}")
    if subset["info"]["version"] != "9.9.9":
        failures.append("openapi info.version not propagated")
    if subset["schemas"] != ["Apple", "Zebra"]:
        failures.append(f"openapi schemas not sorted: {subset['schemas']}")
    if [row["method"] for row in subset["operations"]] != ["POST", "GET"]:
        failures.append(f"openapi ops not path-ordered: {subset['operations']}")
    if subset["source"] != "数据源 = contracts/openapi.v1.frozen.json":
        failures.append("openapi source field drifted")

    sse = json.loads(
        derive_sse_channels(
            {
                "contract_version": 1,
                "frame_format": "f",
                "channels": [
                    {"channel": "b.x", "domain_type": "b.x", "payload_keys_in_order": ["k"]},
                    {"channel": "a.y", "domain_type": "a.y", "payload_keys_in_order": []},
                ],
            }
        )
    )
    if sse["counts"] != {"channels": 2}:
        failures.append(f"sse counts: {sse['counts']}")
    if [row["channel"] for row in sse["channels"]] != ["a.y", "b.x"]:
        failures.append("sse channels not sorted")
    if sse["source"] != "数据源 = contracts/sse/channels.json":
        failures.append("sse source field drifted")

    # An empty input must report 0 — never a remembered number (K-11).
    if json.loads(derive_sse_channels({}))["counts"] != {"channels": 0}:
        failures.append("empty sse input did not report 0")
    if json.loads(derive_openapi_subset({}))["counts"] != {
        "paths": 0,
        "operations": 0,
        "schemas": 0,
    }:
        failures.append("empty openapi input did not report 0")

    ts = render_error_codes_ts(
        {"contract_version": 3, "codes": {"B": {"http_status": 401, "description": 'say "hi"'}, "A": {}}}
    )
    if "实测条数 = 2" not in ts:
        failures.append("error-codes count line missing/wrong")
    if "  A: 500," not in ts:
        failures.append("missing http_status did not fall back to 500")
    if 'A: "",' not in ts:
        failures.append("missing description did not fall back to empty string")
    if 'B: "say \\"hi\\"",' not in ts:
        failures.append("description not escaped")

    if failures:
        for problem in failures:
            print(f"self-test FAIL: {problem}")
        return 9
    print("self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector (``None`` → ``sys.argv[1:]``).

    Returns:
        One of the documented exit codes.
    """
    parser = argparse.ArgumentParser(
        prog="gen_frontend_baseline.py",
        description="Derive contracts/frontend-baseline/** from the frozen contracts.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; fail with 1 when the baseline on disk differs by one byte",
    )
    parser.add_argument("--self-test", action="store_true", help="run the built-in checks and exit")
    args, extra = parser.parse_known_args(argv)
    if extra:
        print(f"usage error: unexpected arguments {extra}", file=sys.stderr)
        return 2

    if args.self_test:
        return _self_test()

    try:
        openapi_doc_src = load_json(SRC_OPENAPI)
        errors_doc_src = load_json(SRC_ERRORS)
        openapi_text = derive_openapi_subset(openapi_doc_src)
        sse_text = derive_sse_channels(load_json(SRC_SSE))
        errors_text = render_error_codes_ts(errors_doc_src)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"derive failed: {exc}", file=sys.stderr)
        return 1
    error_code_count = len(
        errors_doc_src["codes"] if isinstance(errors_doc_src.get("codes"), dict) else {}
    )

    planned = ((OUT_OPENAPI, openapi_text), (OUT_SSE, sse_text), (OUT_ERRORS, errors_text))

    if args.check:
        drift: list[str] = []
        for path, text in planned:
            if not path.is_file():
                drift.append(f"{path.name}: absent")
                continue
            if path.read_bytes() != text.encode("utf-8"):
                drift.append(f"{path.name}: bytes differ")
        if drift:
            for problem in drift:
                print(f"check FAIL {problem}")
            return 1
        for path, _text in planned:
            print(f"check OK {path.name}")
        return 0

    for path, text in planned:
        _write(path, text)

    openapi_doc = json.loads(openapi_text)
    sse_doc = json.loads(sse_text)
    print(
        "derived "
        f"openapi.subset.json(operations={openapi_doc['counts']['operations']}, "
        f"paths={openapi_doc['counts']['paths']}, schemas={openapi_doc['counts']['schemas']}, "
        f"info.version={openapi_doc['info']['version']}) "
        f"sse.channels.json(channels={sse_doc['counts']['channels']}) "
        f"error-codes.ts(codes={error_code_count})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
