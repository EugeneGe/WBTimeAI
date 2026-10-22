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
    "GATE_KEYS",
    "V031_CARRIER",
    "VICTIM_V031_EXEMPTION",
    "VICTIM_V031_STREAM",
    "VICTIM_V031_DEPTH",
    "V031_WATERMARK_CARRIER",
    "VICTIM_V031_WATERMARK",
    "MARKER_IMPL_NOT_LANDED",
    "MARKER_DIST_STALE",
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

# --- V0.3.1 · G031-4 spike（V031 用例集）-------------------------------------
#
# 与前 5 条**性质不同**：那 5 条改的是 `contracts/` 里的冻结件，本 3 条改的是
# `apps/api/src/**` 的**生产实现**。故：
#   * 目标门是 `v031_spike`（`node --test` 跑 `apps/api/tests/subagent-spike.test.mjs`），
#     不是任何 Python 契约门；
#   * 判据载体由 QA 落盘（P1-3：执行者 ≠ 判定者），本文件只负责"把它改坏"；
#   * 生产实现**尚未落地** ⇒ 三个改坏点都不存在 ⇒ 三条一律 MutationError ⇒
#     `UNEVALUABLE` / exit **12**，并带 `V031_IMPL_NOT_LANDED` 标记。**12 不是绿**，
#     与"注入了但门没红"（`FAKE-GREEN` / 10）严格区分。

#: spike 判据载体（相对仓库根）。由 QA 落盘，实现者不得自建自评。
V031_CARRIER: Final[str] = "apps/api/tests/subagent-spike.test.mjs"

#: 三个改坏点（钉在名字上，不写"第一个匹配的"）。
VICTIM_V031_EXEMPTION: Final[str] = "guardRunCreation 的 origin 豁免判据"
VICTIM_V031_STREAM: Final[str] = "streamRunFrames 的 run_id 归属过滤"
VICTIM_V031_DEPTH: Final[str] = "子 run 深度守卫"

#: 两个"不可判"标记。带它们的 exit 12 必须与"用例写坏了"的 exit 12 可区分。
MARKER_IMPL_NOT_LANDED: Final[str] = "V031_IMPL_NOT_LANDED"
MARKER_DIST_STALE: Final[str] = "V031_DIST_STALE"

#: D6 游标缺口判据载体（相对仓库根）。与 spike 载体并列、同属 K5b 的**第二种**
#: 静默崩溃路径（水位归属 / 游标来源）—— spike 的 S-2 只验帧内容归属，不验游标来源。
#: 由 QA 落盘，实现者不得自建自评。
V031_WATERMARK_CARRIER: Final[str] = "apps/api/tests/sse-watermark.test.mjs"

#: 第四个改坏点：无 `seq` 兜底分支被保留为**连接本地自增**（不按 run 隔离）。
VICTIM_V031_WATERMARK: Final[str] = "无 seq 兜底分支（连接本地自增冒充 id:）"

