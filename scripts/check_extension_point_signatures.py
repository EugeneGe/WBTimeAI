"""T1-04 / E-3 — the extension-point signature gate: prove that the 9 TS
``interface`` declarations in ``@wbtime/contracts`` are **signature-identical**
to the legacy Python ``Protocol`` they claim to inherit.

What this gate is for
---------------------
Roadmap §3.1 **M-05 E-3** records the defect verbatim:

    ``audit/sink.py:5`` 的 ``AuditSink`` Protocol 与
    ``plugin.extension_points.audit_sink.AuditSink`` **仅靠 docstring 对齐**
    （0.2.0 ↔ 0.7.0，5 版漂移窗口）

"aligned by docstring" is not an assertion, it is a hope.  V0.1.0 moves the
interface declarations into ``@wbtime/contracts`` and V0.7.0 will build the
loader on top of them — so there is a five-version window in which the two
sides can drift apart while every existing gate stays green.  This gate closes
that window: it parses **both** sides and compares member names, parameter
counts, parameter types and return types, normalised.

For ``audit_sink`` it compares **three** faces (E-3's exact wording):
the TS interface, the plugin-side Protocol, and the core-side ``AuditSink``
in ``packages/audit/src/wbtime_ai_audit/sink.py``.  All three must be equal.

What it asserts
---------------
===========================  ==================================================
member-name parity            for each of the 9 points, the TS member-name set
                              equals the legacy Protocol member-name set
signature parity              for each of the 9 points, every member's
                              ``name(param types) -> return`` canonical string
                              is equal on both sides (audit_sink: three sides)
version parity                the TS ``*_VERSION`` constant equals the legacy
                              ``EXTENSION_POINT_VERSION`` string
domain-type guard             every domain type referenced by a signature is
                              declared in ``domain-refs.ts``; every declared
                              name is really imported by the legacy modules
                              (no phantom, no missing — both directions)
index guard                   ``extension-points/index.ts`` registers all 9
EMPTY ⇒ INVALID               zero points, zero members, zero domain types or
                              an absent legacy source is **never** green
                              (K-11: an empty comparison is vacuously true)
===========================  ==================================================

Three-state report (never folded into one boolean)
--------------------------------------------------
Every point reports exactly one of ``MATCH`` / ``DIFF`` / ``EMPTY`` /
``MISSING``, and the verdict line always carries the coverage
``n/9 points MATCH``.  A single healthy point can never hide a broken one.

The snapshot (second witness)
-----------------------------
``packages/contracts/signature-snapshot.json`` holds the signatures actually
extracted from the TS sources.  The gate compares it against a fresh
extraction, so **any later edit to an interface turns the gate red until the
snapshot is regenerated** (``--write-snapshot``).  It is a witness, not the
oracle: the oracle is the legacy source, which is compared independently.

Exit codes (§3.3)::

    0   PASS — every point MATCHes the legacy source and the snapshot agrees
    1   violation — DIFF / EMPTY / MISSING / missing legacy source / snapshot
        mismatch / undeclared or phantom domain type
    2   usage error
    9   --self-test failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
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
    "PACKAGE_DIR",
    "POINTS_DIR",
    "DOMAIN_REFS_FILE",
    "INDEX_FILE",
    "SNAPSHOT_FILE",
    "EXPECTED_POINTS",
    "AUDIT_CORE_FACE",
    "LEGACY_EXT_POINTS_DIR",
    "TYPE_MAP",
    "BUILTIN_TYPES",
    "PointReport",
    "GateResult",
    "canonical_type",
    "parse_ts_point",
    "parse_py_protocol",
    "collect",
    "evaluate",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "extpoints"

#: Package roots, relative to the repository root.
PACKAGE_DIR: Final[str] = "packages/contracts"
POINTS_DIR: Final[str] = "packages/contracts/src/extension-points"
DOMAIN_REFS_FILE: Final[str] = "packages/contracts/src/domain-refs.ts"
INDEX_FILE: Final[str] = "packages/contracts/src/extension-points/index.ts"
SNAPSHOT_FILE: Final[str] = "packages/contracts/signature-snapshot.json"

#: Where the legacy (read-only) extension-point Protocols live, relative to the
#: legacy root.  Read-only: this gate never writes there (G-1).
LEGACY_EXT_POINTS_DIR: Final[str] = "packages/plugin/src/wbtime_ai_plugin/extension_points"

#: E-3's core-side face: ``audit.Sink``.  Path relative to the legacy root.
AUDIT_CORE_FACE: Final[tuple[str, str]] = (
    "packages/audit/src/wbtime_ai_audit/sink.py",
    "AuditSink",
)

#: The 9 registered extension points: name → (legacy module file name,
#: legacy Protocol class name).  Adding or removing a point means editing this
#: table **and** the TS tree; a mismatch is a violation in both directions.
EXPECTED_POINTS: Final[dict[str, tuple[str, str]]] = {
    "auth_provider": ("auth_provider.py", "AuthProvider"),
    "policy_engine": ("policy_engine.py", "PolicyEngine"),
    "audit_sink": ("audit_sink.py", "AuditSink"),
    "secret_provider": ("secret_provider.py", "SecretProvider"),
    "model_gateway": ("model_gateway.py", "ModelGateway"),
    "model_provider": ("model_provider.py", "ModelProviderFactory"),
    "connector": ("connector.py", "Connector"),
    "ui_extension": ("ui_extension.py", "UIExtension"),
    "agent_executor": ("agent_executor.py", "AgentExecutor"),
}

#: Extra legacy faces compared in addition to the plugin-side Protocol:
#: point → ((relative path, class name), ...).  Only E-3's audit face today.
EXTRA_FACES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "audit_sink": (AUDIT_CORE_FACE,),
}

#: Legacy modules whose imported names form the allowed domain-type universe.
LEGACY_DOMAIN_MODULES: Final[tuple[str, ...]] = ("wbtime_ai_domain", "wbtime_ai_model")

#: Python ↔ TS type vocabulary.  Both sides are mapped through the same table so
#: the comparison is one canonical form, not two dialects guessed at each other.
TYPE_MAP: Final[dict[str, str]] = {
    "str": "string",
    "bool": "boolean",
    "int": "number",
    "float": "number",
    "bytes": "Uint8Array",
    "bytearray": "Uint8Array",
    "None": "void",
    "Any": "unknown",
    "object": "unknown",
    "Exception": "Error",
    "BaseException": "Error",
}

#: Generic wrappers normalised to the TS spelling.
GENERIC_MAP: Final[dict[str, str]] = {
    "list": "[]",
    "Sequence": "[]",
    "tuple": "[]",
    "dict": "Record",
    "Mapping": "Record",
    "Iterator": "IterableIterator",
}

#: Identifiers that are language furniture, not domain types.
BUILTIN_TYPES: Final[frozenset[str]] = frozenset(
    {
        "string", "boolean", "number", "void", "unknown", "null", "undefined",
        "Uint8Array", "Record", "Array", "ReadonlyArray", "Iterable",
        "IterableIterator", "Iterator", "Error", "Promise", "Date", "any",
        "never", "object", "symbol", "bigint",
    }
)

#: States a point report can carry.  Only ``MATCH`` passes (K-11).
STATE_MATCH: Final[str] = "MATCH"
STATE_DIFF: Final[str] = "DIFF"
STATE_EMPTY: Final[str] = "EMPTY"
STATE_MISSING: Final[str] = "MISSING"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split ``text`` on ``separator`` at bracket depth 0.

    Args:
        text: Text to split (no nested parentheses expected, generics use
            ``<>`` / ``[]`` which are depth-tracked as well).
        separator: Single-character separator.

    Returns:
        The stripped, non-empty parts.
    """
    parts: list[str] = []
    depth = 0
    buffer: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    closers = {value: key for key, value in pairs.items()}
    for char in text:
        if char in pairs:
            depth += 1
        elif char in closers:
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(buffer).strip())
            buffer.clear()
            continue
        buffer.append(char)
    parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def canonical_type(text: str) -> str:
    """Normalise one type expression from either language to one canonical form.

    Whitespace is removed; ``readonly`` / ``?`` decorations are dropped;
    primitives and generics are mapped through :data:`TYPE_MAP` and
    :data:`GENERIC_MAP` (``list[X]`` ⇒ ``X[]``, ``dict[K, V]`` ⇒
    ``Record<K,V>``, ``Iterator[X]`` ⇒ ``IterableIterator<X>`` ...).

    Args:
        text: A raw TS or Python annotation.

    Returns:
        The canonical string, e.g. ``"Record<string,unknown>"``.
    """
    value = str(text).strip()
    value = re.sub(r"\breadonly\s+", "", value)
    value = value.replace("?", "")
    value = re.sub(r"\s+", "", value)
    if not value:
        return ""

    # Trailing array suffix (TS side): `X[]` -> canonical(X) + "[]"
    if value.endswith("[]"):
        return canonical_type(value[:-2]) + "[]"

    # Union: normalise each member, keep order (both sides declare one order).
    if "|" in value:
        return "|".join(canonical_type(part) for part in _split_top_level(value, "|"))

    # Generic wrapper: `list[X]` / `tuple[X, ...]` / `Mapping[K, V]` ...
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\[(.*)\]$", value)
    if match is not None:
        name = match.group(1)
        inner = match.group(2)
        target = GENERIC_MAP.get(name)
        if target == "[]":
            elements = _split_top_level(inner, ",")
            if not elements:
                return "unknown[]"
            return canonical_type(elements[0]) + "[]"
        if target is not None:
            elements = _split_top_level(inner, ",")
            mapped = [canonical_type(element) for element in elements]
            return f"{target}<{','.join(mapped)}>"
        return f"{name}<{inner}>"

    # TS generic spelling: `Record<K, V>` / `IterableIterator<X>` — inner normalised.
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)<(.*)>$", value)
    if match is not None:
        name = match.group(1)
        elements = _split_top_level(match.group(2), ",")
        return f"{name}<{','.join(canonical_type(element) for element in elements)}>"

    return TYPE_MAP.get(value, value)


