"""T04 — the counterexample registry (pure data + one mutator per case).

Why a registry instead of "5 cases hard-coded in the engine"
-----------------------------------------------------------
A injection case is three separate things: *what* is tampered with, *which gate*
must notice, and *what the red must say*.  Keeping them as data means a reviewer
can read the whole expectation matrix without reading the engine, and the engine
can be audited for "does it really insist on :attr:`InjectionCase.must_be_red`"
independently of "which cases exist".

Hard rules encoded here (design ``02-施工/README.md`` §5-T04 + §11.1)
---------------------------------------------------------------------
1. **Every mutator re-pins the whole ledger chain** (``manifest.sha256`` and
   ``contract-manifest.json#objects[].sha256``).  Without that, the case would
   merely re-prove ``run.py check`` — which is the trivial half of the story.
2. **Mutators never touch the real tree.**  They receive paths *inside a
   temporary clone* (``<scratch>/repo/contracts`` and ``<scratch>/repo``) and are
   called by :mod:`inject_counterexample` only.
3. **A "self-consistent" tamper must also sync the toolkit's code constants**
   (§11.1).  ``scripts/extract-from-py/contract_manifest.py`` hard-codes
   ``245`` / ``2 hnsw`` / ``migration_count == 10``, so deleting one hnsw *and*
   its counts while leaving those literals alone makes ``run.py check`` red for
   the wrong reason.  :func:`ddl_hnsw_deleted_consistent` therefore also rewrites
   the cloned toolkit's constants — that is exactly the attacker a semantic gate
   must survive.

Every mutator raises :class:`MutationError` when its anchor text is not found
exactly once.  Guessing would turn "the mutator silently did nothing" into a
green injection — the failure mode this whole version exists to kill.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final

__all__ = [
    "MutationError",
    "InjectionCase",
    "CASES",
    "CASE_BY_ID",
    "case_ids",
    "get_case",
    "victims",
    "PG_NORMALIZED",
    "PG_SQL",
    "SQLITE_NORMALIZED",
    "SQLITE_SQL",
    "CONTRACT_MANIFEST",
    "OPENAPI_FROZEN",
    "SSE_CHANNELS",
    "VICTIM_HNSW",
    "VICTIM_OPENAPI_PATH",
    "VICTIM_SSE_CHANNEL",
    "TOOLKIT_CONTRACT_MANIFEST",
    "TOOLKIT_DDL_PARITY",
]

#: Artifact paths relative to ``contracts/``.
PG_NORMALIZED: Final[str] = "schema.v0018.pg.normalized.json"
SQLITE_NORMALIZED: Final[str] = "schema.v0018.sqlite.normalized.json"
PG_SQL: Final[str] = "schema.v0018.pg.sql"
SQLITE_SQL: Final[str] = "schema.v0018.sqlite.sql"
CONTRACT_MANIFEST: Final[str] = "contract-manifest.json"
OPENAPI_FROZEN: Final[str] = "openapi.v1.frozen.json"
SSE_CHANNELS: Final[str] = "sse/channels.json"

#: Toolkit scripts compiled into the clone (paths relative to the repo root).
TOOLKIT_CONTRACT_MANIFEST: Final[str] = "scripts/extract-from-py/contract_manifest.py"
TOOLKIT_DDL_PARITY: Final[str] = "scripts/check_ddl_parity.py"

#: The victims.  Pinned by name (not "the first one") so a re-run attacks the
#: same object and the ledger can quote it verbatim.
VICTIM_HNSW: Final[str] = "ix_memory_vector_hnsw"
VICTIM_OPENAPI_PATH: Final[str] = "/api/v1/agents/{agent_id}/publish"
VICTIM_SSE_CHANNEL: Final[str] = "agent.thinking"

#: Gate keys understood by :mod:`inject_counterexample`.  Declared here so the
#: registry fails loudly on a typo instead of silently skipping a case.
GATE_KEYS: Final[tuple[str, ...]] = (
    "check_ddl_parity",
    "verify_semantics",
    "compare_openapi_legacy",
    "oracle_recompute",
    "run_check",
)


class MutationError(RuntimeError):
    """Raised when a mutator cannot apply its tamper exactly as declared.

    The engine maps this to ``EXIT_CASE_UNEVALUABLE`` (``12``): a tamper that did
    not happen must never be reported as "the gate stayed green".
    """


@dataclass(frozen=True)
class InjectionCase:
    """One named tamper and the red it must provoke.

    Attributes:
        case_id: Stable identifier used by ``--case`` and in the ledger.
        dod: Which DoD (or design clause) this case is evidence for.
        target_gate: Gate key (see :data:`GATE_KEYS`) that must go red.
        expected_reason: One-line prose description of the *expected* red reason.
        description: What the mutator does, in the reader's words.
        must_be_red: Tokens that must all appear in the target gate's output
            (diff kinds, criterion ids, object names ...).  Empty is illegal at
            run time — the engine refuses to judge such a case (``INVALID``/``12``).
        mutator: ``(contracts_clone, repo_clone) -> description of what changed``.
        must_stay_green: Gate keys that must *stay* green on the same tampered
            clone (the "correct gate" argument).  An integrity failure here is
            reported as ``12`` — the case's premise did not hold.
        checks_integrity: When true the engine also runs ``run.py check`` on the
            clone and requires exit ``0`` (design §5-T04 要点 ②).
    """

    case_id: str
    dod: str
    target_gate: str
    expected_reason: str
    description: str
    must_be_red: tuple[str, ...]
    mutator: Callable[[Path, Path], str]
    must_stay_green: tuple[str, ...] = ()
    checks_integrity: bool = True


# ---------------------------------------------------------------------------
# Small artifact helpers (deliberately local: the registry must not depend on a
# gate, otherwise "the case" and "the judgement" would share one implementation)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    """Load a JSON object, raising :class:`MutationError` on any problem.

    Args:
        path: File to read (UTF-8).

    Returns:
        The decoded object (must be a mapping).
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise MutationError(f"cannot read {path.as_posix()}: {error}") from error
    except json.JSONDecodeError as error:
        raise MutationError(f"invalid JSON in {path.as_posix()}: {error}") from error
    if not isinstance(document, dict):
        raise MutationError(f"{path.as_posix()}: top level is not an object")
    return document