#: Gate keys understood by :mod:`inject_counterexample`.  Declared here so the
#: registry fails loudly on a typo instead of silently skipping a case.
GATE_KEYS: Final[tuple[str, ...]] = (
    "check_ddl_parity",
    "verify_semantics",
    "compare_openapi_legacy",
    "oracle_recompute",
    "run_check",
    "v031_spike",
    "v031_watermark",
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
# V031 · G031-4 spike 的三个改坏点
#
# 为什么必须**同时**改 `src` 与 `dist`
# -----------------------------------
#   spike 测试 `import "../dist/..."`（与仓内所有 api 测试一致），而 `dist/` 是
#   `tsc -b` 的产物、被 gitignore。在克隆里跑 `tsc -b` 会顺着 `apps/api/tsconfig.json`
#   的 `references` 把 `packages/*/dist` 重新编译进**真树** —— 那是污染他人工作区，
#   本脚本禁止。故改坏点**双写**：`src` 是契约件（记录"改的是什么语义"），`dist`
#   是测试真正 import 的件（让改坏生效）。
#
#   由此派生一条强约束：**两处必须命中同一锚点，且命中次数相等**（≥1，全部替换）。
#   `src` 命中而 `dist` 不命中 ⇒ `dist` 落后于 `src` ⇒ 报 `V031_DIST_STALE`
#   （exit 12，不是假绿）—— 先 `pnpm -C apps/api build` 再跑注入。
#
#   计数必须**只数代码、不数注释**（§4.5 实测）：`sse-stream.ts` 的归属过滤说明把
#   `agent_event.run_id === runId` 写进了文档注释，编译后注释剥掉 ⇒ src=2、dist=1，
#   若按原文计数会误报 `V031_DIST_STALE`（dist 比 src 还新）。故先算注释区间，
#   只把**完全落在代码区**的命中算数；替换也只落在这些命中上，注释原样保留。
# ---------------------------------------------------------------------------


def _comment_spans(text: str) -> "list[tuple[int, int]]":
    """返回 JS/TS 注释的字符区间（半开）列表，**字符串字面量与模板串保护**。

    为什么不用 `re.sub(r"/\\*.*?\\*/", "", text)`：那会把注释体连换行一起删掉，
    也会误伤字符串里的 `//`（如 `"https://…"`）。这里走一个字符级扫描器，
    记录区间而不是改写文本 —— 调用方据此过滤正则命中、并保留原文本做替换。
    """
    spans: "list[tuple[int, int]]" = []
    i = 0
    n = len(text)
    state = "code"  # code | squote | dquote | template | line | block
    start = 0
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line"
                start = i
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                start = i
                i += 2
                continue
            if ch == "'":
                state = "squote"
            elif ch == '"':
                state = "dquote"
            elif ch == "`":
                state = "template"
            i += 1
            continue
        if state in ("squote", "dquote", "template"):
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if (state == "squote" and ch == "'") or (state == "dquote" and ch == '"') or (state == "template" and ch == "`"):
                state = "code"
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                spans.append((start, i))
                state = "code"
            i += 1
            continue
        # block
        if ch == "*" and nxt == "/":
            spans.append((start, i + 2))
            state = "code"
            i += 2
            continue
        i += 1
    if state == "line":  # 文件以行注释结尾
        spans.append((start, n))
    return spans


def _code_matches(text: str, pattern: str) -> "list[re.Match[str]]":
    """正则命中，**剔除落在注释里的** —— 注释是给人看的，不是实现。"""
    spans = _comment_spans(text)
    hits: "list[re.Match[str]]" = []
    for match in re.finditer(pattern, text):
        begin, end = match.span()
        if any(begin < cend and cbegin < end for cbegin, cend in spans):
            continue
        hits.append(match)
    return hits


def _replace_code_matches(path: Path, hits: "list[re.Match[str]]", replacement: object) -> None:
    """按命中区间**从后往前**替换（保持前面的偏移量有效）；注释原样保留。"""
    text = path.read_text(encoding="utf-8-sig")
    for match in reversed(hits):
        new = replacement(match) if callable(replacement) else str(replacement)
        begin, end = match.span()
        text = text[:begin] + new + text[end:]
    path.write_text(text, encoding="utf-8")


def _v031_patch(
    repo: Path,
    src_candidates: tuple[str, ...],
    alternatives: tuple[tuple[str, object], ...],
    *,
    label: str,
) -> str:
    """在克隆里把一段实现改坏（`src` 与 `dist` 双写，同锚点、命中次数相等）。

    Args:
        repo: 克隆仓库根。
        src_candidates: `src` 侧候选文件（相对仓库根）。**取第一个含锚点的**，
            不是第一个存在的 —— §4.4 实测：豁免判据落在 `coordinator.ts`，而
            `run-service.ts` 存在但不含锚点，按"第一个存在的"会把已落地的实现
            误报成 `V031_IMPL_NOT_LANDED`。
        alternatives: `(pattern, replacement)` 候选，按顺序取第一个"两侧命中次数相等且 ≥1"的。
            `replacement` 可以是字符串，也可以是 `re.Match -> str` 回调。
        label: 人类描述（写进证据行）。

    Returns:
        一行"改了什么"。

    Raises:
        MutationError: 实现未落地 / dist 落后 / 两侧命中次数不等。
    """
    last_miss = ""
    for src_name in src_candidates:
        src = repo / Path(*src_name.split("/"))
        if not src.is_file():
            last_miss = f"{src_name} 不存在"
            continue
        dist_name = src_name.replace("apps/api/src/", "apps/api/dist/").removesuffix(".ts") + ".js"
        dist = repo / Path(*dist_name.split("/"))
        if not dist.is_file():
            last_miss = f"{dist_name} 不存在 —— 请先 `pnpm -C apps/api build` 再跑注入"
            continue

        src_text = src.read_text(encoding="utf-8-sig")
        dist_text = dist.read_text(encoding="utf-8-sig")

        for pattern, replacement in alternatives:
            src_hits = _code_matches(src_text, pattern)
            dist_hits = _code_matches(dist_text, pattern)
            if not src_hits:
                last_miss = f"{src_name}: src（剔除注释后）未命中 {pattern!r}"
                continue
            if not dist_hits:
                last_miss = f"{src_name}: dist 未命中同一锚点 {pattern!r}（dist 落后于 src？）"
                continue

            # 为什么是"全部替换 + 两侧次数相等"，而不是前 5 条用例的"恰好一次"
            # ------------------------------------------------------------
            #   契约件里的对象可以钉死到唯一一个（`ix_memory_vector_hnsw` 只有一个），
            #   实现里的判据**不能**：例如 `run_id` 归属过滤在 `streamRunFrames` 里
            #   天然出现两处（主轮询 + 终态前的尾读），写"恰好一次"会让用例在实现
            #   落地后**永远** UNEVALUABLE —— 那是把判据写成了不可判。
            #   故改为：两侧命中次数**必须相等**（不等 ⇒ dist 落后于 src），且 ≥ 1，
            #   然后**全部**替换（只改一处等于"过滤了一半"，反而是个含糊的注入）。
            #   计数只数**代码命中**（注释剔除，见 §4.5）。
            if len(src_hits) != len(dist_hits):
                raise MutationError(
                    f"{MARKER_DIST_STALE}: {label} —— 锚点 {pattern!r} 命中 src={len(src_hits)} 次、"
                    f"dist={len(dist_hits)} 次（均只数代码），两侧不等 ⇒ dist 落后于 src，"
                    "请先 `pnpm -C apps/api build`"
                )

            _replace_code_matches(src, src_hits, replacement)
            _replace_code_matches(dist, dist_hits, replacement)
            return (
                f"{label}: {src_name} ×{len(src_hits)} + {dist_name} ×{len(dist_hits)}"
                f"（锚点 {pattern!r}，只数代码命中）"
            )

    raise MutationError(
        f"{MARKER_IMPL_NOT_LANDED}: {label} —— 在 {' / '.join(src_candidates)} 里均未命中任何候选锚点"
        f"（最后一条：{last_miss}）。实现未按《调用契约》落地 ⇒ 本用例今日不可判（exit 12）"
    )


def v031_exemption_bare_trigger(contracts: Path, repo: Path) -> str:
    """改坏点 ①：把 `origin` 豁免写成裸 `trigger == "subagent"`（D10 反例① / K7①）。

    正确实现：`origin === RUN_ORIGIN_SUBAGENT`（`origin` 是应用层形参，客户端碰不到）。
    改坏后：只看 `trigger` —— 客户端可通过自由 `str` 字段伪造"子 run"身份绕过并发闸。
    ⇒ `apps/api/tests/subagent-spike.test.mjs` 的 **S-1-4** 必红。

    Args:
        contracts: 未使用（本族改的是实现，不是契约件）。
        repo: 克隆仓库根。

    Returns:
        一行"改了什么"。
    """
    del contracts
    return _v031_patch(
        repo,
        (
            "apps/api/src/modules/run/run-service.ts",
            "apps/api/src/modules/run/coordinator.ts",
        ),
        (
            (r"origin\s*===\s*(?:RUN_ORIGIN_SUBAGENT|[\"']SUBAGENT[\"'])", 'trigger === "subagent"'),
            (r"origin\s*(?:===|==)\s*(?:RUN_ORIGIN_SUBAGENT|[\"']SUBAGENT[\"'])", 'trigger == "subagent"'),
        ),
        label=f"① {VICTIM_V031_EXEMPTION}：origin 判据 → 裸 trigger 判据",
    )


def v031_stream_no_run_filter(contracts: Path, repo: Path) -> str:
    """改坏点 ②：去掉 `stream_run` 的 `run_id` 归属过滤（D2 反例 / K4）。

    去掉后子 run 的帧会汇入父流 ⇒ 前端会在子 run 的 `agent.completed` 上提前终止父流，
    并把 `activeRunId` 改写成子 run id —— 静默崩溃（K5b）。
    ⇒ **S-2-2** 必红（其反向断言"传 `runId` 与不传必须不同"直接抓住"形参没被消费"）。

    Args:
        contracts: 未使用。
        repo: 克隆仓库根。

    Returns:
        一行"改了什么"。
    """
    del contracts

    def _always_true(match: "re.Match[str]") -> str:
        return "true" if "===" in match.group(0) else "false"

    return _v031_patch(
        repo,
        ("apps/api/src/modules/run/sse-stream.ts",),
        (
            (r"(?:row|r|event)\.run_id\s*(?:!==|===)\s*runId", _always_true),
            (r"(?:row|r|event)\.run_id\s*(?:!=|==)\s*runId", _always_true),
        ),
        label=f"② {VICTIM_V031_STREAM}：归属比较 → 常量 true/false",
    )


def v031_depth_lt_3(contracts: Path, repo: Path) -> str:
    """改坏点 ③：把深度守卫从 `depth < maxDepth` 改成 `depth < 3`（D1 反例）。

    `max_subagent_depth` 缺省 1（单层委派）。改成硬编码 3 后，子 run 内再派生**不再被拒**
    ⇒ 委派树可无限下钻，D1 的 ④（`agent_run` 中 `trigger=='subagent'` 行数 == 0）失守。
    ⇒ **S-3-2** 必红。

    Args:
        contracts: 未使用。
        repo: 克隆仓库根。

    Returns:
        一行"改了什么"。
    """
    del contracts
    return _v031_patch(
        repo,
        (
            "apps/api/src/modules/run/subagent-guard.ts",
            "apps/api/src/modules/run/subagent-spawner.ts",
        ),
        (
            (r"depth\s*<\s*maxDepth", "depth < 3"),
            (r"depth\s*>=\s*maxDepth", "depth >= 3"),
            (r"depth\s*<\s*max_subagent_depth", "depth < 3"),
        ),
        label=f"③ {VICTIM_V031_DEPTH}：depth < maxDepth → depth < 3",
    )


def v031_watermark_local_increment(contracts: Path, repo: Path) -> str:
    """改坏点 ④：把无 `seq` 兜底分支保留为**连接本地自增**（不按 run 隔离）（D6 反例）。

    正确实现（两条路线任选其一，判据载体 `sse-watermark.test.mjs` 都判绿）：
      * 路线 A —— 缺 `seq` 的行**不下发**且**不推进水位**（跳过而非抛错，不得杀整条流）；
      * 路线 B —— 下发但**显式标记**，且编号作用域**声明为 run**。
    改坏后：无 `seq` 的行用"连接水位 + 1"的整数 `id:` **静默**下发 ⇒ 前端把它当
    `Last-Event-ID` 续传**拉错 run**，或父流水位被顶高后 gap-aware 直接停 ⇒
    **跳帧 / 永远空回放** —— 两者都是静默崩溃（K5b / D6 路径①②）。
    ⇒ `apps/api/tests/sse-watermark.test.mjs` 的 **W-2a** 必红
    （撞号场景：自增编号数字上落在父 run 的 `(run_id, seq)` 空间内，W-1 抓不住，
    只有 payload 探针能抓）。

    Args:
        contracts: 未使用（本族改的是实现，不是契约件）。
        repo: 克隆仓库根。

    Returns:
        一行"改了什么"。

    Raises:
        MutationError: 实现未落地 / dist 落后 / 锚点命中次数不为 1。
    """
    del contracts
    return _v031_patch(
        repo,
        (
            "apps/api/src/modules/run/sse-stream.ts",
            "apps/api/src/modules/run/sse-watermark.ts",
        ),
        (
            # **方案 2（QA 主审裁定，2026-10-23）**：把「守卫过滤」改成「本地自增补号」——
            #   有合法 seq 的行原样保留；无 seq / 非法 seq 的行改写为 `seq = i + 1`
            #   （i = 该行在本次连接里的下标 ⇒ **连接本地**自增）。
            #   ⇒ 无 seq 行以**真·整数 id** 静默下发，且编号**落在父 run 的
            #     (run_id, seq) 空间内**（撞号：第 3 行的合成 id 3 撞上父 run 真 seq 3）
            #     —— 与用例名 `local-increment` 的字面承诺一致，即 K5b 的真实危险形态。
            #
            #   为什么改整条语句（filter→map）而不是只换谓词（§4.6 实测）：
            #     只把 `Number.isInteger(row.seq)` 换成 `true` 会剩
            #     `true && row.seq >= 1`，而 `undefined >= 1` 恒为 false ⇒ 守卫照常拦下
            #     ⇒ 改坏是**语义空操作**（R-14 首判 FAKE-GREEN 的根因）。
            #     补号必须写进行本身 ⇒ 必须 filter→map。
            #
            #   为什么锚点用 `[^;]*;` 跨到语句尾：src 带 as-cast、dist 不带
            #   （`(row.seq as number) >= 1` vs `row.seq >= 1`），谓词级锚点无法
            #   两侧同形；语句级锚点两侧各命中 1 次（次数相等），且替换文本
            #   两边**同形**、各自合法（TS 侧 `{...row, seq}` 与 AgentEventRow 兼容）。
            #
            #   若将来实现改成 route-A 形态（`if (!Number.isInteger(row.seq)) continue;`），
            #   本锚点将不再命中 ⇒ 用例 UNEVALUABLE(12) ⇒ 按纪律重新校准锚点，
            #   **不得**回退到"只换谓词"的方案 1（那只证明抓得住崩流，不证明抓得住冒充）。
            (
                r"owned\.filter\(\s*\(\s*(?:row|r|item|event)\s*\)\s*=>[^;]*;",
                "owned.map((row, i) => (Number.isInteger(row.seq) && row.seq >= 1)"
                " ? row : { ...row, seq: i + 1 });",
            ),
        ),
        label=f"④ {VICTIM_V031_WATERMARK}：缺 seq 守卫 → 连接本地自增补号（整数 id 静默冒充）",
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
    # --- V0.3.1 · G031-4 spike（V031 用例集）--------------------------------
    InjectionCase(
        case_id="v031-exemption-bare-trigger",
        dod="V0.3.1 D10 · G031-4 S-1",
        target_gate="v031_spike",
        expected_reason=(
            f"{VICTIM_V031_EXEMPTION} 写成了裸 trigger 判据 ⇒ spike 的 S-1-4 红"
            "（origin 非 SUBAGENT 却拿到豁免 = 可被客户端注入）"
        ),
        description=(
            "把 `guardRunCreation` 的 `origin === RUN_ORIGIN_SUBAGENT` 换成 "
            '`trigger === "subagent"`（src 与 dist 双写）。'
        ),
        must_be_red=(
            "S-1-4",
            "豁免判据若写成裸 trigger=='subagent'",
        ),
        mutator=v031_exemption_bare_trigger,
        checks_integrity=False,
    ),
    InjectionCase(
        case_id="v031-stream-no-run-filter",
        dod="V0.3.1 D2 · G031-4 S-2",
        target_gate="v031_spike",
        expected_reason=(
            f"{VICTIM_V031_STREAM} 被去掉 ⇒ spike 的 S-2-2（D2-a）与 S-2-3（D2-b）红"
            "：跨 run 行汇入父流，父流帧数由 2 变 4"
        ),
        description=(
            "把 `streamRunFrames` 里的 `row.run_id === runId` 换成常量 `true`"
            "（`/ !== runId` 换 `false`），src 与 dist 双写。"
        ),
        # 令牌取自载体 S-2-2 的断言消息。注意：**不**用「传 runId 与不传必须不同」
        # 那条 —— 它已按架构裁定 §8.5 移出载体（当前 `StreamRunFramesOptions` 无
        # `runId` 形参，该断言恒红且红得无意义），改为 T031-05 待办断言。
        must_be_red=(
            "S-2-2",
            "父 run 只有 2 帧；子 run 的 2 帧必须被归属过滤掉",
        ),
        mutator=v031_stream_no_run_filter,
        checks_integrity=False,
    ),
    InjectionCase(
        case_id="v031-depth-lt-3",
        dod="V0.3.1 D1 · G031-4 S-3",
        target_gate="v031_spike",
        expected_reason=(
            f"{VICTIM_V031_DEPTH} 改成 depth < 3 ⇒ spike 的 S-3-2 红"
            "（max_subagent_depth=1 时子 run 内再派生不再被拒）"
        ),
        description=(
            "把 `subagent-guard.ts`（或 `subagent-spawner.ts`）里的 `depth < maxDepth` "
            "换成 `depth < 3`，src 与 dist 双写。"
        ),
        must_be_red=(
            "S-3-2",
            "max_subagent_depth=1 时子 run 内再派生必须被拒",
        ),
        mutator=v031_depth_lt_3,
        checks_integrity=False,
    ),
    InjectionCase(
        case_id="v031-watermark-local-increment",
        dod="V0.3.1 D6 · T031-05 出口判据 / T031-06 收口",
        target_gate="v031_watermark",
        expected_reason=(
            f"{VICTIM_V031_WATERMARK} 被保留 ⇒ sse-watermark 载体的 W-2a 红"
            "（无 seq 的行用连接本地自增的整数 id: 冒充父 run 游标 = 静默崩溃 K5b）"
        ),
        description=(
            "把无 `seq` 行的守卫（`!Number.isInteger(row.seq)` 或等价判断式）失效，"
            "使该行落到连接本地自增兜底，src 与 dist 双写。"
        ),
        must_be_red=(
            "W-2a",
            "无 seq 的行",
        ),
        mutator=v031_watermark_local_increment,
        checks_integrity=False,
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
        "v031_exemption": VICTIM_V031_EXEMPTION,
        "v031_stream": VICTIM_V031_STREAM,
        "v031_depth": VICTIM_V031_DEPTH,
        "v031_watermark": VICTIM_V031_WATERMARK,
    }