def canonical_signature(name: str, params: Sequence[str], returns: str) -> str:
    """Render one member signature in the canonical comparison form.

    Args:
        name: Member name.
        params: Parameter **type** strings (names dropped), in order.
        returns: Return type string (``""`` when absent ⇒ ``void``).

    Returns:
        ``"name(A,B):C"``.
    """
    head = f"{name}({','.join(canonical_type(param) for param in params)})"
    tail = canonical_type(returns) if returns else "void"
    return f"{head}:{tail}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Remove ``/** ... */``, ``/* ... */`` and ``// ...`` comments.

    Args:
        text: Source text.

    Returns:
        The text without comments (line structure preserved).
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", without_blocks)


def _interface_body(text: str, class_name: str) -> str:
    """Return the body of ``export interface <class_name> { ... }``.

    Args:
        text: TS source (comments already stripped).
        class_name: Interface name to look for.

    Returns:
        The body between the braces, or ``""`` when the interface is absent.
    """
    match = re.search(
        rf"export interface {re.escape(class_name)}\s*\{{(.*?)\n\}}",
        text,
        flags=re.S,
    )
    return match.group(1) if match is not None else ""


def parse_ts_members(text: str, class_name: str) -> dict[str, str]:
    """Extract the canonical signatures of one TS interface.

    Args:
        text: TS source (comments stripped by the caller).
        class_name: Interface name.

    Returns:
        ``{member_name: canonical_signature}`` in declaration order.
    """
    body = _interface_body(text, class_name)
    members: dict[str, str] = {}
    pattern = re.compile(r"(\w+)\s*\(([^()]*)\)\s*:\s*([^;{}]+);", flags=re.S)
    for match in pattern.finditer(body):
        name = match.group(1)
        raw_params = match.group(2).strip()
        params: list[str] = []
        if raw_params:
            for item in _split_top_level(raw_params, ","):
                if ":" in item:
                    params.append(item.rsplit(":", 1)[1].strip())
                else:
                    params.append(item.strip())
        members[name] = canonical_signature(name, params, match.group(3).strip())
    return members