def _write_json(path: Path, document: dict) -> None:
    """Write a JSON object the way the toolkit writes ledgers.

    Args:
        path: Destination file.
        document: Payload to serialise (indent 2, UTF-8, trailing newline).
    """
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_text(path: Path) -> str:
    """Read a UTF-8 text artifact, raising :class:`MutationError` when absent.

    Args:
        path: File to read.

    Returns:
        The file content.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise MutationError(f"cannot read {path.as_posix()}: {error}") from error


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with a trailing newline.

    Args:
        path: Destination file.
        text: New content.
    """
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    """Replace ``old`` with ``new`` exactly once inside ``path``.

    Args:
        path: File to rewrite.
        old: Anchor text (must occur exactly once).
        new: Replacement text.
        label: Human description used in the error message.

    Raises:
        MutationError: The anchor occurs zero or more than one time.
    """
    text = _read_text(path)
    occurrences = text.count(old)
    if occurrences != 1:
        raise MutationError(
            f"{label}: anchor occurs {occurrences} time(s) in {path.as_posix()}, expected 1"
        )
    _write_text(path, text.replace(old, new, 1))


def _replace_regex_once(path: Path, pattern: str, new: str, *, label: str) -> None:
    """Replace the single regex match in ``path`` with ``new``.

    Args:
        path: File to rewrite.
        pattern: Regular expression that must match exactly once.
        new: Replacement text (literal, ``backslash`` is not interpreted).
        label: Human description used in the error message.

    Raises:
        MutationError: The pattern matches zero or more than one time.
    """
    text = _read_text(path)
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise MutationError(
            f"{label}: pattern matched {len(matches)} time(s) in {path.as_posix()}, expected 1"
        )
    start, end = matches[0].span()
    _write_text(path, text[:start] + new + text[end:])


