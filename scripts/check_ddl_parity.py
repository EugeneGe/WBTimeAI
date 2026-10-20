#!/usr/bin/env python3
"""DoD#1 / DoD#2 — three-source DDL parity gate (PG / SQLite / their own ``.sql`` text).

What this gate is for
---------------------
The frozen DDL face of V0.0.1 is built from **three** sources (roadmap §3.3.1 /
M-02), and any one of them going missing silently shrinks the contract:

* source ①: ORM ``metadata`` compiled  -> 61 tables / 629 columns / 174 indexes;
* source ②: migration-chain raw DDL    -> 2 ``hnsw`` vector indexes (**ORM cannot
  express them**);
* source ③: SQLite-only objects        -> 1 FTS5 virtual table + 4 shadow tables
  + 3 sync triggers.

``run.py check`` only verifies sha256, so "delete one ``hnsw`` **and** re-pin every
sha" is invisible to it (evidence: ``V0.0.1`` 验收报告-回归 §4.2).  This gate is the
one that compares the *content* of the four artifacts against each other:

1. ``schema.v0018.pg.normalized.json``     <-> ``schema.v0018.pg.sql``
2. ``schema.v0018.sqlite.normalized.json`` <-> ``schema.v0018.sqlite.sql``
3. ``schema.v0018.pg.normalized.json``     <-> ``schema.v0018.sqlite.normalized.json``
   (table names / column names / nullability must agree; **types must not** — they
   are dialect-specific by definition: ``UUID`` vs ``CHAR(36)``, ``JSONB`` vs ``JSON``);
4. ``counts`` blocks vs the structures they claim to count.

Hard assertions (the reason this gate exists)
---------------------------------------------
* ``raw_indexes`` filtered by ``method == "hnsw"`` must be **exactly 2** in
  ``schema.v0018.pg.normalized.json``;
* ``CREATE INDEX ... USING hnsw`` must be **exactly 2** in ``schema.v0018.pg.sql``;
* both name sets must be identical.

Comparing only "columns and ordinary indexes" cannot see "one ``hnsw`` went
missing" — that is exactly the hole this gate closes.

Exit codes (§3.3 of the design doc)
-----------------------------------
* ``0`` — three sources agree (and the ``hnsw`` assertion holds);
* ``1`` — a difference was found (this is the red the injection cases target);
* ``2`` — usage error, or the artifacts could not be loaded;
* ``9`` — ``--self-test`` failed (the injected tamper did **not** go red, or the
  red reason was the wrong one).

``--self-test``
---------------
Never touches the real ``contracts/`` tree: it copies the four artifacts into a
:class:`tempfile.TemporaryDirectory`, then applies two named injections and
asserts that each one turns this gate red **for the right reason**:

* injection 1 — narrow one column's type (``VARCHAR(255)`` -> ``VARCHAR(64)``) in
  the **normalized JSON only**; the ``.sql`` text still says the old width, so the
  red reason must be a ``column-type`` diff naming that ``(table, column)``;
* injection 2 — delete one ``hnsw`` entry from ``raw_indexes`` in the
  **normalized JSON only**; the red reason must be ``hnsw-count`` (and an ordinary
  ``index`` diff), proving the "missing one hnsw" guard is live.

Python: standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import _gate_io
from _gate_io import (
    EXIT_OK,
    EXIT_SELFTEST,
    EXIT_USAGE,
    EXIT_VIOLATION,
    Diff,
    GateIOError,
    GatePaths,
    iter_sql_statements,
    load_json,
    load_text,
    log,
)

__all__ = [
    "TAG",
    "EXPECTED_HNSW_PG",
    "DIALECT_ONLY_KINDS",
    "ColumnDef",
    "TableDef",
    "SchemaEntities",
    "parse_pg_sql",
    "parse_sqlite_sql",
    "parity",
    "collect_diffs",
    "main",
]

#: Log tag (K-7).
TAG = "parity"

#: The four frozen artifacts this gate reads, relative to ``contracts/``.
PG_NORMALIZED = "schema.v0018.pg.normalized.json"
SQLITE_NORMALIZED = "schema.v0018.sqlite.normalized.json"
PG_SQL = "schema.v0018.pg.sql"
SQLITE_SQL = "schema.v0018.sqlite.sql"
ARTIFACTS: tuple[str, ...] = (PG_NORMALIZED, SQLITE_NORMALIZED, PG_SQL, SQLITE_SQL)

#: Roadmap §3.3.1: the PG face must carry **exactly two** ``hnsw`` indexes
#: (``ix_embedding_vector_hnsw`` / ``ix_memory_vector_hnsw``).  Anything else is a
#: silent loss of RAG recall capability.  This literal is the guard.
EXPECTED_HNSW_PG = 2

#: Object kinds that are legitimately dialect-specific and must therefore not be
#: reported as a cross-dialect "missing / extra" object.
DIALECT_ONLY_KINDS: frozenset[str] = frozenset(
    {"index", "extension", "virtual_table", "shadow_table", "trigger"}
)

#: Leading words of a *table-level* constraint inside ``CREATE TABLE (...)``.
#: Matched with a trailing ``\b`` so a column named ``checksum`` is **not** mistaken
#: for a ``CHECK`` constraint (the frozen PG face really has ``document.checksum``).
_RE_TABLE_CONSTRAINT = re.compile(
    r"^(?:CONSTRAINT|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE)\b",
    re.IGNORECASE,
)

#: Words that terminate the *type* part of a column definition.
_COLUMN_MODIFIERS: frozenset[str] = frozenset(
    {
        "NOT",
        "NULL",
        "DEFAULT",
        "PRIMARY",
        "REFERENCES",
        "UNIQUE",
        "CHECK",
        "COLLATE",
        "GENERATED",
        "AUTOINCREMENT",
        "AUTO_INCREMENT",
        "CONSTRAINT",
        "AS",
        "STORED",
        "VIRTUAL",
        "COMMENT",
        "ON",
    }
)

#: ``-- [sqlite_master] <stmt>`` marker used by ``schema.v0018.sqlite.sql`` for
#: objects that SQLite creates implicitly (shadow tables) and therefore cannot be
#: re-executed.  The gate treats the marked text as an authoritative declaration.
_SQLITE_MASTER_MARKER: re.Pattern[str] = re.compile(
    r"^\s*--\s*\[sqlite_master\]\s*(?P<stmt>.+?)\s*$",
    re.MULTILINE,
)

_RE_CREATE_TABLE = re.compile(
    r"^CREATE\s+(?P<virtual>VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s(]+)",
    re.IGNORECASE,
)
_RE_CREATE_INDEX = re.compile(
    r"^CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s(]+)",
    re.IGNORECASE,
)
_RE_CREATE_EXTENSION = re.compile(
    r"^CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s;]+)",
    re.IGNORECASE,
)
_RE_CREATE_TRIGGER = re.compile(
    r"^CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s(]+)",
    re.IGNORECASE,
)
_RE_HNSW = re.compile(r"\bUSING\s+hnsw\b", re.IGNORECASE)
_RE_INDEX_ON_TABLE = re.compile(r"\bON\s+(?P<table>[^\s(]+)", re.IGNORECASE)
_RE_ALTER_ADD_FK = re.compile(
    r"^ALTER\s+TABLE\s+(?P<table>\S+)\s+ADD\s+"
    r"(?:CONSTRAINT\s+(?P<name>\S+)\s+)?"
    r"FOREIGN\s+KEY\s*\((?P<cols>[^)]*)\)\s*"
    r"REFERENCES\s+(?P<rtable>[^\s(,]+)\s*\((?P<rcols>[^)]*)\)",
    re.IGNORECASE,
)
_RE_INLINE_FK = re.compile(
    r"(?:CONSTRAINT\s+(?P<name>\S+)\s+)?"
    r"FOREIGN\s+KEY\s*\((?P<cols>[^)]*)\)\s*"
    r"REFERENCES\s+(?P<rtable>[^\s(,]+)\s*\((?P<rcols>[^)]*)\)",
    re.IGNORECASE,
)
_RE_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.IGNORECASE)
_RE_BARE_END = re.compile(r"^END$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnDef:
    """One column, dialect-neutral.

    Attributes:
        name: Column name, unquoted.
        type: Dialect type, canonicalised by :func:`_normalize_type`.
        nullable: ``True`` when the column accepts ``NULL``.
    """

    name: str
    type: str
    nullable: bool


@dataclass
class TableDef:
    """One table and the metadata indexes that belong to it.

    Attributes:
        name: Table name, unquoted.
        columns: Column name -> definition, insertion-ordered for stable output.
        index_names: Index names created by the ORM metadata for this table.
    """

    name: str
    columns: dict[str, ColumnDef] = field(default_factory=dict)
    index_names: set[str] = field(default_factory=set)


@dataclass
class SchemaEntities:
    """One comparable "schema face".

    The same shape is produced from a ``.normalized.json`` document and from a
    ``.sql`` text, which is what makes the three-source comparison possible.

    Attributes:
        tables: Table name -> definition.
        index_names: Every index object name (metadata indexes **and** raw DDL
            indexes), so a dropped ``CREATE INDEX`` always shows up.
        extensions: Extension names (``CREATE EXTENSION``).
        counts: The ``counts`` block, as declared by the artifact (empty for a
            ``.sql`` text, which declares nothing).
        raw_index_names: Subset of ``index_names`` that came from raw DDL
            (migration-level, not expressible through the ORM metadata).
        hnsw_index_names: Subset of ``raw_index_names`` built with ``USING hnsw``.
        dialect_only: Object name -> kind, for objects that only exist on one
            dialect (FTS5 virtual table, shadow tables, triggers, raw indexes).
        foreign_keys: Canonical ``table(cols)->reftable(refcols)[:name]`` strings.
        triggers: Trigger names declared by the artifact.
        notes: Free-form parse notes (never used as a pass criterion).
    """

    tables: dict[str, TableDef] = field(default_factory=dict)
    index_names: set[str] = field(default_factory=set)
    extensions: set[str] = field(default_factory=set)
    counts: dict[str, Any] = field(default_factory=dict)
    raw_index_names: set[str] = field(default_factory=set)
    hnsw_index_names: set[str] = field(default_factory=set)
    dialect_only: dict[str, str] = field(default_factory=dict)
    foreign_keys: set[str] = field(default_factory=set)
    triggers: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    # -- constructors ------------------------------------------------------
    @classmethod
    def from_normalized(cls, document: Mapping[str, Any]) -> SchemaEntities:
        """Build the face from a ``*.normalized.json`` document.

        Args:
            document: The decoded normalized document.

        Returns:
            The populated :class:`SchemaEntities`.

        Raises:
            GateIOError: A required key is missing or has an unexpected shape.
        """
        if not isinstance(document, Mapping):
            raise GateIOError("normalized DDL document is not a JSON object")
        raw_tables = document.get("tables")
        if not isinstance(raw_tables, list):
            raise GateIOError("normalized DDL document has no 'tables' array")

        entities = cls(counts=dict(document.get("counts") or {}) if isinstance(
            document.get("counts"), Mapping
        ) else {})

        for raw_table in raw_tables:
            if not isinstance(raw_table, Mapping) or not raw_table.get("name"):
                raise GateIOError(f"malformed table entry: {raw_table!r}")
            name = str(raw_table["name"])
            table = TableDef(name=name)
            for raw_column in raw_table.get("columns") or []:
                if not isinstance(raw_column, Mapping) or not raw_column.get("name"):
                    raise GateIOError(f"malformed column in table {name}: {raw_column!r}")
                column = ColumnDef(
                    name=str(raw_column["name"]),
                    type=_normalize_type(str(raw_column.get("type") or "")),
                    nullable=bool(raw_column.get("nullable", False)),
                )
                table.columns[column.name] = column
            for raw_index in raw_table.get("indexes") or []:
                if isinstance(raw_index, Mapping) and raw_index.get("name"):
                    index_name = str(raw_index["name"])
                    table.index_names.add(index_name)
                    entities.index_names.add(index_name)
            entities.tables[name] = table

            for raw_fk in raw_table.get("foreign_keys") or []:
                if not isinstance(raw_fk, Mapping):
                    continue
                entities.foreign_keys.add(
                    _canonical_fk(
                        table=name,
                        name=raw_fk.get("name"),
                        columns=raw_fk.get("columns") or [],
                        referred_table=raw_fk.get("referred_table"),
                        referred_columns=raw_fk.get("referred_columns") or [],
                    )
                )

        for raw_index in document.get("raw_indexes") or []:
            if not isinstance(raw_index, Mapping) or not raw_index.get("name"):
                raise GateIOError(f"malformed raw_indexes entry: {raw_index!r}")
            index_name = str(raw_index["name"])
            entities.raw_index_names.add(index_name)
            entities.index_names.add(index_name)
            entities.dialect_only[index_name] = "index"
            if str(raw_index.get("method") or "").lower() == "hnsw":
                entities.hnsw_index_names.add(index_name)

        for raw_extension in document.get("extensions") or []:
            if isinstance(raw_extension, Mapping) and raw_extension.get("name"):
                entities.extensions.add(str(raw_extension["name"]))

        for raw_entry in document.get("dialect_only") or []:
            if isinstance(raw_entry, Mapping) and raw_entry.get("name"):
                entities.dialect_only[str(raw_entry["name"])] = str(
                    raw_entry.get("kind") or "unknown"
                )

        for raw_trigger in document.get("triggers") or []:
            if isinstance(raw_trigger, Mapping) and raw_trigger.get("name"):
                entities.triggers.add(str(raw_trigger["name"]))

        return entities

    @classmethod
    def from_sql(cls, text: str, *, dialect: str) -> SchemaEntities:
        """Build the face from a frozen ``.sql`` text.

        Args:
            text: Raw SQL file content.
            dialect: ``"postgresql"`` or ``"sqlite"``.  Determines whether
                ``[sqlite_master]`` comment declarations and ``CREATE VIRTUAL
                TABLE`` statements are recognised.

        Returns:
            The populated :class:`SchemaEntities`.

        Raises:
            GateIOError: The dialect is unknown.
        """
        if dialect not in ("postgresql", "sqlite"):
            raise GateIOError(f"unknown dialect: {dialect!r}")

        entities = cls()
        statements = list(_iter_declared_statements(text, dialect=dialect))

        # Pass 1 — every ``CREATE VIRTUAL TABLE`` name, so the FTS5 shadow tables
        # (``<vtab>_<suffix>``) can be recognised even though their declarations
        # are emitted before the virtual table itself.
        virtual_tables: list[str] = [
            _unquote(match.group("name"))
            for match in (_RE_CREATE_TABLE.match(item) for item in statements)
            if match is not None and match.group("virtual")
        ]

        # Pass 2 — classify and absorb.
        open_trigger: str | None = None

        for statement in statements:
            stripped = statement.strip()
            if not stripped:
                continue

            if _RE_BARE_END.match(stripped):
                # SQLite ``CREATE TRIGGER ... BEGIN ... END;``: a ``';'`` inside the
                # body splits it (documented in ``_gate_io.iter_sql_statements``),
                # so the trailing ``END`` statement closes the open trigger.
                if open_trigger is None:
                    entities.notes.append(
                        "orphan 'END' statement (no open CREATE TRIGGER) — ignored"
                    )
                else:
                    open_trigger = None
                continue

            if open_trigger is not None:
                # Body continuation of a multi-statement trigger body.
                continue

            trigger_match = _RE_CREATE_TRIGGER.match(stripped)
            if trigger_match:
                name = _unquote(trigger_match.group("name"))
                entities.triggers.add(name)
                entities.dialect_only[name] = "trigger"
                open_trigger = name
                continue

            table_match = _RE_CREATE_TABLE.match(stripped)
            if table_match:
                name = _unquote(table_match.group("name"))
                if table_match.group("virtual"):
                    entities.dialect_only[name] = "virtual_table"
                    continue
                if any(name.startswith(f"{virtual}_") for virtual in virtual_tables):
                    # FTS5 shadow table: SQLite names them ``<vtab>_<suffix>``.
                    entities.dialect_only[name] = "shadow_table"
                    continue
                _absorb_create_table(entities, name, stripped)
                continue

            index_match = _RE_CREATE_INDEX.match(stripped)
            if index_match:
                name = _unquote(index_match.group("name"))
                entities.index_names.add(name)
                is_raw = bool(_RE_HNSW.search(stripped))
                if is_raw:
                    entities.raw_index_names.add(name)
                    entities.hnsw_index_names.add(name)
                    entities.dialect_only[name] = "index"
                else:
                    # Raw DDL indexes live in the top-level ``raw_indexes`` array of
                    # the normalized document, not in a table's metadata index list,
                    # so they are deliberately not attached to ``TableDef.index_names``
                    # here either — otherwise ``counts.metadata_indexes`` could never
                    # reconcile.
                    on_match = _RE_INDEX_ON_TABLE.search(stripped)
                    if on_match:
                        owner = _unquote(on_match.group("table"))
                        if owner in entities.tables:
                            entities.tables[owner].index_names.add(name)
                        else:
                            entities.notes.append(
                                f"index {name} references an unknown table {owner}"
                            )
                continue

            extension_match = _RE_CREATE_EXTENSION.match(stripped)
            if extension_match:
                entities.extensions.add(_unquote(extension_match.group("name")))
                continue

            alter_match = _RE_ALTER_ADD_FK.match(stripped)
            if alter_match:
                entities.foreign_keys.add(
                    _canonical_fk(
                        table=_unquote(alter_match.group("table")),
                        name=alter_match.group("name"),
                        columns=[alter_match.group("cols")],
                        referred_table=_unquote(alter_match.group("rtable")),
                        referred_columns=[alter_match.group("rcols")],
                    )
                )
                continue

            entities.notes.append(f"unclassified statement: {stripped.splitlines()[0][:120]}")

        return entities

    # -- comparison --------------------------------------------------------
    def diff(self, other: SchemaEntities) -> list[Diff]:
        """Compare two faces of the **same** dialect (normalized vs ``.sql``).

        Args:
            other: The right-hand face.

        Returns:
            Every difference, deterministically ordered.
        """
        report = _compare_tables(self, other)
        report.extend(
            _prefix_diff("index", self.index_names, other.index_names)
        )
        report.extend(
            _prefix_diff("extension", self.extensions, other.extensions)
        )
        report.extend(_prefix_diff("foreign-key", self.foreign_keys, other.foreign_keys))
        report.extend(
            _prefix_diff(
                "dialect-only",
                set(self.dialect_only),
                set(other.dialect_only),
            )
        )
        for name in sorted(set(self.dialect_only) & set(other.dialect_only)):
            if self.dialect_only[name] != other.dialect_only[name]:
                report.append(
                    Diff(
                        kind="dialect-only-kind",
                        subject=name,
                        left=self.dialect_only[name],
                        right=other.dialect_only[name],
                    )
                )
        return report

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        """Return a one-line human summary used by the gate output."""
        columns = sum(len(table.columns) for table in self.tables.values())
        return (
            f"tables={len(self.tables)} columns={columns} "
            f"indexes={len(self.index_names)} raw={len(self.raw_index_names)} "
            f"hnsw={len(self.hnsw_index_names)} extensions={len(self.extensions)} "
            f"dialect_only={len(self.dialect_only)} fks={len(self.foreign_keys)}"
        )


# ---------------------------------------------------------------------------
# SQL text parsing helpers
# ---------------------------------------------------------------------------
def _iter_declared_statements(text: str, *, dialect: str) -> Iterator[str]:
    """Yield every declared statement, including SQLite's implicit objects.

    For ``dialect == "sqlite"`` the frozen artifact also declares the FTS5 shadow
    tables **inside comments** (prefix ``-- [sqlite_master]``), because re-issuing
    ``CREATE TABLE`` for them would fail with "table ... already exists".  Those
    declarations are authoritative and must be parsed, otherwise four real objects
    would be invisible to the parity check.

    Args:
        text: Raw SQL file content.
        dialect: ``"postgresql"`` or ``"sqlite"``.

    Yields:
        Statements in file order: the commented ``[sqlite_master]`` declarations
        first (they live in their own section), then the executable statements.
    """
    if dialect == "sqlite":
        for match in _SQLITE_MASTER_MARKER.finditer(text):
            declared = match.group("stmt").strip()
            if declared.endswith(";"):
                declared = declared[:-1].rstrip()
            if declared:
                yield declared
    yield from iter_sql_statements(text)


def _absorb_create_table(entities: SchemaEntities, name: str, statement: str) -> None:
    """Parse one ``CREATE TABLE`` statement into ``entities``.

    Args:
        entities: Face being populated (mutated in place).
        name: Table name, already unquoted.
        statement: The full statement text.
    """
    table = TableDef(name=name)
    body = _table_body(statement)
    if body is None:
        entities.notes.append(f"CREATE TABLE without a body: {name}")
        entities.tables[name] = table
        return

    for part in _split_top_level(body):
        if _RE_TABLE_CONSTRAINT.match(part):
            fk_match = _RE_INLINE_FK.search(part)
            if fk_match:
                entities.foreign_keys.add(
                    _canonical_fk(
                        table=name,
                        name=fk_match.group("name"),
                        columns=[fk_match.group("cols")],
                        referred_table=_unquote(fk_match.group("rtable")),
                        referred_columns=[fk_match.group("rcols")],
                    )
                )
            continue
        column = _parse_column(part, table=name, entities=entities)
        if column is not None:
            table.columns[column.name] = column

    entities.tables[name] = table


def _parse_column(
    part: str, *, table: str, entities: SchemaEntities
) -> ColumnDef | None:
    """Parse one column definition.

    Args:
        part: One comma-separated fragment of a ``CREATE TABLE`` body.
        table: Owning table name (for notes only).
        entities: Face receiving parse notes.

    Returns:
        The column, or ``None`` when the fragment is not a column definition.
    """
    tokens = _tokenize(part)
    if not tokens:
        return None
    name = _unquote(tokens[0])
    if not name:
        return None

    type_tokens: list[str] = []
    for token in tokens[1:]:
        if token.upper() in _COLUMN_MODIFIERS:
            break
        type_tokens.append(token)
    if not type_tokens:
        entities.notes.append(f"column without a type: {table}.{name}")
        return None

    return ColumnDef(
        name=name,
        type=_normalize_type(" ".join(type_tokens)),
        nullable=not _RE_NOT_NULL.search(part),
    )


def _tokenize(fragment: str) -> list[str]:
    """Split a column fragment into name/type/modifier tokens.

    Parentheses, commas and quotes become their own tokens so the caller can
    accumulate a type such as ``NUMERIC ( 18 , 6 )`` without losing punctuation.

    Args:
        fragment: One comma-separated fragment of a ``CREATE TABLE`` body.

    Returns:
        The token list.
    """
    tokens: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(fragment)
    while index < length:
        char = fragment[index]
        if char in ("'", '"', "`"):
            closing = "]" if char == "[" else char
            start = index
            index += 1
            while index < length:
                if fragment[index] == closing:
                    if index + 1 < length and fragment[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()
            tokens.append(fragment[start:index])
            continue
        if char == "[":
            closing = "]"
            start = index
            index += 1
            while index < length:
                if fragment[index] == closing:
                    index += 1
                    break
                index += 1
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()
            tokens.append(fragment[start:index])
            continue
        if char in "(),":
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()
            tokens.append(char)
            index += 1
            continue
        if char.isspace():
            if buffer:
                tokens.append("".join(buffer))
                buffer.clear()
            index += 1
            continue
        buffer.append(char)
        index += 1
    if buffer:
        tokens.append("".join(buffer))
    return tokens


def _table_body(statement: str) -> str | None:
    """Return the text between the outermost parentheses of a statement.

    Args:
        statement: A ``CREATE TABLE`` statement.

    Returns:
        The body, or ``None`` when the parentheses are unbalanced.
    """
    start = statement.find("(")
    if start == -1:
        return None
    depth = 0
    index = start
    length = len(statement)
    while index < length:
        char = statement[index]
        if char in ("'", '"', "`"):
            closing = char
            index += 1
            while index < length:
                if statement[index] == closing:
                    if index + 1 < length and statement[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return statement[start + 1 : index]
        index += 1
    return None


def _split_top_level(body: str) -> list[str]:
    """Split a ``CREATE TABLE`` body on top-level commas.

    Args:
        body: The text between the outermost parentheses.

    Returns:
        The comma-separated fragments, stripped and non-empty.
    """
    fragments: list[str] = []
    buffer: list[str] = []
    depth = 0
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char in ("'", '"', "`"):
            closing = char
            start = index
            index += 1
            while index < length:
                if body[index] == closing:
                    if index + 1 < length and body[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            buffer.append(body[start:index])
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            fragments.append("".join(buffer).strip())
            buffer.clear()
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        fragments.append(tail)
    return [fragment for fragment in fragments if fragment]


def _normalize_type(raw: str) -> str:
    """Canonicalise a type string so both sides of a comparison agree.

    Applied to **both** the normalized JSON and the ``.sql`` text, so
    ``NUMERIC(18, 6)`` and ``NUMERIC ( 18 , 6 )`` are the same type.

    Args:
        raw: The raw type text.

    Returns:
        Upper-cased, whitespace-collapsed, punctuation-tight type text.
    """
    text = " ".join(str(raw).split()).upper()
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    text = re.sub(r"\s*,\s*", ",", text)
    return text.strip()


def _unquote(identifier: str | None) -> str:
    """Strip SQL identifier quoting.

    Args:
        identifier: A possibly quoted identifier (``"user"``, ``'x'``, ``[x]``,
            ```` `x` ````).

    Returns:
        The bare identifier (``""`` for ``None``).
    """
    if identifier is None:
        return ""
    text = str(identifier).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "`"):
        return text[1:-1]
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return text[1:-1]
    return text


def _column_list(raw: Any) -> tuple[str, ...]:
    """Turn a column reference into a tuple of bare names.

    Args:
        raw: A string (``"a, b"`` / ``"a"``) or a list of names.

    Returns:
        The bare names, in order.
    """
    if isinstance(raw, str):
        pieces = [piece.strip() for piece in raw.split(",")]
    elif isinstance(raw, Iterable):
        pieces = [str(piece).strip() for piece in raw]
    else:
        pieces = []
    return tuple(_unquote(piece) for piece in pieces if piece)


def _canonical_fk(
    *,
    table: str | None,
    name: str | None,
    columns: Any,
    referred_table: str | None,
    referred_columns: Any,
) -> str:
    """Render a foreign key as one canonical, comparable string.

    Args:
        table: Owning table.
        name: Constraint name (``None`` for an unnamed FK).
        columns: Local columns.
        referred_table: Referenced table.
        referred_columns: Referenced columns.

    Returns:
        ``"<table>(<cols>)-><reftable>(<refcols>)[:<name>]"``.
    """
    local = ",".join(_column_list(columns))
    remote = ",".join(_column_list(referred_columns))
    suffix = f":{_unquote(name)}" if name else ""
    return f"{_unquote(table)}({local})->{_unquote(referred_table)}({remote}){suffix}"


# ---------------------------------------------------------------------------
# §3.2 public parsers
# ---------------------------------------------------------------------------
def parse_pg_sql(text: str) -> SchemaEntities:
    """Parse ``schema.v0018.pg.sql``.

    Args:
        text: Raw SQL file content.

    Returns:
        The PostgreSQL face.
    """
    return SchemaEntities.from_sql(text, dialect="postgresql")


def parse_sqlite_sql(text: str) -> SchemaEntities:
    """Parse ``schema.v0018.sqlite.sql``.

    Recognises the ``-- [sqlite_master]`` declarations for the FTS5 shadow tables
    and merges ``CREATE TRIGGER ... BEGIN <stmts> END;`` bodies that the shared
    ``';'`` splitter breaks apart.

    Args:
        text: Raw SQL file content.

    Returns:
        The SQLite face.
    """
    return SchemaEntities.from_sql(text, dialect="sqlite")


# ---------------------------------------------------------------------------
# Comparison rules
# ---------------------------------------------------------------------------
def _prefix_diff(kind: str, left: set[str], right: set[str]) -> list[Diff]:
    """Report ``left`` vs ``right`` under a specific ``kind`` label.

    Args:
        kind: The diff kind to stamp on every record.
        left: Left-hand names.
        right: Right-hand names.

    Returns:
        One :class:`Diff` per symmetric-difference member.
    """
    report: list[Diff] = []
    for diff in _gate_io.set_diff_report(left, right):
        report.append(
            Diff(kind=kind, subject=diff.subject, left=diff.left, right=diff.right)
        )
    return report


def _compare_tables(left: SchemaEntities, right: SchemaEntities) -> list[Diff]:
    """Compare table names and, per table, column names / types / nullability.

    Args:
        left: Left-hand face.
        right: Right-hand face.

    Returns:
        Table-level and column-level diffs.
    """
    report = _prefix_diff("table", set(left.tables), set(right.tables))
    for table_name in sorted(set(left.tables) & set(right.tables)):
        left_table = left.tables[table_name]
        right_table = right.tables[table_name]
        report.extend(
            _prefix_diff(
                "column",
                {f"{table_name}.{name}" for name in left_table.columns},
                {f"{table_name}.{name}" for name in right_table.columns},
            )
        )
        for column_name in sorted(set(left_table.columns) & set(right_table.columns)):
            left_column = left_table.columns[column_name]
            right_column = right_table.columns[column_name]
            subject = f"{table_name}.{column_name}"
            if left_column.type != right_column.type:
                report.append(
                    Diff(
                        kind="column-type",
                        subject=subject,
                        left=left_column.type,
                        right=right_column.type,
                    )
                )
            if left_column.nullable != right_column.nullable:
                report.append(
                    Diff(
                        kind="column-nullable",
                        subject=subject,
                        left=str(left_column.nullable).lower(),
                        right=str(right_column.nullable).lower(),
                    )
                )
        report.extend(
            _prefix_diff(
                "table-index",
                {f"{table_name}.{name}" for name in left_table.index_names},
                {f"{table_name}.{name}" for name in right_table.index_names},
            )
        )
    return report


def _compare_cross_dialect(
    left: SchemaEntities, right: SchemaEntities, *, dialect_only: frozenset[str]
) -> list[Diff]:
    """Compare two faces of **different** dialects.

    Only the dialect-neutral facts are compared: table names, column names and
    nullability.  Column **types differ by design** (``UUID`` vs ``CHAR(36)``,
    ``JSONB`` vs ``JSON``, ``TIMESTAMP WITH TIME ZONE`` vs ``DATETIME``), so type
    equality must never be demanded here.

    Args:
        left: Left-hand face (PostgreSQL).
        right: Right-hand face (SQLite).
        dialect_only: Object kinds allowed to exist on one dialect only; names in
            this set are excluded from the table-name comparison.

    Returns:
        Cross-dialect diffs.
    """
    left_tables = {
        name
        for name in left.tables
        if left.dialect_only.get(name) not in dialect_only
    }
    right_tables = {
        name
        for name in right.tables
        if right.dialect_only.get(name) not in dialect_only
    }
    report = _prefix_diff("cross-table", left_tables, right_tables)
    for table_name in sorted(left_tables & right_tables):
        left_table = left.tables[table_name]
        right_table = right.tables[table_name]
        report.extend(
            _prefix_diff(
                "cross-column",
                {f"{table_name}.{name}" for name in left_table.columns},
                {f"{table_name}.{name}" for name in right_table.columns},
            )
        )
        for column_name in sorted(set(left_table.columns) & set(right_table.columns)):
            if left_table.columns[column_name].nullable != right_table.columns[
                column_name
            ].nullable:
                report.append(
                    Diff(
                        kind="cross-column-nullable",
                        subject=f"{table_name}.{column_name}",
                        left=str(left_table.columns[column_name].nullable).lower(),
                        right=str(right_table.columns[column_name].nullable).lower(),
                    )
                )
    return report


def _check_counts(label: str, entities: SchemaEntities) -> list[Diff]:
    """Verify that a ``counts`` block agrees with the structures it counts.

    This catches the cheapest forgery — "change the number, not the structure"
    (ATK-1 in the design doc) — before any cross-source comparison runs.

    Args:
        label: Human label used in the diff subject (``pg.normalized`` ...).
        entities: The face whose ``counts`` block is checked.

    Returns:
        One ``count`` diff per inconsistent counter.
    """
    if not entities.counts:
        return [Diff(kind="count", subject=f"{label}.counts", left="present", right="absent")]

    counts = entities.counts
    tables = list(entities.tables.values())
    # Only counters that are fully recoverable from the parsed structures are
    # asserted here.  ``unique_indexes`` / ``partial_indexes`` depend on a
    # per-index ``unique`` / ``where`` flag that this face does not carry: those
    # numbers belong to ``verify_semantics.py`` (C6 family).  Re-checking them
    # from a second place would create a second place to weaken a criterion.
    actual: dict[str, int] = {
        "tables": len(entities.tables),
        "columns": sum(len(table.columns) for table in tables),
        "metadata_indexes": sum(len(table.index_names) for table in tables),
        "foreign_keys": len(entities.foreign_keys),
        "raw_indexes": len(entities.raw_index_names),
        "extensions": len(entities.extensions),
        "triggers": len(entities.triggers),
    }

    report: list[Diff] = []
    for key, value in actual.items():
        if key not in counts:
            report.append(
                Diff(kind="count", subject=f"{label}.{key}", left="expected", right="missing")
            )
            continue
        if int(counts[key]) != value:
            report.append(
                Diff(
                    kind="count",
                    subject=f"{label}.{key}",
                    left=str(counts[key]),
                    right=str(value),
                )
            )

    metadata_indexes = counts.get("metadata_indexes")
    raw_indexes = counts.get("raw_indexes")
    total = counts.get("index_objects_total")
    if isinstance(metadata_indexes, int) and isinstance(raw_indexes, int) and isinstance(
        total, int
    ):
        if total != metadata_indexes + raw_indexes:
            report.append(
                Diff(
                    kind="count",
                    subject=f"{label}.index_objects_total",
                    left=str(total),
                    right=str(metadata_indexes + raw_indexes),
                )
            )

    if "dialect_only_objects" in counts and int(counts["dialect_only_objects"]) != len(
        entities.dialect_only
    ):
        report.append(
            Diff(
                kind="count",
                subject=f"{label}.dialect_only_objects",
                left=str(counts["dialect_only_objects"]),
                right=str(len(entities.dialect_only)),
            )
        )

    declared_by_kind = counts.get("dialect_only_by_kind")
    if isinstance(declared_by_kind, Mapping):
        expected_by_kind: Counter[str] = Counter(entities.dialect_only.values())
        if dict(expected_by_kind) != dict(declared_by_kind):
            report.append(
                Diff(
                    kind="count",
                    subject=f"{label}.dialect_only_by_kind",
                    left=json.dumps(dict(declared_by_kind), sort_keys=True),
                    right=json.dumps(dict(expected_by_kind), sort_keys=True),
                )
            )
    return report


def _assert_hnsw(
    pg_norm: SchemaEntities, pg_sql: SchemaEntities, *, expected: int = EXPECTED_HNSW_PG
) -> list[Diff]:
    """Assert the PG face carries exactly ``expected`` ``hnsw`` indexes.

    This is the guard the roadmap §3.3.1 omission needs: a plain
    "columns and indexes" comparison cannot tell the difference between
    "2 hnsw" and "1 hnsw" once the sha256 ledger has been re-pinned.

    Args:
        pg_norm: PG face parsed from the normalized document.
        pg_sql: PG face parsed from the ``.sql`` text.
        expected: The required number of ``hnsw`` indexes.

    Returns:
        Diffs for a wrong count on either side, and for name-set disagreement.
    """
    report: list[Diff] = []
    for label, entities in (("pg.normalized", pg_norm), ("pg.sql", pg_sql)):
        actual = len(entities.hnsw_index_names)
        if actual != expected:
            report.append(
                Diff(
                    kind="hnsw-count",
                    subject=f"{label}.hnsw_indexes",
                    left=str(expected),
                    right=str(actual),
                )
            )
    report.extend(
        _prefix_diff("hnsw-name", pg_norm.hnsw_index_names, pg_sql.hnsw_index_names)
    )
    return report


def parity(
    pg_norm: SchemaEntities,
    sqlite_norm: SchemaEntities,
    pg_sql: SchemaEntities,
    *,
    dialect_only: frozenset[str] = DIALECT_ONLY_KINDS,
    sqlite_sql: SchemaEntities | None = None,
) -> list[Diff]:
    """Compare the three (optionally four) DDL sources.

    Args:
        pg_norm: PostgreSQL, from ``schema.v0018.pg.normalized.json``.
        sqlite_norm: SQLite, from ``schema.v0018.sqlite.normalized.json``.
        pg_sql: PostgreSQL, from ``schema.v0018.pg.sql``.
        dialect_only: Object kinds allowed to exist on one dialect only.
        sqlite_sql: SQLite, from ``schema.v0018.sqlite.sql``.  Optional so the
            function matches §3.2 of the design doc exactly; when supplied the
            SQLite normalized-vs-text face is checked too (the design's "各自对应
            的 ``.sql`` 文本" requirement).

    Returns:
        Every diff, sorted by ``(kind, subject)`` for stable evidence output.
    """
    report: list[Diff] = []
    report.extend(_check_counts("pg.normalized", pg_norm))
    report.extend(_check_counts("sqlite.normalized", sqlite_norm))
    report.extend(_assert_hnsw(pg_norm, pg_sql))
    report.extend(_compare_same_dialect("pg", pg_norm, pg_sql))
    if sqlite_sql is not None:
        report.extend(_compare_same_dialect("sqlite", sqlite_norm, sqlite_sql))
    report.extend(
        _compare_cross_dialect(pg_norm, sqlite_norm, dialect_only=dialect_only)
    )
    return sorted(report, key=lambda diff: (diff.kind, diff.subject, diff.left, diff.right))


def _compare_same_dialect(
    label: str, normalized: SchemaEntities, sql_text: SchemaEntities
) -> list[Diff]:
    """Compare a normalized document against its own ``.sql`` text.

    Args:
        label: ``"pg"`` or ``"sqlite"``; used to prefix the diff kind.
        normalized: Face built from the ``.normalized.json``.
        sql_text: Face built from the ``.sql`` text.

    Returns:
        Prefixed diffs.
    """
    return [
        Diff(
            kind=f"{label}.{diff.kind}",
            subject=diff.subject,
            left=diff.left,
            right=diff.right,
        )
        for diff in normalized.diff(sql_text)
    ]


# ---------------------------------------------------------------------------
# Gate entry point
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Sources:
    """The four parsed faces, kept together for reporting."""

    pg_norm: SchemaEntities
    sqlite_norm: SchemaEntities
    pg_sql: SchemaEntities
    sqlite_sql: SchemaEntities


def load_sources(contracts_dir: Path) -> Sources:
    """Load and parse all four DDL artifacts.

    Args:
        contracts_dir: Directory holding the frozen artifacts.

    Returns:
        The parsed :class:`Sources`.

    Raises:
        GateIOError: An artifact is missing or unparsable.
    """
    pg_norm = SchemaEntities.from_normalized(load_json(contracts_dir / PG_NORMALIZED))
    sqlite_norm = SchemaEntities.from_normalized(
        load_json(contracts_dir / SQLITE_NORMALIZED)
    )
    pg_sql = parse_pg_sql(load_text(contracts_dir / PG_SQL))
    sqlite_sql = parse_sqlite_sql(load_text(contracts_dir / SQLITE_SQL))
    return Sources(
        pg_norm=pg_norm, sqlite_norm=sqlite_norm, pg_sql=pg_sql, sqlite_sql=sqlite_sql
    )


def collect_diffs(contracts_dir: Path) -> tuple[list[Diff], Sources]:
    """Run the whole three-source parity check against ``contracts_dir``.

    Args:
        contracts_dir: Directory holding the frozen artifacts.

    Returns:
        ``(diffs, sources)`` where ``diffs`` is empty when the sources agree.

    Raises:
        GateIOError: An artifact is missing or unparsable.
    """
    sources = load_sources(contracts_dir)
    diffs = parity(
        sources.pg_norm,
        sources.sqlite_norm,
        sources.pg_sql,
        dialect_only=DIALECT_ONLY_KINDS,
        sqlite_sql=sources.sqlite_sql,
    )
    return diffs, sources


def _report_sources(sources: Sources) -> None:
    """Print the four one-line summaries plus the parse notes.

    Args:
        sources: The parsed faces.
    """
    log(TAG, f"pg.normalized      : {sources.pg_norm.summary()}")
    log(TAG, f"pg.sql             : {sources.pg_sql.summary()}")
    log(TAG, f"sqlite.normalized  : {sources.sqlite_norm.summary()}")
    log(TAG, f"sqlite.sql         : {sources.sqlite_sql.summary()}")
    for label, entities in (
        ("pg.sql", sources.pg_sql),
        ("sqlite.sql", sources.sqlite_sql),
    ):
        for note in entities.notes:
            log(TAG, f"note({label}): {note}")


def _emit_diffs(diffs: Sequence[Diff], *, tag: str = TAG) -> None:
    """Print every diff as one ASCII-preferring line.

    Args:
        diffs: Diffs to print.
        tag: Log tag.
    """
    for diff in diffs:
        log(tag, f"DIFF {diff.render()}")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments without the program name (``None`` -> ``sys.argv[1:]``).

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="check_ddl_parity.py",
        description=(
            "Three-source DDL parity: pg.normalized / sqlite.normalized / their .sql "
            "texts, plus the hard 'exactly 2 hnsw indexes' assertion."
        ),
    )
    parser.add_argument(
        "--contracts",
        default=None,
        metavar="DIR",
        help="contracts directory to read (default: <repo>/contracts)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the two named injections on a temporary clone (exit 9 on failure)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the diffs as a JSON array instead of log lines",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` three sources agree, ``1`` difference found, ``2`` usage / load
        failure, ``9`` ``--self-test`` failed.
    """
    try:
        arguments = _parse_arguments(argv)
    except SystemExit as exit_error:  # argparse already printed the message
        return EXIT_USAGE if exit_error.code else EXIT_OK

    paths = GatePaths.resolve(contracts_dir=arguments.contracts)

    if arguments.self_test:
        return _self_test(paths.contracts_dir)

    log(TAG, f"contracts: {paths.contracts_dir.as_posix()}")
    try:
        diffs, sources = collect_diffs(paths.contracts_dir)
    except GateIOError as error:
        log(TAG, f"ERROR: cannot load DDL artifacts: {error}")
        return EXIT_USAGE

    _report_sources(sources)
    log(
        TAG,
        f"hnsw hard assertion: pg.normalized={len(sources.pg_norm.hnsw_index_names)} "
        f"pg.sql={len(sources.pg_sql.hnsw_index_names)} expected={EXPECTED_HNSW_PG}",
    )

    if arguments.json:
        print(json.dumps([diff.to_dict() for diff in diffs], ensure_ascii=False, indent=2))

    if diffs:
        _emit_diffs(diffs)
        log(TAG, f"VERDICT: FAIL ({len(diffs)} differences)")
        return EXIT_VIOLATION

    log(TAG, "VERDICT: PASS (three sources agree; hnsw == 2 on both PG sources)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------
def _clone(contracts_dir: Path, destination: Path) -> Path:
    """Copy the four DDL artifacts into a scratch directory.

    Args:
        contracts_dir: Source ``contracts/`` directory (read-only in spirit).
        destination: Fresh scratch directory.

    Returns:
        The scratch directory.

    Raises:
        GateIOError: An artifact is missing.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for relative in ARTIFACTS:
        source = contracts_dir / relative
        if not source.is_file():
            raise GateIOError(f"missing artifact: {source.as_posix()}")
        shutil.copy2(source, destination / relative)
    return destination


def _inject_narrow_column(clone_dir: Path) -> str:
    """Injection 1: narrow one column type in the normalized JSON only.

    Args:
        clone_dir: Scratch ``contracts/`` copy.

    Returns:
        A description of what was changed.

    Raises:
        GateIOError: No ``VARCHAR(255)`` column is available to narrow.
    """
    target = clone_dir / PG_NORMALIZED
    document = load_json(target)
    for table in document.get("tables") or []:
        for column in table.get("columns") or []:
            if _normalize_type(str(column.get("type") or "")) == "VARCHAR(255)":
                column["type"] = "VARCHAR(64)"
                target.write_text(
                    json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return (
                    f"narrowed {table['name']}.{column['name']} "
                    "VARCHAR(255)->VARCHAR(64) in pg.normalized only"
                )
    raise GateIOError("no VARCHAR(255) column found to narrow")


def _inject_drop_hnsw(clone_dir: Path) -> str:
    """Injection 2: drop one ``hnsw`` index from the normalized ``raw_indexes``.

    Only ``raw_indexes`` is touched: neither ``counts`` nor the ``.sql`` text is
    edited, so the gate must catch it both via the ``hnsw == 2`` assertion and via
    the ordinary index comparison.

    Args:
        clone_dir: Scratch ``contracts/`` copy.

    Returns:
        A description of what was changed.

    Raises:
        GateIOError: There is no ``hnsw`` index to drop.
    """
    target = clone_dir / PG_NORMALIZED
    document = load_json(target)
    raw_indexes = document.get("raw_indexes") or []
    victim = next(
        (
            entry
            for entry in raw_indexes
            if str(entry.get("method") or "").lower() == "hnsw"
            and entry.get("name") == "ix_memory_vector_hnsw"
        ),
        None,
    )
    if victim is None:
        victim = next(
            (
                entry
                for entry in raw_indexes
                if str(entry.get("method") or "").lower() == "hnsw"
            ),
            None,
        )
    if victim is None:
        raise GateIOError("no hnsw entry in pg.normalized raw_indexes to drop")
    document["raw_indexes"] = [entry for entry in raw_indexes if entry is not victim]
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return f"dropped raw index {victim['name']} from pg.normalized raw_indexes only"


def _expect(
    *,
    label: str,
    diffs: Sequence[Diff],
    must_contain_kind: str,
    must_name: str | None = None,
) -> bool:
    """Assert that a tampered clone goes red for the expected reason.

    Args:
        label: Injection label, for output.
        diffs: Diffs produced by the gate on the tampered clone.
        must_contain_kind: The diff kind that must appear.
        must_name: A subject fragment that must appear on a diff of that kind.

    Returns:
        ``True`` when the specific expected red reason is present.
    """
    hits = [diff for diff in diffs if diff.kind == must_contain_kind]
    if not hits:
        log(
            "parity",
            f"SELFTEST FAIL [{label}]: expected a '{must_contain_kind}' diff, got "
            f"{sorted({diff.kind for diff in diffs}) or 'no diffs at all'}",
        )
        return False
    if must_name is not None:
        named = [diff for diff in hits if must_name in diff.subject]
        if not named:
            log(
                "parity",
                f"SELFTEST FAIL [{label}]: '{must_contain_kind}' diff did not name "
                f"{must_name} (subjects={[diff.subject for diff in hits][:5]})",
            )
            return False
        hits = named
    if not diffs:
        log("parity", f"SELFTEST FAIL [{label}]: gate stayed green on a tampered clone")
        return False
    log("parity", f"SELFTEST OK [{label}]: red on {must_contain_kind} -> {hits[0].render()}")
    return True


def _self_test(contracts_dir: Path) -> int:
    """Run both named injections on a temporary clone.

    Args:
        contracts_dir: The real (read-only) ``contracts/`` directory.

    Returns:
        ``0`` when both injections turn the gate red for the right reason,
        ``9`` otherwise.
    """
    log(TAG, f"self-test: cloning artifacts from {contracts_dir.as_posix()}")
    failures = 0
    try:
        with tempfile.TemporaryDirectory(prefix="wbtime-parity-") as scratch:
            root = Path(scratch)

            # Step 0 — the clone must be green, otherwise "red" would prove nothing.
            baseline_dir = _clone(contracts_dir, root / "baseline")
            baseline_diffs, _ = collect_diffs(baseline_dir)
            if baseline_diffs:
                log(
                    TAG,
                    "SELFTEST FAIL [baseline]: the untouched clone is already red "
                    f"({len(baseline_diffs)} diffs)",
                )
                _emit_diffs(baseline_diffs[:10])
                failures += 1
            else:
                log(TAG, "SELFTEST OK [baseline]: untouched clone is green")

            # Step 1 — narrow one column type, normalized JSON only.
            narrow_dir = _clone(contracts_dir, root / "narrow")
            description = _inject_narrow_column(narrow_dir)
            log(TAG, f"self-test injection 1: {description}")
            narrow_diffs, _ = collect_diffs(narrow_dir)
            if not _expect(
                label="inject-1 column narrowed",
                diffs=narrow_diffs,
                must_contain_kind="pg.column-type",
            ):
                failures += 1

            # Step 2 — drop one hnsw index, normalized raw_indexes only.
            drop_dir = _clone(contracts_dir, root / "drop-hnsw")
            description = _inject_drop_hnsw(drop_dir)
            log(TAG, f"self-test injection 2: {description}")
            drop_diffs, _ = collect_diffs(drop_dir)
            if not _expect(
                label="inject-2 hnsw dropped (hard count assertion)",
                diffs=drop_diffs,
                must_contain_kind="hnsw-count",
                must_name="pg.normalized.hnsw_indexes",
            ):
                failures += 1
            if not _expect(
                label="inject-2 hnsw dropped (name-set assertion)",
                diffs=drop_diffs,
                must_contain_kind="hnsw-name",
                must_name="ix_memory_vector_hnsw",
            ):
                failures += 1
            if not _expect(
                label="inject-2 hnsw dropped (ordinary index diff)",
                diffs=drop_diffs,
                must_contain_kind="pg.index",
                must_name="ix_memory_vector_hnsw",
            ):
                failures += 1
    except GateIOError as error:
        log(TAG, f"SELFTEST FAIL: {error}")
        return EXIT_SELFTEST

    if failures:
        log(TAG, f"SELFTEST VERDICT: FAIL ({failures} assertion(s) did not hold)")
        return EXIT_SELFTEST
    log(TAG, "SELFTEST VERDICT: PASS (both injections go red on the expected reason)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