def parse_ts_version(text: str) -> str | None:
    """Return the ``<point>/vN`` string declared by a TS point module.

    Args:
        text: TS source (comments stripped by the caller).

    Returns:
        The version string, or ``None`` when no ``*_VERSION`` constant exists.
    """
    match = re.search(r'export const [A-Z0-9_]+_VERSION\s*=\s*"([^"]+)"', text)
    return match.group(1) if match is not None else None


def parse_ts_domain_names(text: str) -> set[str]:
    """Return the ``DomainRef``-declared names of ``domain-refs.ts``.

    Args:
        text: TS source of ``domain-refs.ts`` (comments stripped by the caller).

    Returns:
        The declared domain-type names (``DomainRef`` itself excluded).
    """
    return set(re.findall(r"export interface (\w+) extends DomainRef<", text))


def _py_class_body(text: str, class_name: str) -> str:
    """Return the indented body of ``class <name>(Protocol):``.

    The body ends at the first column-0 statement, so a module-level helper
    defined **after** the Protocol (``register_provider_factory`` in
    ``model_provider.py``, ``_serialize`` in ``audit/sink.py``) can never be
    mistaken for a member.

    Args:
        text: Python source.
        class_name: Protocol class name.

    Returns:
        The body text, or ``""`` when the class is absent.
    """
    header = re.compile(rf"^class {re.escape(class_name)}\(Protocol\):")
    body: list[str] = []
    started = False
    for line in text.splitlines():
        if header.match(line):
            started = True
            continue
        if not started:
            continue
        if line.strip() == "" or line[:1] in (" ", "\t"):
            body.append(line)
            continue
        break
    return "\n".join(body)


def parse_py_protocol(text: str, class_name: str) -> dict[str, str]:
    """Extract the canonical signatures of one Python ``Protocol``.

    Args:
        text: Python source.
        class_name: Protocol class name.

    Returns:
        ``{member_name: canonical_signature}`` in declaration order.
    """
    body = _py_class_body(text, class_name)
    if not body.strip():
        return {}
    members: dict[str, str] = {}
    pattern = re.compile(r"def (\w+)\s*\((.*?)\)\s*(?:->\s*([^:]+))?\s*:", flags=re.S)
    for found in pattern.finditer(body):
        name = found.group(1)
        raw_params = found.group(2)
        params: list[str] = []
        for item in _split_top_level(raw_params, ","):
            item = item.strip()
            if item in ("self", "cls", ""):
                continue
            if ":" in item:
                params.append(item.rsplit(":", 1)[1].strip())
            else:
                params.append("unknown")
        returns = (found.group(3) or "").strip()
        members[name] = canonical_signature(name, params, returns)
    return members


def parse_py_version(text: str) -> str | None:
    """Return the legacy ``EXTENSION_POINT_VERSION`` string.

    Args:
        text: Python source of an extension-point module.

    Returns:
        The version string, or ``None``.
    """
    match = re.search(r'EXTENSION_POINT_VERSION\s*:\s*str\s*=\s*"([^"]+)"', text)
    return match.group(1) if match is not None else None