def _manifest_paths(contracts: Path) -> Path:
    """Return ``<contracts>/contract-manifest.json``.

    Args:
        contracts: Contracts directory (inside the clone).

    Returns:
        Path to the object ledger.
    """
    return contracts / CONTRACT_MANIFEST


def _criterion(document: dict, criterion_id: str) -> dict:
    """Return one ``criteria[]`` record, raising when it is absent.

    Args:
        document: Parsed ``contract-manifest.json``.
        criterion_id: Identifier such as ``C7``.

    Returns:
        The mutable record.
    """
    for item in document.get("criteria") or []:
        if str(item.get("id")) == criterion_id:
            return item
    raise MutationError(f"contract-manifest.json: criteria[{criterion_id}] not found")


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------


def ddl_column_narrowed(contracts: Path, repo: Path) -> str:
    """Narrow one ``VARCHAR(255)`` column to ``VARCHAR(64)`` in PG normalized only.

    DoD#1.  The ``.sql`` text keeps the original width, so the *only* witness is
    the cross-source parity comparison: a sha256 ledger (re-pinned here) cannot
    see it, and ``verify_semantics`` only counts columns.

    Args:
        contracts: Contracts directory inside the clone.
        repo: Repository root inside the clone (unused).

    Returns:
        Description of the tamper.
    """
    del repo
    target = contracts / PG_NORMALIZED
    document = _read_json(target)
    for table in document.get("tables") or []:
        for column in table.get("columns") or []:
            if str(column.get("type") or "").upper() == "VARCHAR(255)":
                column["type"] = "VARCHAR(64)"
                _write_json(target, document)
                return (
                    f"{table['name']}.{column['name']}: VARCHAR(255) -> VARCHAR(64) "
                    "in pg.normalized only (pg.sql untouched)"
                )
    raise MutationError(f"{PG_NORMALIZED}: no VARCHAR(255) column found to narrow")


def ddl_hnsw_deleted_naive(contracts: Path, repo: Path) -> str:
    """Delete ``counts.raw_indexes`` 2 -> 1 and nothing else.

    DoD#2, weak half.  The structure still carries two ``raw_indexes`` entries and
    ``index_objects_total`` still says 176, so this is the cheapest forgery — the
    one ``verify_semantics`` (C7) recomputes from the structure and catches.

    Args:
        contracts: Contracts directory inside the clone.
        repo: Repository root inside the clone (unused).

    Returns:
        Description of the tamper.
    """
    del repo
    target = contracts / PG_NORMALIZED
    document = _read_json(target)
    counts = document.get("counts") or {}
    if counts.get("raw_indexes") != 2:
        raise MutationError(f"{PG_NORMALIZED}: counts.raw_indexes is {counts.get('raw_indexes')!r}, expected 2")
    counts["raw_indexes"] = 1
    document["counts"] = counts
    _write_json(target, document)
    return (
        "counts.raw_indexes 2 -> 1 in pg.normalized only "
        "(raw_indexes[] still has 2 entries, index_objects_total still 176)"
    )