def parse_py_imports(text: str, modules: Sequence[str]) -> set[str]:
    """Return the names imported from ``modules`` (single-line or parenthesised).

    Args:
        text: Python source.
        modules: Module names such as ``wbtime_ai_domain``.

    Returns:
        The imported identifiers (aliases resolved to the local name).
    """
    names: set[str] = set()
    for module in modules:
        pattern = re.compile(
            rf"^from {re.escape(module)} import\s*\((.*?)\)|^from {re.escape(module)} import\s+([^\n(]+)",
            flags=re.S | re.M,
        )
        for match in pattern.finditer(text):
            block = match.group(1) if match.group(1) is not None else match.group(2)
            for item in _split_top_level(block.replace("\n", " "), ","):
                item = item.strip()
                if not item:
                    continue
                names.add(item.split(" as ")[-1].strip())
    return names


def referenced_domain_names(members: dict[str, str]) -> set[str]:
    """Return the domain-type names a set of canonical signatures refers to.

    Args:
        members: Canonical signatures (values of :func:`parse_ts_members`).

    Returns:
        Identifiers that look like domain types (capitalised, not builtin).
    """
    names: set[str] = set()
    for signature in members.values():
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", signature):
            if token[0].isupper() and token not in BUILTIN_TYPES:
                names.add(token)
    return names


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@dataclass
class PointReport:
    """One extension point's three-state result.

    Attributes:
        point: Extension-point key.
        state: ``MATCH`` / ``DIFF`` / ``EMPTY`` / ``MISSING``.
        ts_members: Members extracted from the TS interface.
        faces: ``{face_label: members}`` for every legacy face compared.
        version_ts: Version declared by the TS module.
        version_legacy: Version declared by the legacy module.
        problems: Human readable reasons (empty when ``MATCH``).
    """

    point: str
    state: str
    ts_members: dict[str, str] = field(default_factory=dict)
    ts_present: bool = False
    faces: dict[str, dict[str, str]] = field(default_factory=dict)
    version_ts: str | None = None
    version_legacy: str | None = None
    problems: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the per-point evidence line.

        Returns:
            e.g. ``point audit_sink  MATCH  ts=3 plugin=3 audit=3``.
        """
        counts = " ".join(f"{label}={len(members)}" for label, members in self.faces.items())
        return f"point {self.point:<16} {self.state:<8} ts={len(self.ts_members)} {counts}".rstrip()

    def to_dict(self) -> dict[str, object]:
        """Return the record as a plain dict (for ``--json`` output)."""
        return {
            "point": self.point,
            "state": self.state,
            "ts_members": self.ts_members,
            "faces": self.faces,
            "version_ts": self.version_ts,
            "version_legacy": self.version_legacy,
            "problems": list(self.problems),
        }


@dataclass
class GateResult:
    """Everything the gate measured, before any verdict is folded.

    Attributes:
        points: One report per registered point (in :data:`EXPECTED_POINTS` order).
        extra_points: TS files that are **not** registered (unexpected).
        declared_domain: Names declared in ``domain-refs.ts``.
        referenced_domain: Domain names referenced by the 9 interfaces.
        legacy_domain: Names the legacy modules import from the domain modules.
        index_registered: How many of the 9 points ``index.ts`` registers.
        snapshot_state: ``MATCH`` / ``DIFF`` / ``ABSENT``.
        snapshot_digest: sha256 of the canonical snapshot payload.
        source_state: ``OK`` / ``ABSENT`` for the legacy source root.
        source_path: Legacy root used.
    """

    points: list[PointReport] = field(default_factory=list)
    ts_modules_present: int = 0
    extra_points: list[str] = field(default_factory=list)
    declared_domain: set[str] = field(default_factory=set)
    referenced_domain: set[str] = field(default_factory=set)
    legacy_domain: set[str] = field(default_factory=set)
    index_registered: int = 0
    snapshot_state: str = "ABSENT"
    snapshot_digest: str = ""
    source_state: str = "ABSENT"
    source_path: str = ""


def _read(path: Path) -> str | None:
    """Read a UTF-8 file, returning ``None`` when it is missing.

    Args:
        path: File to read.

    Returns:
        The text, or ``None``.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def collect(repo_root: Path, legacy_root: Path) -> GateResult:
    """Measure every fact the verdict needs.

    Args:
        repo_root: Repository root.
        legacy_root: Read-only legacy root.

    Returns:
        The :class:`GateResult`; nothing here is judged yet.
    """
    result = GateResult(source_path=legacy_root.as_posix())
    legacy_points_dir = legacy_root / Path(*LEGACY_EXT_POINTS_DIR.split("/"))
    result.source_state = "OK" if legacy_points_dir.is_dir() else "ABSENT"

    points_dir = repo_root / Path(*POINTS_DIR.split("/"))
    present = sorted(path.stem for path in points_dir.glob("*.ts")) if points_dir.is_dir() else []
    present = [name for name in present if name != "index"]
    result.ts_modules_present = len(present)

    # --- per point ---------------------------------------------------------
    for point, (module_file, class_name) in EXPECTED_POINTS.items():
        report = PointReport(point=point, state=STATE_MISSING)
        ts_path = points_dir / f"{point}.ts"
        ts_text = _read(ts_path)
        if ts_text is not None:
            stripped = _strip_comments(ts_text)
            report.ts_present = True
            report.ts_members = parse_ts_members(stripped, class_name)
            report.version_ts = parse_ts_version(stripped)

        legacy_path = legacy_points_dir / module_file
        legacy_text = _read(legacy_path)
        if legacy_text is not None:
            report.faces["plugin"] = parse_py_protocol(legacy_text, class_name)
            report.version_legacy = parse_py_version(legacy_text)

        for relative, face_class in EXTRA_FACES.get(point, ()):
            face_path = legacy_root / Path(*relative.split("/"))
            face_text = _read(face_path)
            report.faces[face_label(relative)] = (
                parse_py_protocol(face_text, face_class) if face_text is not None else {}
            )
        result.points.append(report)

    result.extra_points = [name for name in present if name not in EXPECTED_POINTS]

    # --- domain types ------------------------------------------------------
    domain_text = _read(repo_root / Path(*DOMAIN_REFS_FILE.split("/")))
    if domain_text is not None:
        result.declared_domain = parse_ts_domain_names(_strip_comments(domain_text))
    result.referenced_domain = set()
    for report in result.points:
        result.referenced_domain |= referenced_domain_names(report.ts_members)
    if legacy_points_dir.is_dir():
        for path in sorted(legacy_points_dir.glob("*.py")):
            text = _read(path)
            if text is not None:
                result.legacy_domain |= parse_py_imports(text, LEGACY_DOMAIN_MODULES)

    # --- index registration ------------------------------------------------
    index_text = _read(repo_root / Path(*INDEX_FILE.split("/")))
    if index_text is not None:
        result.index_registered = sum(
            1 for point in EXPECTED_POINTS if f"readonly {point}:" in index_text
        )
    return result


def face_label(relative: str) -> str:
    """Return a short ASCII label for a legacy face path.

    Args:
        relative: POSIX path relative to the legacy root.

    Returns:
        e.g. ``"audit"`` for ``packages/audit/src/wbtime_ai_audit/sink.py``.
    """
    stem = Path(relative).stem
    return "audit" if "audit" in relative else stem


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------


def _judge_point(report: PointReport) -> None:
    """Set ``report.state`` and fill ``report.problems`` (three-state)."""
    if not report.ts_present:
        report.state = STATE_MISSING
        report.problems.append("TS module missing")
        return

    ts_names = set(report.ts_members)
    if not ts_names:
        report.state = STATE_EMPTY
        report.problems.append("TS interface has 0 members (EMPTY ⇒ never pass, K-11)")
        return

    problems: list[str] = []
    if report.version_ts is None:
        problems.append("TS module declares no *_VERSION constant")
    elif report.version_legacy is None:
        problems.append("legacy module declares no EXTENSION_POINT_VERSION")
    elif report.version_ts != report.version_legacy:
        problems.append(f"version differs: ts={report.version_ts} legacy={report.version_legacy}")

    for label, members in report.faces.items():
        if not members:
            problems.append(f"{label}: legacy Protocol absent or has 0 members (EMPTY ⇒ red)")
            continue
        legacy_names = set(members)
        ts_only = sorted(ts_names - legacy_names)
        ts_missing = sorted(legacy_names - ts_names)
        if ts_only:
            problems.append(f"{label}: member(s) only in TS {ts_only}")
        if ts_missing:
            problems.append(f"{label}: member(s) missing in TS {ts_missing}")
        for name in sorted(ts_names & legacy_names):
            if report.ts_members[name] != members[name]:
                problems.append(
                    f"{label}: {name} signature differs "
                    f"(ts={report.ts_members[name]} legacy={members[name]})"
                )

    report.problems.extend(problems)
    report.state = STATE_DIFF if problems else STATE_MATCH


def _snapshot_payload(result: GateResult) -> dict[str, object]:
    """Build the snapshot payload from the **TS** side only.

    Args:
        result: Measured facts.

    Returns:
        A JSON-ready dict (no timestamp: the digest must be stable).
    """
    return {
        "contract": "extension-point-signatures/v1",
        "point_count": len(result.points),
        "points": {
            report.point: {
                "version": report.version_ts,
                "interface": EXPECTED_POINTS[report.point][1],
                "members": dict(sorted(report.ts_members.items())),
            }
            for report in result.points
        },
    }