def ddl_hnsw_deleted_consistent(contracts: Path, repo: Path) -> str:
    """Delete one hnsw index and make **the whole chain** agree with the loss.

    DoD#2, strong half (design §1.3 ATK-2).  Six places must move together or the
    internal gates stay red for the wrong reason:

    1. ``pg.normalized#raw_indexes[]`` — the object itself;
    2. ``pg.normalized#counts`` — ``raw_indexes`` / ``index_objects_total`` /
       ``dialect_only_objects`` / ``dialect_only_by_kind.index`` (§11.4: three of
       these were missing from the original ATK-2 list);
    3. ``pg.sql`` — the ``CREATE INDEX`` line, its ``-- source:`` comment, and the
       three header lines that state "2 hnsw" / "174 + 2 = 176";
    4. ``contract-manifest.json#ddl_objects[]`` — the object record;
    5. ``contract-manifest.json#schema.ddl_object_count`` + ``criteria[]``
       ``C7`` / ``C8`` / ``C21`` ``expected`` **and** ``measured``;
    6. the cloned **toolkit's code constants** (§11.1): ``DDL_OBJECT_EXPECTED``,
       ``DDL_DIALECT_EXPECTED``, the ``migration_count != 10`` literal in
       ``contract_manifest.verify``, the ``C7``/``C8`` probe expectations, and
       ``check_ddl_parity.EXPECTED_HNSW_PG``.

    After all six, ``run.py check`` / ``verify_semantics`` / ``check_ddl_parity``
    are green on the clone while ``oracle_recompute`` must still see two hnsw
    indexes in ``_old/migrations/versions/0014_phase2_memory.py``.

    Args:
        contracts: Contracts directory inside the clone.
        repo: Repository root inside the clone (toolkit constants live here).

    Returns:
        Description of the tamper (one line per moved place).
    """
    steps: list[str] = []

    # 1 + 2 — the object and its counts.
    normalized = contracts / PG_NORMALIZED
    document = _read_json(normalized)
    raw_indexes = document.get("raw_indexes") or []
    survivors = [item for item in raw_indexes if str(item.get("name")) != VICTIM_HNSW]
    if len(survivors) != len(raw_indexes) - 1:
        raise MutationError(
            f"{PG_NORMALIZED}: expected exactly one raw index named {VICTIM_HNSW}, "
            f"found {len(raw_indexes) - len(survivors)}"
        )
    document["raw_indexes"] = survivors
    counts = document.get("counts") or {}
    counts["raw_indexes"] = int(counts.get("raw_indexes", 2)) - 1
    counts["index_objects_total"] = int(counts.get("index_objects_total", 176)) - 1
    counts["dialect_only_objects"] = int(counts.get("dialect_only_objects", 2)) - 1
    by_kind = dict(counts.get("dialect_only_by_kind") or {})
    if "index" in by_kind:
        by_kind["index"] = int(by_kind["index"]) - 1
    counts["dialect_only_by_kind"] = by_kind
    document["counts"] = counts
    _write_json(normalized, document)
    steps.append(
        f"pg.normalized: raw_indexes 2->1, index_objects_total 176->175, "
        f"dialect_only_objects 2->1, dialect_only_by_kind.index 2->1 (dropped {VICTIM_HNSW})"
    )

    # 3 — the frozen SQL text (statement, its provenance comment, header counts).
    sql_path = contracts / PG_SQL
    sql_text = _read_text(sql_path)
    statement = (
        "-- source: migration:migrations/versions/0014_phase2_memory.py:195\n"
        f"CREATE INDEX {VICTIM_HNSW} ON memory USING hnsw (vector vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);\n"
    )
    if sql_text.count(statement) != 1:
        raise MutationError(
            f"{PG_SQL}: the hnsw statement block occurs {sql_text.count(statement)} time(s), expected 1"
        )
    sql_text = sql_text.replace(statement, "", 1)
    header_pairs = (
        (
            "--   源② 迁移链 raw DDL：2 个 hnsw 向量索引"
            "（ix_embedding_vector_hnsw / ix_memory_vector_hnsw，metadata 里 0 处）",
            "--   源② 迁移链 raw DDL：1 个 hnsw 向量索引"
            "（ix_embedding_vector_hnsw，metadata 里 0 处）",
        ),
        ("--   合并后索引对象总数：174 + 2 = 176", "--   合并后索引对象总数：174 + 1 = 175"),
        (
            "-- ===== 4. 迁移 raw DDL 索引（源②，2 个；ORM 无法表达）=====",
            "-- ===== 4. 迁移 raw DDL 索引（源②，1 个；ORM 无法表达）=====",
        ),
    )
    for old, new in header_pairs:
        if sql_text.count(old) != 1:
            raise MutationError(
                f"{PG_SQL}: header anchor occurs {sql_text.count(old)} time(s), expected 1: {old!r}"
            )
        sql_text = sql_text.replace(old, new, 1)
    _write_text(sql_path, sql_text)
    steps.append("pg.sql: CREATE INDEX block removed + 3 header count lines rewritten (2 -> 1, 176 -> 175)")

    # 4 + 5 — the object ledger and its criteria.
    manifest_path = _manifest_paths(contracts)
    manifest = _read_json(manifest_path)
    entries = manifest.get("ddl_objects") or []
    kept = [item for item in entries if str(item.get("name")) != VICTIM_HNSW]
    if len(kept) != len(entries) - 1:
        raise MutationError(
            f"{CONTRACT_MANIFEST}: expected exactly one ddl_objects entry named {VICTIM_HNSW}"
        )
    manifest["ddl_objects"] = kept
    schema_block = manifest.get("schema") or {}
    schema_block["ddl_object_count"] = len(kept)
    manifest["schema"] = schema_block
    steps.append(
        f"contract-manifest.json: ddl_objects {len(entries)}->{len(kept)}, "
        f"schema.ddl_object_count -> {len(kept)}"
    )

    for criterion_id, expected_key, delta in (
        ("C7", "ddl.raw_hnsw_indexes", -1),
        ("C8", "ddl.index_objects_total", -1),
        ("C21", "ddl_objects.total", -1),
    ):
        record = _criterion(manifest, criterion_id)
        record["measured"] = int(record.get("measured")) + delta
        record["expected"] = int(record.get("expected")) + delta
        note = str(record.get("note") or "")
        record["note"] = (
            (note + " | " if note else "")
            + "T04 injection ddl-hnsw-deleted-consistent: chain re-derived after dropping "
            + VICTIM_HNSW
        )
        if str(record.get("metric")) != expected_key:
            raise MutationError(
                f"contract-manifest.json: criteria[{criterion_id}].metric is "
                f"{record.get('metric')!r}, expected {expected_key!r} (registry drift)"
            )
    _write_json(manifest_path, manifest)
    steps.append("contract-manifest.json: criteria C7/C8/C21 expected+measured decremented, notes annotated")

    # 6 — the toolkit's code constants (§11.1).  Without this the ledger re-pin
    #     alone leaves `run.py check` red for a *mechanical* reason and the
    #     "check stayed green" assertion becomes a lie.
    contract_manifest_py = repo / TOOLKIT_CONTRACT_MANIFEST
    _replace_once(
        contract_manifest_py,
        '    "index.raw_hnsw": 2,',
        '    "index.raw_hnsw": 1,',
        label="toolkit DDL_OBJECT_EXPECTED.index.raw_hnsw",
    )
    _replace_once(
        contract_manifest_py,
        'DDL_DIALECT_EXPECTED: dict[str, int] = {"pg": 2, "sqlite": 8, "null": 235}',
        'DDL_DIALECT_EXPECTED: dict[str, int] = {"pg": 1, "sqlite": 8, "null": 235}',
        label="toolkit DDL_DIALECT_EXPECTED.pg",
    )
    _replace_once(
        contract_manifest_py,
        "    if ddl_objects and migration_count != 10:",
        "    if ddl_objects and migration_count != 9:",
        label="toolkit verify() migration_count literal",
    )
    _replace_once(
        contract_manifest_py,
        '_criterion("C7", "DoD#3", "ddl.raw_hnsw_indexes", 2, pg_counts.get("raw_indexes"),',
        '_criterion("C7", "DoD#3", "ddl.raw_hnsw_indexes", 1, pg_counts.get("raw_indexes"),',
        label="toolkit C7 probe expectation",
    )
    _replace_once(
        contract_manifest_py,
        '_criterion("C8", "DoD#3", "ddl.index_objects_total", 176, pg_counts.get("index_objects_total"),',
        '_criterion("C8", "DoD#3", "ddl.index_objects_total", 175, pg_counts.get("index_objects_total"),',
        label="toolkit C8 probe expectation",
    )
    steps.append(
        "toolkit contract_manifest.py: DDL_OBJECT_EXPECTED.index.raw_hnsw 2->1, "
        "DDL_DIALECT_EXPECTED.pg 2->1, migration_count 10->9, C7/C8 probe expectations 2->1 / 176->175"
    )
    _replace_regex_once(
        repo / TOOLKIT_DDL_PARITY,
        r"EXPECTED_HNSW_PG = 2",
        "EXPECTED_HNSW_PG = 1",
        label="toolkit check_ddl_parity.EXPECTED_HNSW_PG",
    )
    steps.append("toolkit check_ddl_parity.py: EXPECTED_HNSW_PG 2->1 (the guard is a code constant)")

    return " | ".join(steps)