def _snapshot_digest(payload: dict[str, object]) -> str:
    """Return the sha256 of the canonical snapshot payload.

    Args:
        payload: Output of :func:`_snapshot_payload`.

    Returns:
        The hex digest.
    """
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def evaluate(result: GateResult, snapshot_path: Path) -> list[str]:
    """Judge every measured fact and return the violation lines.

    Args:
        result: Measured facts (mutated: point states are filled in).
        snapshot_path: Snapshot file location.

    Returns:
        Violation lines; empty means PASS.
    """
    violations: list[str] = []

    if not EXPECTED_POINTS:
        violations.append("registry is empty: 0 registered points ⇒ INVALID(EMPTY), never PASS")
    if not result.points:
        violations.append("0 point report(s) produced ⇒ INVALID(EMPTY), never PASS")
    if result.ts_modules_present == 0:
        violations.append(
            f"0 TS point module(s) under {POINTS_DIR} ⇒ INVALID(EMPTY), never PASS (K-11)"
        )

    for report in result.points:
        _judge_point(report)
        if report.state != STATE_MATCH:
            for problem in report.problems:
                violations.append(f"{report.point}: {problem}")

    for name in result.extra_points:
        violations.append(f"{name}: TS module present but not registered in EXPECTED_POINTS")

    if result.source_state != "OK":
        violations.append(
            f"legacy source absent: {result.source_path} ⇒ cannot compare; "
            "an uncompared contract is INVALID, never PASS"
        )

    # --- domain types (both directions, empty ⇒ red) ----------------------
    if not result.declared_domain:
        violations.append("domain-refs.ts declares 0 type(s) ⇒ INVALID(EMPTY)")
    if not result.referenced_domain:
        violations.append("the 9 interfaces reference 0 domain type(s) ⇒ INVALID(EMPTY)")
    if not result.legacy_domain:
        violations.append("legacy modules import 0 domain type(s) ⇒ INVALID(EMPTY)")
    undeclared = sorted(result.referenced_domain - result.declared_domain)
    phantom = sorted(result.declared_domain - result.legacy_domain)
    for name in undeclared:
        violations.append(f"domain type {name}: referenced by a signature but not declared")
    for name in phantom:
        violations.append(
            f"domain type {name}: declared but never imported by the legacy extension points"
        )

    if result.index_registered != len(EXPECTED_POINTS):
        violations.append(
            f"index.ts registers {result.index_registered}/{len(EXPECTED_POINTS)} point(s)"
        )

    # --- snapshot (second witness) ----------------------------------------
    payload = _snapshot_payload(result)
    result.snapshot_digest = _snapshot_digest(payload)
    raw = _read(snapshot_path)
    if raw is None:
        result.snapshot_state = "ABSENT"
        violations.append(f"snapshot absent: {snapshot_path.as_posix()} (write it with --write-snapshot)")
    else:
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError as error:
            result.snapshot_state = "DIFF"
            violations.append(f"snapshot is not valid JSON: {error}")
            return violations
        stored_points = stored.get("points") if isinstance(stored, dict) else None
        if not isinstance(stored_points, dict) or not stored_points:
            result.snapshot_state = "EMPTY"
            violations.append("snapshot has no points ⇒ INVALID(EMPTY)")
        elif stored_points != payload["points"]:
            result.snapshot_state = "DIFF"
            for point in sorted(set(stored_points) | set(payload["points"])):
                left = stored_points.get(point)
                right = payload["points"].get(point) if isinstance(payload["points"], dict) else None
                if left != right:
                    violations.append(f"snapshot differs for {point} (regenerate with --write-snapshot)")
        else:
            result.snapshot_state = "MATCH"
    return violations



# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render(paths: _gate_io.GatePaths, result: GateResult, violations: Sequence[str]) -> None:
    """Print the whole evidence block (one line per fact, K-7).

    Args:
        paths: Resolved roots.
        result: Measured facts.
        violations: Folded violations.
    """
    _gate_io.log(TAG, f"repo={paths.repo_root.as_posix()} at {_gate_io.utc_now_iso()}")
    _gate_io.log(TAG, f"source legacy={result.source_path} state={result.source_state}")
    for report in result.points:
        _gate_io.log(TAG, report.render())
        for problem in report.problems:
            _gate_io.log(TAG, f"  {report.point}: {problem}")
    _gate_io.log(
        TAG,
        f"domain declared={len(result.declared_domain)} referenced={len(result.referenced_domain)} "
        f"legacy_imported={len(result.legacy_domain)}",
    )
    _gate_io.log(TAG, f"index.ts registered={result.index_registered}/{len(EXPECTED_POINTS)}")
    _gate_io.log(
        TAG,
        f"snapshot {SNAPSHOT_FILE} {result.snapshot_state} sha256={result.snapshot_digest[:16]}",
    )
    for violation in violations:
        _gate_io.log(TAG, f"VIOLATION: {violation}")

    matched = sum(1 for report in result.points if report.state == STATE_MATCH)
    if violations:
        _gate_io.log(TAG, f"VERDICT: INVALID ({len(violations)} violation(s))")
    else:
        _gate_io.log(TAG, "VERDICT: PASS (every point is compared against the legacy Protocol)")
    # The last line is always the coverage line: "PASS" alone is forbidden.
    _gate_io.log(TAG, f"coverage: {matched}/{len(EXPECTED_POINTS)} points MATCH the legacy source")


# ---------------------------------------------------------------------------
# Self-test — injections on a throw-away clone
# ---------------------------------------------------------------------------


def _prepare_clone(repo_root: Path, legacy_root: Path) -> Path:
    """Build a throw-away clone holding only what the gate needs.

    Args:
        repo_root: Real repository root (read-only source).
        legacy_root: Real legacy root (read-only source).

    Returns:
        The clone root.

    Raises:
        RuntimeError: The contracts package or the legacy extension points are
            missing, so nothing can be self-tested.
    """
    scratch = Path(tempfile.mkdtemp(prefix="wbtime-xp-"))
    clone = scratch / "repo"
    clone.mkdir(parents=True, exist_ok=True)

    package = repo_root / Path(*PACKAGE_DIR.split("/"))
    if not package.is_dir():
        raise RuntimeError(f"cannot self-test: {package.as_posix()} is missing")
    shutil.copytree(
        package,
        clone / Path(*PACKAGE_DIR.split("/")),
        ignore=shutil.ignore_patterns("node_modules", "__pycache__", "dist", "*.tsbuildinfo"),
    )

    scripts = clone / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "scripts" / "check_extension_point_signatures.py", scripts)
    shutil.copy2(repo_root / "scripts" / "_gate_io.py", scripts)

    legacy_target = clone / "_old"
    source_points = legacy_root / Path(*LEGACY_EXT_POINTS_DIR.split("/"))
    if not source_points.is_dir():
        raise RuntimeError(f"cannot self-test: {source_points.as_posix()} is missing")
    destination = legacy_target / Path(*LEGACY_EXT_POINTS_DIR.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_points, destination)

    face_relative = AUDIT_CORE_FACE[0]
    face_source = legacy_root / Path(*face_relative.split("/"))
    if face_source.is_file():
        face_target = legacy_target / Path(*face_relative.split("/"))
        face_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(face_source, face_target)
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
        str(clone / "scripts" / "check_extension_point_signatures.py"),
        "--repo-root",
        str(clone),
        "--legacy-root",
        str(clone / "_old"),
        *extra,
    ]
    completed = subprocess.run(
        command, cwd=str(clone), capture_output=True, text=True, timeout=180, check=False
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _self_test(repo_root: Path, legacy_root: Path) -> int:
    """Run the injections that prove the gate moves in both directions.

    The injections:

    1. untouched clone -> PASS;
    2. rename one ``audit_sink`` member (``flush`` → ``flushAll``) -> red DIFF;
    3. drop one ``ui_extension`` member -> red DIFF (missing member);
    4. empty the ``secret_provider`` interface -> red EMPTY (never green);
    5. delete ``connector.ts`` -> red MISSING;
    6. delete **all** point modules -> red EMPTY (0 points, K-11);
    7. tamper with the snapshot -> red;
    8. point ``--legacy-root`` at an empty directory -> red (uncompared ≠ pass).

    Args:
        repo_root: Real repository root.
        legacy_root: Real legacy root.

    Returns:
        ``0`` when every injection behaved, ``9`` otherwise.
    """
    checks: list[tuple[str, bool, str]] = []

    def record(label: str, ok: bool, detail: str) -> None:
        checks.append((label, ok, detail))
        _gate_io.log(TAG, f"  {'PASS' if ok else 'FAIL'}  {label} :: {detail}")

    # 1 — control: the untouched clone must be PASS -------------------------
    clone = _prepare_clone(repo_root, legacy_root)
    code, output = _run_gate(clone)
    record(
        "control clone is PASS",
        code == 0 and "coverage: 9/9" in output,
        f"exit={code} last={output.strip().splitlines()[-1] if output.strip() else ''}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 2 — rename an audit_sink member -> red (E-3 face) ---------------------
    clone = _prepare_clone(repo_root, legacy_root)
    target = clone / Path(*POINTS_DIR.split("/")) / "audit_sink.ts"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("flush(): void;", "flushAll(): void;", 1), encoding="utf-8")
    code, output = _run_gate(clone)
    record(
        "rename audit_sink.flush -> red (audit+plugin faces)",
        code == 1 and "DIFF" in output and "audit" in output,
        f"exit={code}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 3 — drop one ui_extension member -> red -------------------------------
    clone = _prepare_clone(repo_root, legacy_root)
    target = clone / Path(*POINTS_DIR.split("/")) / "ui_extension.ts"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("  assets_base_url(): string;\n", "", 1), encoding="utf-8")
    code, output = _run_gate(clone)
    record("drop a ui_extension member -> red", code == 1 and "missing in TS" in output, f"exit={code}")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 4 — empty the secret_provider interface -> EMPTY, never green ---------
    clone = _prepare_clone(repo_root, legacy_root)
    target = clone / Path(*POINTS_DIR.split("/")) / "secret_provider.ts"
    text = target.read_text(encoding="utf-8")
    emptied = re.sub(r"export interface SecretProvider \{.*?\n\}", "export interface SecretProvider {\n}", text, flags=re.S)
    target.write_text(emptied, encoding="utf-8")
    code, output = _run_gate(clone)
    record("empty interface -> EMPTY red", code == 1 and "EMPTY" in output, f"exit={code}")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 5 — delete one point module -> MISSING --------------------------------
    clone = _prepare_clone(repo_root, legacy_root)
    (clone / Path(*POINTS_DIR.split("/")) / "connector.ts").unlink()
    code, output = _run_gate(clone)
    record("delete connector.ts -> red", code == 1 and "MISSING" in output, f"exit={code}")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 6 — delete every point module -> 0 points, K-11 -----------------------
    clone = _prepare_clone(repo_root, legacy_root)
    for path in (clone / Path(*POINTS_DIR.split("/"))).glob("*.ts"):
        if path.stem != "index":
            path.unlink()
    code, output = _run_gate(clone)
    record("0 point modules -> EMPTY red (K-11)", code == 1 and "EMPTY" in output, f"exit={code}")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 7 — tamper with the snapshot -> red -----------------------------------
    clone = _prepare_clone(repo_root, legacy_root)
    snapshot = clone / Path(*SNAPSHOT_FILE.split("/"))
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    document["points"]["audit_sink"]["members"]["write"] = "write(AuditEvent):boolean"
    snapshot.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    code, output = _run_gate(clone)
    record("tampered snapshot -> red", code == 1 and "snapshot differs" in output, f"exit={code}")
    shutil.rmtree(clone.parent, ignore_errors=True)

    # 8 — legacy source absent -> red (never a vacuous pass) ----------------
    clone = _prepare_clone(repo_root, legacy_root)
    empty_legacy = clone.parent / "empty-legacy"
    empty_legacy.mkdir(parents=True, exist_ok=True)
    code, output = _run_gate(clone, "--legacy-root", str(empty_legacy))
    record(
        "legacy source absent -> red",
        code == 1 and "legacy source absent" in output,
        f"exit={code}",
    )
    shutil.rmtree(clone.parent, ignore_errors=True)

    failures = [label for label, ok, _ in checks if not ok]
    _gate_io.log(TAG, f"self-test: {len(checks) - len(failures)}/{len(checks)} passed")
    if failures:
        for label in failures:
            _gate_io.log(TAG, f"  failed: {label}")
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
        prog="check_extension_point_signatures.py",
        description=(
            "E-3: assert the 9 @wbtime/contracts extension-point interfaces are "
            "signature-identical to the legacy Python Protocols (three faces for "
            "audit_sink), with an EMPTY->INVALID floor and a snapshot witness."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=None, metavar="DIR", help="repository root")
    parser.add_argument(
        "--legacy-root", type=Path, default=None, metavar="DIR", help="read-only legacy repository root"
    )
    parser.add_argument(
        "--write-snapshot",
        action="store_true",
        help="regenerate packages/contracts/signature-snapshot.json from the TS sources",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--self-test", action="store_true", help="run the injections (exit 9 on failure)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``1`` / ``2`` / ``9`` (§3.3).
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

    paths = _gate_io.GatePaths.resolve(
        repo_root=repo_root,
        legacy_root=arguments.legacy_root,
    )
    if arguments.self_test:
        try:
            return _self_test(paths.repo_root, paths.legacy_root)
        except (RuntimeError, OSError) as error:
            _gate_io.log(TAG, f"SELFTEST VERDICT: FAIL ({error})")
            return _gate_io.EXIT_SELFTEST

    result = collect(paths.repo_root, paths.legacy_root)
    snapshot_path = paths.repo_root / Path(*SNAPSHOT_FILE.split("/"))

    if arguments.write_snapshot:
        payload = _snapshot_payload(result)
        payload["generated_at"] = _gate_io.utc_now_iso()
        payload["sha256"] = _snapshot_digest(_snapshot_payload(result))
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _gate_io.log(
            TAG,
            f"snapshot written: {snapshot_path.as_posix()} "
            f"points={payload['point_count']} sha256={payload['sha256'][:16]}",
        )

    violations = evaluate(result, snapshot_path)

    if arguments.json:
        print(
            json.dumps(
                {
                    "generated_at": _gate_io.utc_now_iso(),
                    "repo_root": paths.repo_root.as_posix(),
                    "legacy_root": paths.legacy_root.as_posix(),
                    "source_state": result.source_state,
                    "points": [report.to_dict() for report in result.points],
                    "extra_points": result.extra_points,
                    "domain": {
                        "declared": sorted(result.declared_domain),
                        "referenced": sorted(result.referenced_domain),
                        "legacy_imported": sorted(result.legacy_domain),
                    },
                    "index_registered": result.index_registered,
                    "snapshot": {"state": result.snapshot_state, "sha256": result.snapshot_digest},
                    "violations": list(violations),
                    "coverage": {
                        "matched": sum(1 for report in result.points if report.state == STATE_MATCH),
                        "total": len(EXPECTED_POINTS),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    render(paths, result, violations)
    if violations:
        return _gate_io.EXIT_VIOLATION
    return _gate_io.EXIT_OK


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