def openapi_path_deleted(contracts: Path, repo: Path) -> str:
    """Delete one path object from the frozen OpenAPI document.

    DoD#3.  Comparing the frozen file against *itself* (`--candidate file`) can
    never see this, which is why the target gate is run with
    ``--candidate legacy`` (static ``ast`` scan of the read-only legacy routers).

    Args:
        contracts: Contracts directory inside the clone.
        repo: Repository root inside the clone (unused).

    Returns:
        Description of the tamper.
    """
    del repo
    target = contracts / OPENAPI_FROZEN
    document = _read_json(target)
    paths = document.get("paths") or {}
    if VICTIM_OPENAPI_PATH not in paths:
        raise MutationError(f"{OPENAPI_FROZEN}: path {VICTIM_OPENAPI_PATH!r} not found")
    removed = paths.pop(VICTIM_OPENAPI_PATH)
    document["paths"] = paths
    _write_json(target, document)
    return (
        f"openapi.v1.frozen.json: deleted path {VICTIM_OPENAPI_PATH} "
        f"({len(removed)} operation(s)); paths 100 -> {len(paths)}"
    )


def sse_channel_dropped(contracts: Path, repo: Path) -> str:
    """Drop one SSE channel from ``sse/channels.json`` (row **and** mapping key).

    Both sides of the registry move together, so this is a *consistent* loss: the
    only thing that still remembers 19 channels is the ledger's own expectation —
    which is exactly what ``verify_semantics`` C10/C11 recompute from the artifact.

    The golden frame file stays on disk on purpose: the case must be red because
    the channel disappeared, not because a file went missing (C12 stays green).

    Args:
        contracts: Contracts directory inside the clone.
        repo: Repository root inside the clone (unused).

    Returns:
        Description of the tamper.
    """
    del repo
    target = contracts / SSE_CHANNELS
    document = _read_json(target)
    channels = document.get("channels") or []
    kept = [item for item in channels if str(item.get("channel")) != VICTIM_SSE_CHANNEL]
    if len(kept) != len(channels) - 1:
        raise MutationError(f"{SSE_CHANNELS}: expected exactly one channel {VICTIM_SSE_CHANNEL!r}")
    document["channels"] = kept
    by_channel = document.get("by_channel") or {}
    by_channel.pop(VICTIM_SSE_CHANNEL, None)
    document["by_channel"] = by_channel
    _write_json(target, document)
    return (
        f"sse/channels.json: dropped channel {VICTIM_SSE_CHANNEL} "
        f"(channels 19 -> {len(kept)}, by_channel 19 -> {len(by_channel)}); golden file kept"
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

CASES: Final[tuple[InjectionCase, ...]] = (
    InjectionCase(
        case_id="ddl-column-narrowed",
        dod="DoD#1",
        target_gate="check_ddl_parity",
        expected_reason="red on a column-type diff naming the narrowed (table, column)",
        description=(
            "Narrow one VARCHAR(255) column to VARCHAR(64) in pg.normalized only, "
            "then re-pin both ledgers. pg.sql still says VARCHAR(255)."
        ),
        must_be_red=("column-type", "pg.normalized", "VARCHAR(64)"),
        mutator=ddl_column_narrowed,
    ),
    InjectionCase(
        case_id="ddl-hnsw-deleted-consistent",
        dod="DoD#2 (strong / N-2 closure)",
        target_gate="oracle_recompute",
        expected_reason=(
            "F2 ddl.raw_indexes MISMATCH naming ix_memory_vector_hnsw, while check / "
            "verify_semantics / parity stay green on the same clone"
        ),
        description=(
            "Delete one hnsw index and re-derive the whole chain: normalized object + "
            "4 counts + pg.sql statement/header + ddl_objects + ddl_object_count + "
            "criteria C7/C8/C21 + the toolkit's code constants (§11.1)."
        ),
        must_be_red=("ddl.raw_indexes", "ix_memory_vector_hnsw", "MISMATCH (20)"),
        mutator=ddl_hnsw_deleted_consistent,
        must_stay_green=("check_ddl_parity", "verify_semantics"),
    ),
    InjectionCase(
        case_id="ddl-hnsw-deleted-naive",
        dod="DoD#2 (weak half / 'use the right gate')",
        target_gate="verify_semantics",
        expected_reason="C7 red: counts.raw_indexes says 1 while the structure still has 2 (C8 also trips: 174+1 != 176)",
        description=(
            "Change counts.raw_indexes 2 -> 1 only (structure and index_objects_total "
            "untouched), then re-pin both ledgers. Same tamper, weaker gate still sees it."
        ),
        must_be_red=("C7", "counts.raw_indexes"),
        mutator=ddl_hnsw_deleted_naive,
    ),
    InjectionCase(
        case_id="openapi-path-deleted",
        dod="DoD#3",
        target_gate="compare_openapi_legacy",
        expected_reason="red on the deleted path as a member of the paths collection",
        description=(
            "Delete one path object from the frozen OpenAPI document and re-pin the "
            "ledgers; compare against the static legacy router scan."
        ),
        must_be_red=("paths", VICTIM_OPENAPI_PATH),
        mutator=openapi_path_deleted,
    ),
    InjectionCase(
        case_id="sse-channel-dropped",
        dod="DoD#4 (contract side)",
        target_gate="verify_semantics",
        expected_reason="C10 and C11 red: 18 channels recomputed against a ledger that still says 19",
        description=(
            "Drop one SSE channel from both channels[] and by_channel, keep its golden "
            "file, re-pin the ledgers."
        ),
        must_be_red=("C10", "C11"),
        mutator=sse_channel_dropped,
    ),
)


#: Registry lookup by id.
CASE_BY_ID: Final[dict[str, InjectionCase]] = {case.case_id: case for case in CASES}


def case_ids() -> tuple[str, ...]:
    """Return the registered case ids in declaration order.

    Returns:
        A tuple of case ids.
    """
    return tuple(case.case_id for case in CASES)


def get_case(case_id: str) -> InjectionCase:
    """Return one case by id.

    Args:
        case_id: Identifier as printed by ``--list``.

    Returns:
        The registered case.

    Raises:
        KeyError: No such case.
    """
    return CASE_BY_ID[case_id]


def victims() -> dict[str, str]:
    """Return the pinned victim names (for the ledger and ``--list``).

    Returns:
        Mapping ``{"hnsw": ..., "openapi_path": ..., "sse_channel": ...}``.
    """
    return {
        "hnsw": VICTIM_HNSW,
        "openapi_path": VICTIM_OPENAPI_PATH,
        "sse_channel": VICTIM_SSE_CHANNEL,
    }
