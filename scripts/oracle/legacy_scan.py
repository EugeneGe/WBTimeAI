"""只读外部 oracle：静态扫描 ``_old`` 源码树，独立重算 F1–F4（V0.0.2 · T03）。

设计依据：``docs/V1.0/V0.0.2-oracle自证与假绿反例/02-施工/README.md`` §1.3 / §1.4 / §5-T03。

四个面（**集合级**，不是只比计数）：

===== ============================================ ==============================
面    从 ``_old`` 重算什么                           与 ``contracts/`` 的比对粒度
===== ============================================ ==============================
F1    ``ast`` 扫 ``routers/**`` 的 ``APIRouter`` 前缀 OpenAPI ``paths`` / ``operations``
      + 方法装饰器 + ``include_router`` 链          集合全等
F2    Alembic 迁移**链序累积**最终态（表 / 列 /      ``schema.v0018.pg.normalized.json``
      索引名 / raw hnsw）                            表名集合、``(表, 列)`` 集合、索引名集合
F3    ``sse/encoder.py::SSE_CHANNEL_BY_DOMAIN_TYPE`` ``sse/channels.json`` 的 channel 值集合
      （``ast.literal_eval``，**不 import**）
F4    ``error_codes.py::ErrorCode`` 枚举成员名       ``errors.json`` 的 ``codes`` 键集合
===== ============================================ ==============================

**独立性**（本模块存在的全部理由）：

* 不 import ``scripts/extract-from-py/**``（``export_*`` / ``ddl.exporter``）；
* 不 import ``scripts/compare_openapi.py``（它属被验门禁，复用会掩盖解析器 bug）；
* 不 import ``_old`` 的任何业务包（那会写 ``__pycache__`` 并引入依赖）。

**只读纪律**（施工 §1.5 / §7-K-10）：

* ``sys.dont_write_bytecode = True``（模块导入即生效，配合 ``python -B``）；
* 只读扫描 + 扫前扫后快照比对，被写路径非空即视为违规（**绝不静默**）；
* ``cwd`` 不由本模块改动（调用方负责不把 cwd 留在 ``_old``）。

**解析失败 ⇒ ``OracleUnavailable``，不猜**（施工 §5-T03 风险条款）。

命令行（自检用）::

    python -B scripts/oracle/legacy_scan.py --legacy-root D:/WBT/WBTimeAI_old
    python -B scripts/oracle/legacy_scan.py --assert-independent
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Iterator, Sequence

# 只读纪律：本模块及其调用方全程不落 .pyc（G-4 / 施工 §7 共享知识）。
sys.dont_write_bytecode = True

#: HTTP 方法集合（OpenAPI ``operations`` 的判定词表）。
HTTP_METHODS: Final[tuple[str, ...]] = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
)

#: 迁移源码里被跳过的 ``op.*`` 动作——它们不改变「表 / 列 / 索引名」三集合。
IGNORED_OP_ACTIONS: Final[tuple[str, ...]] = (
    "bulk_insert",
    "create_check_constraint",
    "create_foreign_key",
    "create_primary_key",
    "create_table_comment",
    "create_unique_constraint",
    "drop_constraint",
    "drop_table_comment",
    "alter_column",
    "execute_script",
)

#: 只读快照的扫描范围（相对 ``legacy_root``）。**有意不扫整棵树**：
#: ``_old`` 含 ``node_modules``（3 万文件级），全树扫描会把每次运行拖到分钟级，
#: 而真正的写入风险只落在下面这几个被读取的目录。
READONLY_SCOPE_DIRS: Final[tuple[str, ...]] = (
    "migrations",
    "apps/api/src/wbtime_ai_api",
    "packages/core/src/wbtime_ai_core",
)

#: 禁止出现在 import 图里的模块前缀（独立性判据）。
FORBIDDEN_IMPORT_PREFIXES: Final[tuple[str, ...]] = (
    "extract_from_py",
    "extract-from-py",
    "ddl.exporter",
    "compare_openapi",
)

#: 禁止出现在 import 图里的模块名片段（``export_*`` 一族）。
FORBIDDEN_IMPORT_FRAGMENTS: Final[tuple[str, ...]] = ("export_",)

_CREATE_INDEX_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)\s+ON\s+(?P<table>\w+)"
    r"(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_ADD_COLUMN_RE: Final[re.Pattern[str]] = re.compile(
    r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>\w+)\s+ADD\s+(?:COLUMN\s+)?(?P<column>\w+)",
    re.IGNORECASE,
)
_DROP_INDEX_RE: Final[re.Pattern[str]] = re.compile(
    r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?P<name>\w+)", re.IGNORECASE
)
_CREATE_TABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>\w+)", re.IGNORECASE
)
_HNSW_RE: Final[re.Pattern[str]] = re.compile(r"USING\s+hnsw\b", re.IGNORECASE)
_OPERATOR_CLASS_RE: Final[re.Pattern[str]] = re.compile(r"\(\s*\w+\s+(?P<opclass>\w+)\s*\)")


class OracleUnavailable(RuntimeError):
    """Raised when an external oracle face cannot be recomputed.

    This is **never** translated into a pass: callers map it to
    ``EXIT_ORACLE_UNAVAILABLE`` (21) per the exit-code table (施工 §3.3).

    Attributes:
        reason: Human-readable, single-line reason (ASCII-preferring).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReadonlyViolation(RuntimeError):
    """Raised when the scan observed a write inside the legacy tree.

    Kept separate from :class:`OracleUnavailable` so the caller can print a
    louder ``READONLY-VIOLATION`` banner instead of a plain ``DEGRADED``.
    """

    def __init__(self, paths: Sequence[str]) -> None:
        super().__init__("legacy tree modified: " + ", ".join(paths))
        self.paths: tuple[str, ...] = tuple(paths)


# ---------------------------------------------------------------------------
# Facts（F1–F4）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawIndexFact:
    """One raw (dialect-only) DDL index recomputed from ``_old``.

    Attributes:
        name: Index name as written in the migration ``CREATE INDEX`` text.
        table: Target table name.
        method: Access method (``hnsw`` / ``btree`` / ...).
        operator_class: Operator class when present (``vector_cosine_ops``).
        sql: Normalized one-line SQL text.
    """

    name: str
    table: str
    method: str
    operator_class: str | None
    sql: str

    def to_dict(self) -> dict[str, Any]:
        """Return the fact as a JSON-ready dict."""
        return {
            "name": self.name,
            "table": self.table,
            "method": self.method,
            "operator_class": self.operator_class,
            "sql": self.sql,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawIndexFact:
        """Rebuild a fact from :meth:`to_dict` output."""
        return cls(
            name=str(data["name"]),
            table=str(data["table"]),
            method=str(data["method"]),
            operator_class=(
                None if data.get("operator_class") is None else str(data["operator_class"])
            ),
            sql=str(data["sql"]),
        )


@dataclass(frozen=True)
class LegacyFacts:
    """The external truth recomputed from the legacy tree (F1–F4).

    Every tuple is **sorted** so two scans of the same tree are comparable
    byte-for-byte (snapshot determinism, 施工 §1.3 O-C 档).

    Attributes:
        legacy_root: Absolute path of the scanned legacy tree.
        scanned_at: UTC timestamp ``YYYY-MM-DDTHH:MM:SSZ``.
        openapi_paths: F1 — every concrete path string.
        openapi_operations: F1 — ``"METHOD /path"`` strings.
        ddl_tables: F2 — table names at migration head.
        ddl_columns: F2 — ``(table, column)`` pairs at migration head.
        ddl_indexes: F2 — metadata index names (``op.create_index``).
        ddl_raw_indexes: F2 — raw DDL indexes (``CREATE INDEX ... USING hnsw``).
        sse_channels: F3 — SSE channel names.
        error_codes: F4 — ``ErrorCode`` member names.
        notes: Per-face honesty notes (what was skipped and why).
        chain: Alembic revision chain actually walked (``0001 ... 0018``).
    """

    legacy_root: str
    scanned_at: str
    openapi_paths: tuple[str, ...]
    openapi_operations: tuple[str, ...]
    ddl_tables: tuple[str, ...]
    ddl_columns: tuple[tuple[str, str], ...]
    ddl_indexes: tuple[str, ...]
    ddl_raw_indexes: tuple[RawIndexFact, ...]
    sse_channels: tuple[str, ...]
    error_codes: tuple[str, ...]
    notes: tuple[str, ...] = ()
    chain: tuple[str, ...] = ()

    # -- derived properties -------------------------------------------------

    @property
    def ddl_index_objects_total(self) -> int:
        """F2 — ``metadata_indexes + raw_indexes`` (contracts ``index_objects_total``)."""
        return len(self.ddl_indexes) + len(self.ddl_raw_indexes)

    @property
    def ddl_hnsw_names(self) -> tuple[str, ...]:
        """F2 — names of raw indexes whose access method is ``hnsw``."""
        return tuple(sorted(f.name for f in self.ddl_raw_indexes if f.method == "hnsw"))

    def to_dict(self) -> dict[str, Any]:
        """Return the facts as a JSON-ready dict (snapshot payload)."""
        return {
            "legacy_root": self.legacy_root,
            "scanned_at": self.scanned_at,
            "chain": list(self.chain),
            "openapi": {
                "paths": list(self.openapi_paths),
                "operations": list(self.openapi_operations),
            },
            "ddl": {
                "tables": list(self.ddl_tables),
                "columns": [[table, column] for table, column in self.ddl_columns],
                "indexes": list(self.ddl_indexes),
                "raw_indexes": [fact.to_dict() for fact in self.ddl_raw_indexes],
            },
            "sse": {"channels": list(self.sse_channels)},
            "errors": {"codes": list(self.error_codes)},
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegacyFacts:
        """Rebuild facts from :meth:`to_dict` output (snapshot / O-C 档).

        Args:
            data: Mapping produced by :meth:`to_dict`.

        Returns:
            Reconstructed :class:`LegacyFacts`.

        Raises:
            OracleUnavailable: If the payload is structurally incomplete —
                a snapshot that cannot be read is *unavailable*, not empty.
        """
        try:
            openapi = data["openapi"]
            ddl = data["ddl"]
            return cls(
                legacy_root=str(data.get("legacy_root", "<snapshot>")),
                scanned_at=str(data.get("scanned_at", "<unknown>")),
                chain=tuple(str(x) for x in data.get("chain", [])),
                openapi_paths=tuple(sorted(str(x) for x in openapi["paths"])),
                openapi_operations=tuple(sorted(str(x) for x in openapi["operations"])),
                ddl_tables=tuple(sorted(str(x) for x in ddl["tables"])),
                ddl_columns=tuple(
                    sorted((str(pair[0]), str(pair[1])) for pair in ddl["columns"])
                ),
                ddl_indexes=tuple(sorted(str(x) for x in ddl["indexes"])),
                ddl_raw_indexes=tuple(
                    sorted(
                        (RawIndexFact.from_dict(item) for item in ddl["raw_indexes"]),
                        key=lambda fact: fact.name,
                    )
                ),
                sse_channels=tuple(sorted(str(x) for x in data["sse"]["channels"])),
                error_codes=tuple(sorted(str(x) for x in data["errors"]["codes"])),
                notes=tuple(str(x) for x in data.get("notes", [])),
            )
        except (KeyError, TypeError, IndexError) as exc:
            raise OracleUnavailable(f"snapshot payload incomplete: {exc!r}") from exc


# ---------------------------------------------------------------------------
# 只读快照（扫前 / 扫后比对，施工 §1.5）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PycacheSnapshot:
    """Read-only state of the scanned subtrees plus any ``__pycache__`` files.

    Attributes:
        files: ``(relative_posix_path, size, mtime_ns)`` for every scanned file
            **excluding** ``__pycache__`` (the §1.5 known-exemption rule).
        pycache: Relative paths of every ``__pycache__`` entry seen.
    """

    files: tuple[tuple[str, int, int], ...]
    pycache: tuple[str, ...]


def _iter_scope_files(root: Path, scope_dirs: Sequence[str]) -> Iterator[Path]:
    """Yield files under ``root/<scope>`` for every scope directory that exists.

    Args:
        root: Legacy root (read-only).
        scope_dirs: Relative POSIX directory names.

    Yields:
        Existing files (never follows into ``.git`` / ``.venv`` / ``node_modules``).
    """
    for relative in scope_dirs:
        base = root / relative
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
                continue
            yield path


def capture_readonly_snapshot(
    legacy_root: Path, scope_dirs: Sequence[str] = READONLY_SCOPE_DIRS
) -> PycacheSnapshot:
    """Capture ``(path, size, mtime_ns)`` for the scanned subtrees.

    Args:
        legacy_root: Legacy root (read-only).
        scope_dirs: Relative scope directories; defaults to
            :data:`READONLY_SCOPE_DIRS`.

    Returns:
        A :class:`PycacheSnapshot` with sorted entries (deterministic diff).
    """
    files: list[tuple[str, int, int]] = []
    pycache: list[str] = []
    for path in _iter_scope_files(legacy_root, scope_dirs):
        relative = path.relative_to(legacy_root).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            pycache.append(relative)
            continue
        try:
            stat = path.stat()
        except OSError:  # pragma: no cover - racing deletion inside a read-only tree
            continue
        files.append((relative, stat.st_size, stat.st_mtime_ns))
    return PycacheSnapshot(files=tuple(sorted(files)), pycache=tuple(sorted(pycache)))


# ---------------------------------------------------------------------------
# 常量求值（只做静态字面量折叠；求不出来返回 _Unresolved，绝不猜）
# ---------------------------------------------------------------------------


class _Unresolved:
    """Sentinel carrying why an expression could not be folded statically."""

    __slots__ = ("why",)

    def __init__(self, why: str) -> None:
        self.why = why

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<unresolved: {self.why}>"


class _DialectRef:
    """Sentinel for ``op.get_bind().dialect.name`` (a runtime value)."""

    __slots__ = ()


_DIALECT_REF: Final[_DialectRef] = _DialectRef()

#: 模拟目标方言：比对对象是 ``schema.v0018.**pg**.normalized.json``，故按 PG 走分支。
SIMULATED_DIALECT: Final[str] = "postgresql"


def _is_unresolved(value: Any) -> bool:
    """Return ``True`` when ``value`` is the unresolved sentinel."""
    return isinstance(value, _Unresolved)


def _unparse(node: ast.AST) -> str:
    """Return source text for diagnostics, tolerating very old AST nodes."""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive: unparse is best-effort
        return type(node).__name__


class _ConstEvaluator:
    """Folds the small subset of Python expressions that appear in migrations.

    Supported: string/int/bool/None literals, f-strings and ``+`` concatenation
    of them, tuples/lists/sets (including ``*spread`` of a resolvable value),
    module-level name lookup, ``sa.text(<str>)`` unwrapping, ``str(...)``,
    ``tuple(...)`` / ``list(...)``, and the ``op.get_bind().dialect.name``
    sentinel. Everything else becomes :class:`_Unresolved`.
    """

    def eval(self, node: ast.AST | None, env: dict[str, Any]) -> Any:
        """Evaluate ``node`` against ``env``.

        Args:
            node: AST expression (``None`` yields ``None``).
            env: Visible names mapped to folded values.

        Returns:
            The folded value, or an :class:`_Unresolved` instance.
        """
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return env.get(node.id, _Unresolved(f"name {node.id}"))
        if isinstance(node, ast.JoinedStr):
            return self._eval_joined(node, env)
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node, env)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            items: list[Any] = []
            for element in node.elts:
                if isinstance(element, ast.Starred):
                    spread = self.eval(element.value, env)
                    if _is_unresolved(spread) or not isinstance(spread, (tuple, list)):
                        return _Unresolved(f"spread of {_unparse(element.value)}")
                    items.extend(spread)
                    continue
                value = self.eval(element, env)
                if _is_unresolved(value):
                    return value
                items.append(value)
            if isinstance(node, tuple) or isinstance(node, ast.Tuple):
                return tuple(items)
            if isinstance(node, ast.List):
                return list(items)
            return set(items)
        if isinstance(node, ast.Attribute):
            text = _unparse(node)
            if text.endswith("get_bind().dialect.name"):
                return _DIALECT_REF
            return _Unresolved(f"attribute {text}")
        if isinstance(node, ast.Call):
            return self._eval_call(node, env)
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    return _Unresolved("dict unpacking")
                key = self.eval(key_node, env)
                value = self.eval(value_node, env)
                if _is_unresolved(key) or _is_unresolved(value):
                    return _Unresolved(f"dict item {_unparse(key_node)}")
                result[key] = value
            return result
        return _Unresolved(f"expression {_unparse(node)}")

    def _eval_joined(self, node: ast.JoinedStr, env: dict[str, Any]) -> Any:
        """Fold an f-string into a single ``str``."""
        parts: list[str] = []
        for value_node in node.values:
            if isinstance(value_node, ast.Constant):
                parts.append(str(value_node.value))
                continue
            if isinstance(value_node, ast.FormattedValue):
                if value_node.format_spec is not None:
                    return _Unresolved("f-string format spec")
                value = self.eval(value_node.value, env)
                if _is_unresolved(value):
                    return _Unresolved(f"f-string part {_unparse(value_node.value)}")
                parts.append(f"{value}")
                continue
            return _Unresolved("f-string node")
        return "".join(parts)

    def _eval_binop(self, node: ast.BinOp, env: dict[str, Any]) -> Any:
        """Fold ``+`` for strings and sequences."""
        if not isinstance(node.op, ast.Add):
            return _Unresolved(f"binop {type(node.op).__name__}")
        left = self.eval(node.left, env)
        right = self.eval(node.right, env)
        if _is_unresolved(left) or _is_unresolved(right):
            return _Unresolved("binop operand")
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, tuple) and isinstance(right, tuple):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        return _Unresolved("binop types")

    def _eval_call(self, node: ast.Call, env: dict[str, Any]) -> Any:
        """Fold the few whitelisted call shapes; everything else is unresolved."""
        name = _unparse(node.func)
        tail = name.rsplit(".", 1)[-1]
        if tail == "text" and len(node.args) == 1:
            return self.eval(node.args[0], env)
        if tail in {"str", "tuple", "list", "sorted"} and len(node.args) == 1:
            inner = self.eval(node.args[0], env)
            if _is_unresolved(inner):
                return inner
            if tail == "str":
                return str(inner)
            if tail == "tuple":
                return tuple(inner)
            if tail == "list":
                return list(inner)
            return sorted(inner)
        if tail == "reversed" and len(node.args) == 1:
            inner = self.eval(node.args[0], env)
            if _is_unresolved(inner) or not isinstance(inner, (tuple, list)):
                return _Unresolved("reversed operand")
            return list(reversed(inner))
        return _Unresolved(f"call {name}")


# ---------------------------------------------------------------------------
# 模块模型（import 图 / 常量 / 函数）
# ---------------------------------------------------------------------------


@dataclass
class _ModuleModel:
    """Parsed view of one Python module under ``routers/``.

    Attributes:
        key: Dotted key relative to the ``routers`` package (``""`` = package).
        path: Filesystem path (read-only).
        is_package: Whether the file is an ``__init__.py``.
        tree: Parsed AST.
        consts: Module-level folded constants.
        functions: Module-level ``def`` nodes by name.
        imports: ``symbol -> (target_module_key, target_attr_or_None)``;
            external imports are recorded with key ``""`` and a ``None`` attr.
        external: Symbols imported from outside the scanned package.
    """

    key: str
    path: Path
    is_package: bool
    tree: ast.Module
    consts: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    external: set[str] = field(default_factory=set)


def _parse_module(path: Path, key: str, is_package: bool) -> _ModuleModel:
    """Parse one module into a :class:`_ModuleModel`.

    Args:
        path: Source file (read-only).
        key: Dotted key relative to the package root.
        is_package: Whether ``path`` is an ``__init__.py``.

    Returns:
        The parsed model.

    Raises:
        OracleUnavailable: If the file cannot be decoded or parsed.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OracleUnavailable(f"cannot read {path}: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise OracleUnavailable(f"cannot parse {path}: {exc}") from exc

    model = _ModuleModel(key=key, path=path, is_package=is_package, tree=tree)
    evaluator = _ConstEvaluator()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            model.functions[statement.name] = statement
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name):
                model.consts[target.id] = evaluator.eval(statement.value, model.consts)
            continue
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.value is not None:
                model.consts[statement.target.id] = evaluator.eval(statement.value, model.consts)
    return model


# ---------------------------------------------------------------------------
# F1：OpenAPI paths / operations（独立于 compare_openapi.py 的第二套实现）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _IncludeEdge:
    """One ``<router>.include_router(<target>)`` edge.

    Attributes:
        owner: Symbol of the router the call is made on (``"api_router"``).
        target_module: Target router's module key.
        target_attr: ``None`` when the target is the module itself.
        prefix: Extra ``prefix=`` argument on the include call (usually empty).
    """

    owner: str
    target_module: str
    target_attr: str | None
    prefix: str


class _RouterScanner:
    """Recomputes the OpenAPI ``paths`` / ``operations`` sets from ``routers/``.

    Two static-analysis traps are handled explicitly (施工 §10.5):

    1. ``include_router`` targets must be dereferenced through
       ``routers/__init__.py`` re-exports (``from .health import router as
       health_router``) — single-level resolution collapses to ``/health``;
    2. ``include_router`` inside ``if`` blocks is a **conditional** include
       (``/metrics``) and must be skipped — otherwise 135 vs 134.
    """

    def __init__(self, routers_dir: Path) -> None:
        """Bind the scanner to a ``routers`` package directory.

        Args:
            routers_dir: ``_old/apps/api/src/wbtime_ai_api/routers``.
        """
        self._routers_dir = routers_dir
        self._modules: dict[str, _ModuleModel] = {}
        self._prefixes: dict[tuple[str, str], str] = {}
        self._routes: dict[tuple[str, str], list[tuple[str, tuple[str, ...]]]] = {}
        self._includes: dict[tuple[str, str], list[_IncludeEdge]] = {}
        self._notes: list[str] = []

    # -- loading ------------------------------------------------------------

    def load(self) -> None:
        """Parse every module under ``routers/`` and index routers/routes/edges.

        Raises:
            OracleUnavailable: If the directory is missing (G-1 not satisfied).
        """
        if not self._routers_dir.is_dir():
            raise OracleUnavailable(f"routers directory not found: {self._routers_dir}")
        for path in sorted(self._routers_dir.rglob("*.py")):
            relative = path.relative_to(self._routers_dir)
            is_package = relative.name == "__init__.py"
            key = self._key_for(relative, is_package)
            self._modules[key] = _parse_module(path, key, is_package)
        if not self._modules:
            raise OracleUnavailable(f"no modules under {self._routers_dir}")
        for model in self._modules.values():
            self._index_module(model)

    @staticmethod
    def _key_for(relative: Path, is_package: bool) -> str:
        """Return the dotted key for a module path."""
        parts = list(relative.parts)
        if is_package:
            parts = parts[:-1]
        else:
            parts[-1] = relative.stem
        return ".".join(parts)

    def _index_module(self, model: _ModuleModel) -> None:
        """Fill imports / router prefixes / routes / include edges for one module."""
        for statement in model.tree.body:
            if isinstance(statement, ast.ImportFrom):
                self._record_from_import(model, statement)
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    self._record_import_alias(model, alias.name, None, alias.asname)

        # 1) APIRouter(prefix=...) assignments.
        for statement in model.tree.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                targets = [statement.targets[0]]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                targets = [statement.target]
                value = statement.value
            if not targets or value is None:
                continue
            if not self._is_apirouter_ctor(value):
                continue
            target = targets[0]
            if not isinstance(target, ast.Name):
                continue
            prefix = ""
            assert isinstance(value, ast.Call)
            for keyword in value.keywords:
                if keyword.arg == "prefix":
                    folded = _ConstEvaluator().eval(keyword.value, model.consts)
                    if not isinstance(folded, str):
                        raise OracleUnavailable(
                            f"{model.path}: non-literal APIRouter prefix for {target.id}"
                        )
                    prefix = folded
            self._prefixes[(model.key, target.id)] = prefix

        # 2) Route decorators + include_router edges (both live inside functions).
        for node in ast.walk(model.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._record_decorators(model, node)
        for node in ast.walk(model.tree):
            if isinstance(node, ast.Call):
                self._record_include(model, node)

    def _record_decorators(
        self, model: _ModuleModel, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Record ``@<router>.<method>("path")`` decorators of one function."""
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            method = decorator.func.attr
            if not isinstance(owner, ast.Name):
                continue
            if (model.key, owner.id) not in self._prefixes:
                continue
            if method in HTTP_METHODS:
                methods: tuple[str, ...] = (method.upper(),)
            elif method == "api_route":
                methods = self._api_route_methods(decorator, model)
            else:
                continue
            path = self._call_path_argument(decorator, model)
            if path is None:
                raise OracleUnavailable(
                    f"{model.path}: non-literal route path in {function.name}"
                )
            self._routes.setdefault((model.key, owner.id), []).append((path, methods))

    def _api_route_methods(self, decorator: ast.Call, model: _ModuleModel) -> tuple[str, ...]:
        """Extract ``methods=[...]`` from an ``api_route`` decorator."""
        for keyword in decorator.keywords:
            if keyword.arg != "methods":
                continue
            folded = _ConstEvaluator().eval(keyword.value, model.consts)
            if isinstance(folded, (tuple, list)) and all(isinstance(x, str) for x in folded):
                return tuple(str(x).upper() for x in folded)
        return ()

    def _call_path_argument(self, call: ast.Call, model: _ModuleModel) -> str | None:
        """Return the ``path`` of a ``@router.method(...)`` call when literal."""
        candidates: list[ast.expr] = list(call.args)
        candidates.extend(kw.value for kw in call.keywords if kw.arg == "path")
        if not candidates:
            return ""
        folded = _ConstEvaluator().eval(candidates[0], model.consts)
        return folded if isinstance(folded, str) else None

    def _record_include(self, model: _ModuleModel, call: ast.Call) -> None:
        """Record one ``<router>.include_router(<target>, prefix=...)`` edge."""
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "include_router":
            return
        owner_node = call.func.value
        if not isinstance(owner_node, ast.Name):
            return
        if (model.key, owner_node.id) not in self._prefixes:
            return
        if not call.args:
            raise OracleUnavailable(f"{model.path}: include_router without target")
        resolved = self._resolve_reference(model, call.args[0])
        if resolved is None:
            raise OracleUnavailable(
                f"{model.path}: cannot resolve include_router target "
                f"{_unparse(call.args[0])}"
            )
        target_module, target_attr = resolved
        prefix = ""
        for keyword in call.keywords:
            if keyword.arg == "prefix":
                folded = _ConstEvaluator().eval(keyword.value, model.consts)
                if not isinstance(folded, str):
                    raise OracleUnavailable(
                        f"{model.path}: non-literal include_router prefix"
                    )
                prefix = folded
        self._includes.setdefault((model.key, owner_node.id), []).append(
            _IncludeEdge(
                owner=owner_node.id,
                target_module=target_module,
                target_attr=target_attr,
                prefix=prefix,
            )
        )

    def _resolve_reference(
        self, model: _ModuleModel, node: ast.expr
    ) -> tuple[str, str | None] | None:
        """Resolve ``auth.router`` / ``api_router`` / ``v1.auth`` to a module ref.

        Args:
            model: The module the reference appears in.
            node: Reference expression.

        Returns:
            ``(module_key, attr_or_None)`` or ``None`` when unresolvable.
        """
        if isinstance(node, ast.Name):
            if node.id in model.imports:
                return model.imports[node.id]
            if node.id in self._modules:
                return (node.id, None)
            return None
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id in model.imports:
                module_key, attr = model.imports[base.id]
                if attr is None:
                    return (module_key, node.attr) if module_key else None
                return None
            if isinstance(base, ast.Name) and base.id in self._modules:
                return (base.id, node.attr)
            return None
        return None

    def _record_from_import(self, model: _ModuleModel, statement: ast.ImportFrom) -> None:
        """Record ``from ... import ...`` symbols, mapping them onto module keys."""
        base_parts = self._absolute_base_parts(model, statement)
        for alias in statement.names:
            local = alias.asname or alias.name
            if base_parts is None:
                model.external.add(local)
                continue
            if alias.name == "*":
                raise OracleUnavailable(f"{model.path}: star import is not supported")
            module_key = ".".join(base_parts + [alias.name]) if base_parts else alias.name
            if module_key in self._modules:
                model.imports[local] = (module_key, None)
                continue
            parent = ".".join(base_parts) if base_parts else ""
            if parent in self._modules:
                model.imports[local] = (parent, alias.name)
                continue
            model.external.add(local)

    def _record_import_alias(
        self, model: _ModuleModel, name: str, attr: str | None, asname: str | None
    ) -> None:
        """Record a plain ``import a.b.c`` statement."""
        local = asname or name.split(".")[0]
        mapped = self._to_package_key(name)
        if mapped is not None:
            model.imports[local] = (mapped, attr)
            return
        model.external.add(local)

    def _absolute_base_parts(self, model: _ModuleModel, statement: ast.ImportFrom) -> list[str] | None:
        """Compute the package key a ``from`` import is relative to.

        Args:
            model: Importing module.
            statement: The ``ImportFrom`` node.

        Returns:
            Package parts relative to the scanned package root, or ``None``
            when the import points outside the scanned package.
        """
        if statement.level == 0:
            mapped = self._to_package_key(statement.module or "")
            return None if mapped is None else ([mapped] if mapped else [])
        if not model.key:
            # 包根模块（``routers/__init__.py``）：自身即包，父级为空。
            package_parts: list[str] = []
        elif model.is_package:
            package_parts = model.key.split(".")
        else:
            package_parts = model.key.split(".")[:-1]
        drop = statement.level - 1
        if drop:
            if drop > len(package_parts):
                return None
            package_parts = package_parts[: len(package_parts) - drop]
        parts = list(package_parts)
        if statement.module:
            parts.extend(statement.module.split("."))
        return parts

    def _to_package_key(self, dotted: str) -> str | None:
        """Map an absolute import path onto a key inside the scanned package.

        ``wbtime_ai_api.routers.v1.auth`` → ``v1.auth``; foreign packages →
        ``None``. The package name is derived from the ``routers`` parent so no
        string literal has to be kept in sync with ``_old``.
        """
        package_name = self._routers_dir.parent.name
        prefix = f"{package_name}.routers"
        if dotted == prefix:
            return ""
        if dotted.startswith(prefix + "."):
            return dotted[len(prefix) + 1 :]
        if dotted == "routers":
            return ""
        if dotted.startswith("routers."):
            return dotted[len("routers.") :]
        return None

    @staticmethod
    def _is_apirouter_ctor(node: ast.expr) -> bool:
        """Return ``True`` when ``node`` is ``APIRouter(...)``."""
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "APIRouter"
        )

    @property
    def notes(self) -> tuple[str, ...]:
        """Honesty notes collected while scanning (conditional includes etc.)."""
        return tuple(self._notes)

    # -- resolution ---------------------------------------------------------

    def resolve(self, module_key: str, symbol: str) -> list[tuple[str, tuple[str, ...]]]:
        """Return every ``(path, methods)`` mounted by one router, prefix applied.

        Aliases are dereferenced transitively (``routers/__init__.py`` re-export).

        Args:
            module_key: Module that declares (or re-exports) the router.
            symbol: Router symbol in that module.

        Returns:
            Mounted ``(full_path, http_methods)`` pairs.

        Raises:
            OracleUnavailable: On an unresolvable reference or an include cycle.
        """
        resolved = self._deref(module_key, symbol, seen=())
        return self._collect(resolved[0], resolved[1], seen=())

    def _deref(
        self, module_key: str, symbol: str, *, seen: tuple[tuple[str, str], ...]
    ) -> tuple[str, str]:
        """Follow alias chains until a router assignment is reached."""
        if (module_key, symbol) in seen:
            raise OracleUnavailable(f"router alias cycle at {module_key}::{symbol}")
        if (module_key, symbol) in self._prefixes:
            return (module_key, symbol)
        module = self._modules.get(module_key)
        if module is not None and symbol in module.imports:
            target = module.imports[symbol]
            if target[1] is None:
                raise OracleUnavailable(
                    f"{module_key}::{symbol} points at a module, not a router"
                )
            return self._deref(target[0], target[1], seen=seen + ((module_key, symbol),))
        raise OracleUnavailable(f"unresolvable router {module_key}::{symbol}")

    def _collect(
        self,
        module_key: str,
        symbol: str,
        *,
        seen: tuple[tuple[str, str], ...],
        extra_prefix: str = "",
    ) -> list[tuple[str, tuple[str, ...]]]:
        """Recursively collect mounted routes for one router object."""
        if (module_key, symbol) in seen:
            raise OracleUnavailable(f"include_router cycle at {module_key}::{symbol}")
        chain = seen + ((module_key, symbol),)
        prefix = extra_prefix + self._prefixes.get((module_key, symbol), "")
        mounted: list[tuple[str, tuple[str, ...]]] = []
        for route_path, methods in self._routes.get((module_key, symbol), []):
            mounted.append((_join_path(prefix, route_path), methods))
        for edge in self._includes.get((module_key, symbol), []):
            if edge.target_attr is None:
                raise OracleUnavailable(
                    f"{module_key}: include_router target has no router attribute"
                )
            target = self._deref(edge.target_module, edge.target_attr, seen=chain)
            mounted.extend(
                self._collect(
                    target[0],
                    target[1],
                    seen=chain,
                    extra_prefix=_join_path(prefix, edge.prefix),
                )
            )
        return mounted

    def scan_app(self, app_module: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Mount the routers registered by the FastAPI app factory.

        Only **unconditional** ``include_router`` calls count (施工 §10.5-1).

        Args:
            app_module: ``_old/.../wbtime_ai_api/main.py``.

        Returns:
            ``(paths, operations)`` sorted tuples; ``operations`` are
            ``"METHOD /path"`` strings.
        """
        if not app_module.is_file():
            raise OracleUnavailable(f"app module not found: {app_module}")
        model = _parse_module(app_module, key="__app__", is_package=False)
        self._collect_app_imports(model)
        roots: list[tuple[str, str]] = []
        conditional: list[str] = []
        factory = self._find_factory(model)
        self._walk_app_body(factory.body, model, roots, conditional, nested=False)
        if not roots:
            raise OracleUnavailable(f"no unconditional include_router in {app_module}")
        if not conditional:
            self._notes.append(
                "F1: no conditional include_router found (expected /metrics to be conditional)"
            )
        else:
            self._notes.append(
                "F1: skipped conditional include_router -> " + ", ".join(sorted(conditional))
            )

        paths: set[str] = set()
        operations: set[str] = set()
        for module_key, symbol in roots:
            resolved = self._deref(module_key, symbol, seen=())
            for path, methods in self._collect(resolved[0], resolved[1], seen=()):
                paths.add(path)
                for method in methods:
                    operations.add(f"{method} {path}")
        if not paths:
            raise OracleUnavailable("F1 resolved zero paths (vacuous oracle)")
        return tuple(sorted(paths)), tuple(sorted(operations))

    def _find_factory(self, model: _ModuleModel) -> ast.FunctionDef:
        """Return the FastAPI app factory function (``create_app`` by convention)."""
        for name in ("create_app", "create_application", "build_app"):
            if name in model.functions:
                function = model.functions[name]
                if isinstance(function, ast.AsyncFunctionDef):  # pragma: no cover
                    raise OracleUnavailable(f"{model.path}: async app factory")
                return function
        raise OracleUnavailable(f"{model.path}: no app factory function found")

    def _collect_app_imports(self, model: _ModuleModel) -> None:
        """Attach parsed ``routers`` import symbols to the app module."""
        for statement in model.tree.body:
            if isinstance(statement, ast.ImportFrom):
                self._record_from_import(model, statement)

    def _walk_app_body(
        self,
        body: Sequence[ast.stmt],
        model: _ModuleModel,
        roots: list[tuple[str, str]],
        conditional: list[str],
        *,
        nested: bool,
    ) -> None:
        """Collect ``*.include_router(<router>)`` calls, tagging conditionality."""
        for statement in body:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "include_router"
                    and call.args
                ):
                    resolved = self._resolve_reference(model, call.args[0])
                    label = _unparse(call.args[0])
                    if nested:
                        conditional.append(label)
                        continue
                    if resolved is None:
                        raise OracleUnavailable(
                            f"{model.path}: cannot resolve include_router({label})"
                        )
                    if resolved[1] is None:
                        raise OracleUnavailable(
                            f"{model.path}: include_router({label}) is not a router attribute"
                        )
                    roots.append((resolved[0], resolved[1]))
                    continue
            if isinstance(statement, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                for nested_body in self._nested_bodies(statement):
                    self._walk_app_body(
                        nested_body, model, roots, conditional, nested=True
                    )

    @staticmethod
    def _nested_bodies(statement: ast.stmt) -> list[list[ast.stmt]]:
        """Return the nested statement lists of a compound statement."""
        bodies: list[list[ast.stmt]] = []
        for attribute in ("body", "orelse", "finalbody"):
            nested = getattr(statement, attribute, None)
            if isinstance(nested, list):
                bodies.append(nested)
        for handler in getattr(statement, "handlers", []) or []:
            bodies.append(handler.body)
        return bodies


def _join_path(prefix: str, path: str) -> str:
    """Join a router prefix and a route path into a normalized OpenAPI path."""
    if not prefix:
        joined = path or "/"
    elif not path:
        joined = prefix
    elif path.startswith("/"):
        joined = prefix.rstrip("/") + path
    else:
        joined = prefix.rstrip("/") + "/" + path
    if not joined.startswith("/"):
        joined = "/" + joined
    return joined


# ---------------------------------------------------------------------------
# F2：Alembic 迁移链累积（模拟 PG 分支）
# ---------------------------------------------------------------------------


@dataclass
class _DdlState:
    """Accumulated DDL at the migration head (chain order, PG branch only)."""

    tables: dict[str, list[str]] = field(default_factory=dict)
    indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    ignored: dict[str, int] = field(default_factory=dict)
    opaque_sql: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)


class _Return(Exception):
    """Internal control-flow signal for a ``return`` inside a walked function."""

    def __init__(self, value: ast.AST | None) -> None:
        super().__init__("return")
        self.value = value


class _Break(Exception):
    """Internal control-flow signal for ``break``."""


class _Continue(Exception):
    """Internal control-flow signal for ``continue``."""


@dataclass(frozen=True)
class _BatchContext:
    """Marker bound to ``op.batch_alter_table("t") as batch_op``."""

    table: str


@dataclass(frozen=True)
class _ColumnRef:
    """A column resolved statically and bound to a loop variable.

    ``for column in _new_columns(): op.add_column(_TABLE, column)`` — the loop
    target is bound to one of these so the DDL walker can keep going without
    re-evaluating ``sa.Column(...)``.
    """

    name: str


class _MigrationWalker:
    """Accumulates the DDL final state by walking the Alembic chain in order.

    .. important::
       选择「迁移链累积」而不是「ORM metadata」重算 F2，理由有三：

       1. 索引名在迁移里是**字面量**（``op.create_index("ix_x", ...)``），而 ORM
          侧由 ``metadata.naming_convention`` 生成 ⇒ 后者需要在 oracle 里实现一整套
          命名约定推断，等于新增一层可能出错的推断；
       2. raw hnsw 索引**只**存在于迁移（``op.execute("CREATE INDEX ... USING hnsw")``），
          ORM metadata 里没有 DDL 形态；
       3. ``schema_version`` 是 ``v0018``（迁移 head），迁移链累积天然对齐该版本。

    解析规则（施工 §5-T03 风险条款）：同一表多次 ``add_column`` 按链序累积；任何
    无法静态折叠的实参 ⇒ :class:`OracleUnavailable`（**不猜**）。方言分支按 PG 走
    （比对对象是 ``schema.v0018.pg.normalized.json``）。
    """

    def __init__(self, versions_dir: Path) -> None:
        """Bind the walker to an Alembic ``versions`` directory.

        Args:
            versions_dir: ``_old/migrations/versions``.
        """
        self._versions_dir = versions_dir
        self._evaluator = _ConstEvaluator()
        self._state = _DdlState()

    def run(self) -> tuple[_DdlState, tuple[str, ...]]:
        """Walk ``upgrade()`` of every revision in chain order.

        Returns:
            ``(state, revision_chain)``.

        Raises:
            OracleUnavailable: If the chain is broken or a module cannot be parsed.
        """
        if not self._versions_dir.is_dir():
            raise OracleUnavailable(f"migrations versions dir not found: {self._versions_dir}")
        revisions: dict[str, tuple[Path, str | None]] = {}
        for path in sorted(self._versions_dir.glob("*.py")):
            model = _parse_module(path, key=path.stem, is_package=False)
            revision = model.consts.get("revision")
            down = model.consts.get("down_revision")
            if not isinstance(revision, str):
                raise OracleUnavailable(f"{path}: missing literal `revision`")
            if down is not None and not isinstance(down, str):
                raise OracleUnavailable(f"{path}: non-literal `down_revision`")
            revisions[revision] = (path, down)

        heads = [rev for rev, (_, down) in revisions.items() if down is None]
        if len(heads) != 1:
            raise OracleUnavailable(
                f"migrations chain must have exactly one root, found {sorted(heads)}"
            )
        by_down: dict[str | None, list[str]] = {}
        for rev, (_, down) in revisions.items():
            by_down.setdefault(down, []).append(rev)
        if any(len(children) > 1 for children in by_down.values()):
            raise OracleUnavailable("migrations chain is branched (expected single linear head)")

        chain: list[str] = []
        cursor: str | None = heads[0]
        while cursor is not None:
            chain.append(cursor)
            children = by_down.get(cursor, [])
            cursor = children[0] if children else None
        if len(chain) != len(revisions):
            missing = sorted(set(revisions) - set(chain))
            raise OracleUnavailable(f"migrations chain does not reach: {missing}")
        declared = self._declared_head(revisions)
        if declared is not None and declared != chain[-1]:
            raise OracleUnavailable(f"migration head mismatch: walked {chain[-1]}, dir says {declared}")

        for revision in chain:
            path, _ = revisions[revision]
            model = _parse_module(path, key=path.stem, is_package=False)
            self._run_upgrade(model, revision)
        return self._state, tuple(chain)

    @staticmethod
    def _declared_head(revisions: dict[str, tuple[Path, str | None]]) -> str | None:
        """Return the expected head name if a ``0018_*`` module is present."""
        names = sorted(revisions)
        return names[-1] if names else None

    # -- module / function walking -----------------------------------------

    def _run_upgrade(self, model: _ModuleModel, revision: str) -> None:
        """Execute one migration's ``upgrade()``."""
        upgrade = model.functions.get("upgrade")
        if upgrade is None:
            raise OracleUnavailable(f"{model.path}: no upgrade() function")
        env = dict(model.consts)
        self._exec_function(model, upgrade, env, depth=0, revision=revision)

    def _exec_function(
        self,
        model: _ModuleModel,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
        args: Sequence[Any] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Execute a function body with statically bound arguments."""
        if depth > 8:
            raise OracleUnavailable(f"{model.path}: call depth exceeded in {function.name}")
        local = dict(env)
        arguments = list(function.args.args)
        for index, argument in enumerate(arguments):
            if index < len(args):
                local[argument.arg] = args[index]
            elif kwargs and argument.arg in kwargs:
                local[argument.arg] = kwargs[argument.arg]
            else:
                local[argument.arg] = _Unresolved(f"parameter {argument.arg}")
        try:
            self._exec_block(model, function.body, local, depth=depth, revision=revision)
        except _Return:
            return
        except (_Break, _Continue):  # pragma: no cover - top-level stray signal
            return

    def _exec_block(
        self,
        model: _ModuleModel,
        body: Sequence[ast.stmt],
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Execute a statement block sequentially."""
        for statement in body:
            self._exec_statement(model, statement, env, depth=depth, revision=revision)

    def _exec_statement(
        self,
        model: _ModuleModel,
        statement: ast.stmt,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Execute one statement."""
        if isinstance(statement, ast.Return):
            raise _Return(statement.value)
        if isinstance(statement, ast.Break):
            raise _Break()
        if isinstance(statement, ast.Continue):
            raise _Continue()
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            self._exec_binding(statement, env)
            return
        if isinstance(statement, ast.AugAssign):
            return
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            self._dispatch_call(model, statement.value, env, depth=depth, revision=revision)
            return
        if isinstance(statement, ast.If):
            self._exec_if(model, statement, env, depth=depth, revision=revision)
            return
        if isinstance(statement, ast.For):
            self._exec_for(model, statement, env, depth=depth, revision=revision)
            return
        if isinstance(statement, ast.With):
            self._exec_with(model, statement, env, depth=depth, revision=revision)
            return
        if isinstance(statement, ast.Try):
            try:
                self._exec_block(model, statement.body, env, depth=depth, revision=revision)
            except (_Return, _Break, _Continue):
                raise
            for handler in statement.handlers:
                self._exec_block(model, handler.body, dict(env), depth=depth, revision=revision)
            return
        # Pass / Assert / Raise / ... carry no DDL semantics.

    def _exec_binding(self, statement: ast.Assign | ast.AnnAssign, env: dict[str, Any]) -> None:
        """Bind a simple name (``x = ...``) to its folded value."""
        target = statement.targets[0] if isinstance(statement, ast.Assign) else statement.target
        value_node = statement.value
        if not isinstance(target, ast.Name) or value_node is None:
            return
        folded = self._evaluator.eval(value_node, env)
        if isinstance(folded, _DialectRef):
            env[target.id] = SIMULATED_DIALECT
            return
        env[target.id] = folded

    def _exec_if(
        self,
        model: _ModuleModel,
        statement: ast.If,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Execute an ``if`` under the simulated dialect.

        When the condition cannot be folded, **both** branches are walked: the
        legacy schema is then the union (nothing is silently dropped).
        """
        verdict = self._eval_test(statement.test, env)
        if verdict is True:
            self._exec_block(model, statement.body, env, depth=depth, revision=revision)
            return
        if verdict is False:
            self._exec_block(model, statement.orelse, env, depth=depth, revision=revision)
            return
        self._state.notes.append(
            f"F2: unfolded condition in {model.path.name} -> walked both branches: "
            f"{_unparse(statement.test)}"
        )
        # 守卫式分支（``if _column_exists(...): continue``）在「对象不存在」的假定时
        # 不成立 ⇒ 该分支的控制流信号只属于分支内部，不得终止外层循环。
        for branch in (statement.body, statement.orelse):
            try:
                self._exec_block(model, branch, dict(env), depth=depth, revision=revision)
            except (_Continue, _Break):
                continue

    def _eval_test(self, node: ast.expr, env: dict[str, Any]) -> bool | None:
        """Three-valued evaluation of an ``if`` test (``None`` = unknown)."""
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left = self._evaluator.eval(node.left, env)
            right = self._evaluator.eval(node.comparators[0], env)
            operator = node.ops[0]
            if _is_unresolved(left) or _is_unresolved(right):
                return None
            if isinstance(operator, ast.Eq):
                return left == right
            if isinstance(operator, ast.NotEq):
                return left != right
            if isinstance(operator, ast.In):
                try:
                    return left in right
                except TypeError:  # pragma: no cover - odd operands
                    return None
            if isinstance(operator, ast.NotIn):
                try:
                    return left not in right
                except TypeError:  # pragma: no cover
                    return None
            return None
        if isinstance(node, ast.BoolOp):
            verdicts = [self._eval_test(value, env) for value in node.values]
            if isinstance(node.op, ast.And):
                if any(v is False for v in verdicts):
                    return False
                if all(v is True for v in verdicts):
                    return True
                return None
            if any(v is True for v in verdicts):
                return True
            if all(v is False for v in verdicts):
                return False
            return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = self._eval_test(node.operand, env)
            return None if inner is None else (not inner)
        if isinstance(node, ast.Constant):
            return bool(node.value)
        if isinstance(node, ast.Name):
            value = env.get(node.id, _Unresolved(node.id))
            if isinstance(value, bool):
                return value
            return None
        return None

    def _exec_for(
        self,
        model: _ModuleModel,
        statement: ast.For,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Iterate a resolvable iterable, binding the loop target."""
        iterable = self._eval_iterable(model, statement.iter, env)
        if _is_unresolved(iterable) or not isinstance(iterable, (tuple, list)):
            if self._body_may_emit_ddl(model, statement.body):
                raise OracleUnavailable(
                    f"{model.path}: cannot resolve loop iterable {_unparse(statement.iter)} "
                    "and the body may emit DDL"
                )
            self._state.notes.append(
                f"F2: skipped data-only loop over {_unparse(statement.iter)} in "
                f"{model.path.name} (no DDL in body)"
            )
            return
        for item in iterable:
            local = dict(env)
            self._bind_target(statement.target, item, local, model)
            try:
                self._exec_block(model, statement.body, local, depth=depth, revision=revision)
            except _Continue:
                continue
            except _Break:
                break
        else_body = statement.orelse
        if else_body:
            self._exec_block(model, else_body, env, depth=depth, revision=revision)

    def _eval_iterable(
        self, model: _ModuleModel, node: ast.expr, env: dict[str, Any]
    ) -> Any:
        """Resolve a ``for`` iterable, including ``for c in _new_columns():``.

        Args:
            model: Module owning the loop.
            node: Iterable expression.
            env: Visible names.

        Returns:
            A tuple/list of bound values, or an :class:`_Unresolved` sentinel.
        """
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = model.functions.get(node.func.id)
            if function is not None:
                names = self._columns_from_function(model, function, env)
                return tuple(_ColumnRef(name=name) for name in names)
        return self._evaluator.eval(node, env)

    def _body_may_emit_ddl(
        self, model: _ModuleModel, body: Sequence[ast.stmt]
    ) -> bool:
        """Return ``True`` when a block may change the table/column/index sets.

        Used to decide whether an unresolvable ``for`` iterable is a hard
        :class:`OracleUnavailable` (DDL inside) or a skippable data backfill.

        Args:
            model: Module that owns the block.
            body: Statements of the loop body.

        Returns:
            ``True`` when any statement calls ``op.*`` / a local module function
            or opens a ``batch_alter_table`` context.
        """
        for statement in body:
            for node in ast.walk(statement):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Attribute):
                    receiver = function.value
                    if isinstance(receiver, ast.Name) and receiver.id in {"op", "batch_op"}:
                        return True
                    if function.attr == "batch_alter_table":
                        return True
                elif isinstance(function, ast.Name) and function.id in model.functions:
                    return True
        return False

    def _bind_target(        self, target: ast.expr, value: Any, env: dict[str, Any], model: _ModuleModel
    ) -> None:
        """Bind a ``for`` target (name or tuple pattern)."""
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(value, (tuple, list)) or len(value) != len(target.elts):
                raise OracleUnavailable(
                    f"{model.path}: loop target arity mismatch at {_unparse(target)}"
                )
            for element, item in zip(target.elts, value):
                self._bind_target(element, item, env, model)
            return
        raise OracleUnavailable(f"{model.path}: unsupported loop target {_unparse(target)}")

    def _exec_with(
        self,
        model: _ModuleModel,
        statement: ast.With,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Handle ``with op.batch_alter_table("t") as batch_op:`` blocks."""
        local = dict(env)
        for item in statement.items:
            context = item.context_expr
            if (
                isinstance(context, ast.Call)
                and isinstance(context.func, ast.Attribute)
                and context.func.attr == "batch_alter_table"
                and context.args
            ):
                table = self._evaluator.eval(context.args[0], local)
                if not isinstance(table, str):
                    raise OracleUnavailable(
                        f"{model.path}: non-literal batch_alter_table target"
                    )
                if isinstance(item.optional_vars, ast.Name):
                    local[item.optional_vars.id] = _BatchContext(table=table)
            elif isinstance(item.optional_vars, ast.Name):
                local[item.optional_vars.id] = _Unresolved("with target")
        self._exec_block(model, statement.body, local, depth=depth, revision=revision)

    # -- call dispatch ------------------------------------------------------

    def _dispatch_call(
        self,
        model: _ModuleModel,
        call: ast.Call,
        env: dict[str, Any],
        *,
        depth: int,
        revision: str,
    ) -> None:
        """Route a call to ``op.*`` / ``batch_op.*`` / a local function."""
        func = call.func
        if isinstance(func, ast.Attribute):
            receiver = func.value
            if isinstance(receiver, ast.Name) and receiver.id == "op":
                self._handle_op(model, func.attr, call, env, batch_table=None)
                return
            if isinstance(receiver, ast.Name) and isinstance(
                env.get(receiver.id), _BatchContext
            ):
                context = env[receiver.id]
                assert isinstance(context, _BatchContext)
                self._handle_op(model, func.attr, call, env, batch_table=context.table)
                return
            if isinstance(receiver, ast.Attribute) or isinstance(receiver, ast.Call):
                # module-level helper called through an object (``sa.text`` etc.) or
                # chained calls (``op.get_bind()``): no DDL semantics.
                return
            return
        if isinstance(func, ast.Name):
            local_function = model.functions.get(func.id)
            if local_function is not None:
                args = [self._evaluator.eval(arg, env) for arg in call.args]
                kwargs = {
                    keyword.arg: self._evaluator.eval(keyword.value, env)
                    for keyword in call.keywords
                    if keyword.arg
                }
                resolved_args = [
                    None if _is_unresolved(value) else value for value in args
                ]
                resolved_kwargs = {
                    key: (None if _is_unresolved(value) else value)
                    for key, value in kwargs.items()
                }
                self._exec_function(
                    model,
                    local_function,
                    env,
                    depth=depth + 1,
                    revision=revision,
                    args=resolved_args,
                    kwargs=resolved_kwargs,
                )
                return
            return

    def _handle_op(
        self,
        model: _ModuleModel,
        action: str,
        call: ast.Call,
        env: dict[str, Any],
        *,
        batch_table: str | None,
    ) -> None:
        """Apply one ``op.<action>`` to the accumulated DDL state."""
        if action in IGNORED_OP_ACTIONS:
            self._state.ignored[action] = self._state.ignored.get(action, 0) + 1
            return
        if action == "create_table":
            self._op_create_table(model, call, env)
            return
        if action == "drop_table":
            name = self._require_str(model, call, env, 0, "drop_table table")
            self._state.tables.pop(name, None)
            return
        if action == "add_column":
            table = batch_table or self._require_str(model, call, env, 0, "add_column table")
            column_node = self._column_node(call, offset=0 if batch_table else 1)
            column = self._column_name(model, column_node, env)
            self._add_column(table, column)
            return
        if action == "drop_column":
            table = batch_table or self._require_str(model, call, env, 0, "drop_column table")
            if batch_table is not None:
                column = self._require_str(model, call, env, 0, "drop_column column")
            else:
                column = self._require_str(model, call, env, 1, "drop_column column")
            self._drop_column(table, column)
            return
        if action == "create_index":
            self._op_create_index(model, call, env, batch_table=batch_table)
            return
        if action == "drop_index":
            name = self._require_str(model, call, env, 0, "drop_index name")
            self._state.indexes.pop(name, None)
            return
        if action == "execute":
            self._op_execute(model, call, env)
            return
        self._state.notes.append(f"F2: unhandled op.{action} in {model.path.name}")
        self._state.ignored[action] = self._state.ignored.get(action, 0) + 1

    def _op_create_table(self, model: _ModuleModel, call: ast.Call, env: dict[str, Any]) -> None:
        """Record a ``create_table`` plus its literal columns."""
        table = self._require_str(model, call, env, 0, "create_table name")
        columns: list[str] = []
        for element in call.args[1:]:
            if isinstance(element, ast.Starred):
                columns.extend(self._columns_from_element(model, element.value, env))
                continue
            columns.extend(self._columns_from_element(model, element, env))
        self._state.tables.setdefault(table, [])
        for column in columns:
            self._add_column(table, column)

    def _columns_from_element(
        self, model: _ModuleModel, node: ast.expr, env: dict[str, Any]
    ) -> list[str]:
        """Return the column names contributed by one ``create_table`` element."""
        if isinstance(node, ast.Name):
            bound = env.get(node.id)
            if isinstance(bound, _ColumnRef):
                return [bound.name]
            raise OracleUnavailable(
                f"{model.path}: unresolved column element {node.id}"
            )
        if isinstance(node, ast.Call) and self._call_tail(node.func) == "Column":
            return [self._column_name(model, node, env)]
        if isinstance(node, ast.Call) and self._call_tail(node.func) in {
            "PrimaryKeyConstraint",
            "ForeignKeyConstraint",
            "UniqueConstraint",
            "CheckConstraint",
            "Index",
        }:
            return []
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = model.functions.get(node.func.id)
            if function is not None:
                return self._columns_from_function(model, function, env)
        raise OracleUnavailable(
            f"{model.path}: unsupported create_table element {_unparse(node)}"
        )

    def _columns_from_function(
        self,
        model: _ModuleModel,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        env: dict[str, Any],
    ) -> list[str]:
        """Collect column names from a helper that returns ``sa.Column(...)`` items."""
        local = dict(env)
        for argument in function.args.args:
            local[argument.arg] = _Unresolved(f"parameter {argument.arg}")
        try:
            self._exec_block(model, function.body, local, depth=0, revision="<helper>")
        except _Return as signal:
            return self._columns_from_return(model, signal.value, local)
        # No return: helper performed side effects only.
        return []

    def _columns_from_return(
        self, model: _ModuleModel, value: ast.AST | None, env: dict[str, Any]
    ) -> list[str]:
        """Convert a helper's ``return`` value into column names."""
        if value is None:
            return []
        if isinstance(value, (ast.Tuple, ast.List)):
            names: list[str] = []
            for element in value.elts:
                names.extend(self._columns_from_element(model, element, env))
            return names
        return self._columns_from_element(model, value, env)

    def _op_create_index(
        self,
        model: _ModuleModel,
        call: ast.Call,
        env: dict[str, Any],
        *,
        batch_table: str | None,
    ) -> None:
        """Record ``create_index(name, table, columns, unique=...)``."""
        name = self._require_str(model, call, env, 0, "create_index name")
        table = batch_table
        unique = False
        for keyword in call.keywords:
            if keyword.arg == "unique":
                folded = self._evaluator.eval(keyword.value, env)
                unique = bool(folded) if not _is_unresolved(folded) else False
            elif keyword.arg in {"table_name", "table"} and table is None:
                folded = self._evaluator.eval(keyword.value, env)
                if isinstance(folded, str):
                    table = folded
        if table is None:
            for argument in call.args[1:]:
                folded = self._evaluator.eval(argument, env)
                if isinstance(folded, str):
                    table = folded
                    break
        if table is None:
            raise OracleUnavailable(
                f"{model.path}: create_index({name}) without a resolvable table"
            )
        self._state.indexes[name] = {"table": table, "unique": unique}

    def _op_execute(self, model: _ModuleModel, call: ast.Call, env: dict[str, Any]) -> None:
        """Classify one raw ``op.execute(...)`` statement."""
        if not call.args:
            return
        folded = self._evaluator.eval(call.args[0], env)
        if not isinstance(folded, str):
            reason = folded.why if isinstance(folded, _Unresolved) else type(folded).__name__
            raise OracleUnavailable(
                f"{model.path}: non-literal op.execute SQL ({reason})"
            )
        sql = " ".join(folded.split())
        create_index = _CREATE_INDEX_RE.search(sql)
        if create_index:
            name = create_index.group("name")
            table = create_index.group("table")
            rest = create_index.group("rest") or ""
            method = "hnsw" if _HNSW_RE.search(rest) else "btree"
            operator_class: str | None = None
            match = _OPERATOR_CLASS_RE.search(rest)
            if match:
                operator_class = match.group("opclass")
            if method == "hnsw":
                self._state.raw_indexes[name] = {
                    "table": table,
                    "method": method,
                    "operator_class": operator_class,
                    "sql": sql,
                }
            else:
                self._state.indexes[name] = {"table": table, "unique": False}
            return
        alter_add = _ALTER_ADD_COLUMN_RE.search(sql)
        if alter_add:
            self._add_column(alter_add.group("table"), alter_add.group("column"))
            return
        drop_index = _DROP_INDEX_RE.search(sql)
        if drop_index:
            self._state.indexes.pop(drop_index.group("name"), None)
            self._state.raw_indexes.pop(drop_index.group("name"), None)
            return
        create_table = _CREATE_TABLE_RE.search(sql)
        if create_table:
            self._state.tables.setdefault(create_table.group("table"), [])
            return
        if sql.upper().startswith("CREATE EXTENSION"):
            self._state.extensions.append(sql)
            return
        self._state.opaque_sql.append(sql)

    # -- primitives ---------------------------------------------------------

    def _add_column(self, table: str, column: str) -> None:
        """Append a column to a table (idempotent, order-preserving)."""
        self._state.tables.setdefault(table, [])
        if column not in self._state.tables[table]:
            self._state.tables[table].append(column)

    def _drop_column(self, table: str, column: str) -> None:
        """Remove a column from a table when present."""
        columns = self._state.tables.get(table)
        if columns is None:
            self._state.notes.append(f"F2: drop_column on unknown table {table}.{column}")
            return
        if column not in columns:
            self._state.notes.append(f"F2: drop_column of unknown column {table}.{column}")
            return
        columns.remove(column)

    @staticmethod
    def _call_tail(node: ast.expr) -> str:
        """Return the trailing attribute/name of a call target."""
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return node.id
        return ""

    @staticmethod
    def _column_node(call: ast.Call, *, offset: int) -> ast.expr:
        """Return the ``sa.Column(...)`` node of an ``add_column`` call."""
        if len(call.args) <= offset:
            raise OracleUnavailable("add_column without a column argument")
        return call.args[offset]

    def _column_name(
        self, model: _ModuleModel, node: ast.expr, env: dict[str, Any]
    ) -> str:
        """Return the literal column name of a ``sa.Column("x", ...)`` node."""
        if isinstance(node, ast.Name):
            bound = env.get(node.id)
            if isinstance(bound, _ColumnRef):
                return bound.name
            if isinstance(bound, str):
                return bound
            raise OracleUnavailable(
                f"{model.path}: unresolved column variable {node.id}"
            )
        if not isinstance(node, ast.Call) or self._call_tail(node.func) != "Column":
            raise OracleUnavailable(
                f"{model.path}: unsupported column expression {_unparse(node)}"
            )
        if not node.args:
            raise OracleUnavailable(f"{model.path}: Column without name")
        folded = self._evaluator.eval(node.args[0], env)
        if not isinstance(folded, str):
            raise OracleUnavailable(
                f"{model.path}: non-literal column name {_unparse(node.args[0])}"
            )
        return folded

    def _require_str(
        self,
        model: _ModuleModel,
        call: ast.Call,
        env: dict[str, Any],
        index: int,
        what: str,
    ) -> str:
        """Return a literal string argument, or raise :class:`OracleUnavailable`."""
        if len(call.args) <= index:
            raise OracleUnavailable(f"{model.path}: missing {what}")
        folded = self._evaluator.eval(call.args[index], env)
        if not isinstance(folded, str):
            raise OracleUnavailable(
                f"{model.path}: non-literal {what} ({_unparse(call.args[index])})"
            )
        return folded


# ---------------------------------------------------------------------------
# F3 / F4：SSE 通道 / 错误码
# ---------------------------------------------------------------------------


def scan_sse_channels(encoder_path: Path) -> tuple[str, ...]:
    """Recompute the SSE channel name set from ``SSE_CHANNEL_BY_DOMAIN_TYPE``.

    Uses ``ast.literal_eval`` on the dict literal — the ``_old`` module is
    **never imported** (no dependency, no ``__pycache__``).

    Args:
        encoder_path: ``_old/apps/api/src/wbtime_ai_api/sse/encoder.py``.

    Returns:
        Sorted channel names (the dict **values**).

    Raises:
        OracleUnavailable: If the file or the literal dict is missing.
    """
    if not encoder_path.is_file():
        raise OracleUnavailable(f"SSE encoder not found: {encoder_path}")
    model = _parse_module(encoder_path, key="sse.encoder", is_package=False)
    for statement in model.tree.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            if isinstance(statement.targets[0], ast.Name):
                target_name = statement.targets[0].id
                value_node = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target_name = statement.target.id
            value_node = statement.value
        if target_name != "SSE_CHANNEL_BY_DOMAIN_TYPE" or value_node is None:
            continue
        if not isinstance(value_node, ast.Dict):
            raise OracleUnavailable(
                f"{encoder_path}: SSE_CHANNEL_BY_DOMAIN_TYPE is not a literal dict"
            )
        try:
            mapping = ast.literal_eval(value_node)
        except (ValueError, SyntaxError) as exc:  # pragma: no cover - defensive
            raise OracleUnavailable(f"{encoder_path}: cannot literal_eval channel map") from exc
        if not isinstance(mapping, dict) or not mapping:
            raise OracleUnavailable(f"{encoder_path}: SSE channel map is empty")
        channels: set[str] = set()
        for key, value in mapping.items():
            if not isinstance(value, str):
                raise OracleUnavailable(
                    f"{encoder_path}: non-string SSE channel for {key!r}"
                )
            channels.add(value)
        return tuple(sorted(channels))
    raise OracleUnavailable(f"{encoder_path}: SSE_CHANNEL_BY_DOMAIN_TYPE not found")


def scan_error_codes(error_codes_path: Path) -> tuple[str, ...]:
    """Recompute the ``ErrorCode`` member-name set.

    Args:
        error_codes_path: ``_old/packages/core/src/wbtime_ai_core/error_codes.py``.

    Returns:
        Sorted enum member names.

    Raises:
        OracleUnavailable: If the file or the enum class is missing.
    """
    if not error_codes_path.is_file():
        raise OracleUnavailable(f"error_codes module not found: {error_codes_path}")
    model = _parse_module(error_codes_path, key="core.error_codes", is_package=False)
    for statement in model.tree.body:
        if not isinstance(statement, ast.ClassDef) or statement.name != "ErrorCode":
            continue
        members: list[str] = []
        for element in statement.body:
            if isinstance(element, ast.Assign):
                for target in element.targets:
                    if isinstance(target, ast.Name):
                        members.append(target.id)
            elif isinstance(element, ast.AnnAssign) and isinstance(element.target, ast.Name):
                members.append(element.target.id)
        if not members:
            raise OracleUnavailable(f"{error_codes_path}: ErrorCode has no members")
        return tuple(sorted(set(members)))
    raise OracleUnavailable(f"{error_codes_path}: class ErrorCode not found")


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


class LegacyOracle:
    """Read-only external oracle over the legacy source tree (O-A 主档).

    Attributes:
        legacy_root: Absolute legacy root; never written.
        timeout_s: Soft budget for the scan (between-phase deadline check).
    """

    def __init__(self, legacy_root: Path, *, timeout_s: float = 30.0) -> None:
        """Bind the oracle to a legacy root.

        Args:
            legacy_root: ``D:/WBT/WBTimeAI_old`` (read-only).
            timeout_s: Soft wall-clock budget for :meth:`scan`.
        """
        self.legacy_root = Path(legacy_root).expanduser().resolve()
        self.timeout_s = float(timeout_s)
        self._notes: list[str] = []

    # -- public API ---------------------------------------------------------

    def scan(self) -> LegacyFacts:
        """Recompute F1–F4 from ``_old`` and assert the tree stayed read-only.

        Returns:
            The recomputed :class:`LegacyFacts`.

        Raises:
            OracleUnavailable: When a face cannot be recomputed (missing sources,
                unparsable migrations, broken import graph).
            ReadonlyViolation: When the scanned subtrees changed during the scan.
        """
        if not self.legacy_root.is_dir():
            raise OracleUnavailable(f"legacy root not found: {self.legacy_root}")
        started = _monotonic()
        before = capture_readonly_snapshot(self.legacy_root)

        api_root = self.legacy_root / "apps/api/src/wbtime_ai_api"
        routers_dir = api_root / "routers"
        scanner = _RouterScanner(routers_dir)
        scanner.load()
        paths, operations = scanner.scan_app(api_root / "main.py")
        self._notes.extend(scanner.notes)
        self._check_deadline(started, "F1")

        walker = _MigrationWalker(self.legacy_root / "migrations/versions")
        state, chain = walker.run()
        self._notes.extend(state.notes)
        self._check_deadline(started, "F2")

        channels = scan_sse_channels(api_root / "sse/encoder.py")
        codes = scan_error_codes(
            self.legacy_root / "packages/core/src/wbtime_ai_core/error_codes.py"
        )
        self._check_deadline(started, "F3/F4")

        after = capture_readonly_snapshot(self.legacy_root)
        dirty = self.assert_readonly(before, after)
        if dirty:
            raise ReadonlyViolation(dirty)

        if state.opaque_sql:
            self._notes.append(
                f"F2: {len(state.opaque_sql)} non-DDL raw statements ignored "
                f"(e.g. {state.opaque_sql[0][:60]})"
            )
        if state.ignored:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(state.ignored.items()))
            self._notes.append(f"F2: constraint-level ops ignored (do not name objects): {summary}")
        self._notes.append(
            "F2: column *types* are NOT externally recomputed — rendering "
            "sa.String(255)->VARCHAR(255) / GUID->UUID / JSONType->JSONB needs the "
            "dialect compiler; recorded as an internal-only face instead of guessing"
        )

        return LegacyFacts(
            legacy_root=str(self.legacy_root),
            scanned_at=_utc_now_iso(),
            openapi_paths=paths,
            openapi_operations=operations,
            ddl_tables=tuple(sorted(state.tables)),
            ddl_columns=tuple(
                sorted((table, column) for table, columns in state.tables.items() for column in columns)
            ),
            ddl_indexes=tuple(sorted(state.indexes)),
            ddl_raw_indexes=tuple(
                sorted(
                    (
                        RawIndexFact(
                            name=name,
                            table=str(payload["table"]),
                            method=str(payload["method"]),
                            operator_class=payload.get("operator_class"),
                            sql=str(payload["sql"]),
                        )
                        for name, payload in state.raw_indexes.items()
                    ),
                    key=lambda fact: fact.name,
                )
            ),
            sse_channels=channels,
            error_codes=codes,
            notes=tuple(self._notes),
            chain=chain,
        )

    def assert_readonly(
        self, before: PycacheSnapshot, after: PycacheSnapshot | None = None
    ) -> list[str]:
        """Return the paths written inside the legacy tree (must be empty).

        Args:
            before: Snapshot taken before the scan.
            after: Snapshot taken after the scan; captured on demand when omitted.

        Returns:
            Sorted relative paths that appeared, disappeared or changed size/mtime,
            plus any newly created ``__pycache__`` entry.
        """
        if after is None:
            after = capture_readonly_snapshot(self.legacy_root)
        before_files = {entry[0]: entry[1:] for entry in before.files}
        after_files = {entry[0]: entry[1:] for entry in after.files}
        dirty: set[str] = set()
        for path in before_files:
            if path not in after_files:
                dirty.add(path)
            elif before_files[path] != after_files[path]:
                dirty.add(path)
        dirty.update(path for path in after_files if path not in before_files)
        before_pycache = set(before.pycache)
        dirty.update(path for path in after.pycache if path not in before_pycache)
        return sorted(dirty)

    # -- internals ----------------------------------------------------------

    @property
    def notes(self) -> tuple[str, ...]:
        """Honesty notes collected so far."""
        return tuple(self._notes)

    def _check_deadline(self, started: float, phase: str) -> None:
        """Raise :class:`OracleUnavailable` when the soft budget is exceeded."""
        elapsed = _monotonic() - started
        if elapsed > self.timeout_s:
            raise OracleUnavailable(
                f"scan budget exceeded after {phase} ({elapsed:.1f}s > {self.timeout_s:.1f}s)"
            )


def _monotonic() -> float:
    """Return a monotonic clock reading (seconds)."""
    import time

    return time.monotonic()


def _utc_now_iso() -> str:
    """Return ``YYYY-MM-DDTHH:MM:SSZ`` (K-9; mirrors ``_gate_io.utc_now_iso``)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 独立性自检（--assert-independent）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndependenceReport:
    """Result of the "oracle does not share a parser with the gate" check.

    Attributes:
        scanned: Files whose import graph was inspected.
        violations: ``"<file>: imports <module>"`` strings (empty = independent).
        runtime: Loaded ``sys.modules`` entries matching a forbidden prefix.
    """

    scanned: tuple[str, ...]
    violations: tuple[str, ...]
    runtime: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Whether the oracle is free of shared-parser imports."""
        return not self.violations and not self.runtime


def assert_independent(paths: Sequence[Path] | None = None) -> IndependenceReport:
    """Verify the oracle package never imports the extraction chain.

    Two layers:

    1. **static** — parse every module in ``scripts/oracle/`` and reject any
       import whose module path starts with :data:`FORBIDDEN_IMPORT_PREFIXES`
       or contains :data:`FORBIDDEN_IMPORT_FRAGMENTS` (``export_*``);
    2. **runtime** — reject forbidden modules already present in ``sys.modules``
       (catches transitive imports such as ``ddl.exporter``).

    Args:
        paths: Explicit file list; defaults to every ``*.py`` in this package.

    Returns:
        An :class:`IndependenceReport`; ``report.ok`` is the verdict.
    """
    package_dir = Path(__file__).resolve().parent
    files = list(paths) if paths is not None else sorted(package_dir.glob("*.py"))
    violations: list[str] = []
    scanned: list[str] = []
    for path in files:
        scanned.append(path.name)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:  # pragma: no cover - defensive
            violations.append(f"{path.name}: cannot parse ({exc})")
            continue
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if _is_forbidden_module(module):
                    violations.append(f"{path.name}: imports {module}")
    runtime: list[str] = []
    for name in sorted(sys.modules):
        if _is_forbidden_module(name):
            runtime.append(name)
    if any(name == "compare_openapi" for name in sys.modules):
        runtime.append("compare_openapi")
    return IndependenceReport(
        scanned=tuple(scanned), violations=tuple(sorted(set(violations))), runtime=tuple(sorted(set(runtime)))
    )


def _imported_modules(node: ast.AST) -> Iterator[str]:
    """Yield every module path imported by one AST node."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level:
            # ``from . import x`` / ``from .x import y`` — reconstruct the tail so
            # a relative import of the extraction chain is still caught.
            for alias in node.names:
                yield ("." * node.level) + "/".join(filter(None, (module, alias.name)))
            yield ("." * node.level) + module
        else:
            yield module
            for alias in node.names:
                yield f"{module}.{alias.name}" if module else alias.name


def _is_forbidden_module(module: str) -> bool:
    """Return ``True`` when ``module`` belongs to the product-generation chain."""
    normalized = module.replace("-", "_")
    segments = [segment for segment in normalized.replace("/", ".").split(".") if segment]
    if any(segment.startswith("export_") for segment in segments):
        return True
    dotted = ".".join(segments)
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        probe = prefix.replace("-", "_")
        if dotted == probe or dotted.startswith(probe + "."):
            return True
        probe_dots = probe.replace("_", ".")
        if dotted == probe_dots or dotted.startswith(probe_dots + "."):
            return True
    return False


# ---------------------------------------------------------------------------
# CLI（自检用；不是门禁）
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scanner standalone (diagnostics, not a gate).

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` on success, ``2`` on usage error, ``21`` when the oracle is
        unavailable, ``9`` when ``--assert-independent`` fails.
    """
    parser = argparse.ArgumentParser(
        prog="legacy_scan.py",
        description="Read-only external oracle over the legacy tree (F1-F4).",
    )
    parser.add_argument("--legacy-root", type=Path, default=None)
    parser.add_argument("--assert-independent", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    exit_code = 0
    if args.assert_independent:
        report = assert_independent()
        print(
            f"[oracle] independence: files={len(report.scanned)} "
            f"violations={len(report.violations)} runtime={len(report.runtime)}"
        )
        for violation in report.violations:
            print(f"[oracle]   VIOLATION {violation}")
        for module in report.runtime:
            print(f"[oracle]   RUNTIME-MODULE {module}")
        print(f"[oracle] independence verdict: {'INDEPENDENT' if report.ok else 'SHARED-PARSER'}")
        if not report.ok:
            exit_code = 9
        if args.legacy_root is None:
            return exit_code

    root = args.legacy_root
    if root is None:
        parser.error("--legacy-root is required unless only --assert-independent is used")
        return 2
    oracle = LegacyOracle(root, timeout_s=args.timeout)
    try:
        facts = oracle.scan()
    except (OracleUnavailable, ReadonlyViolation) as exc:
        print(f"[oracle] UNAVAILABLE {exc}")
        return 21
    if args.json:
        print(json.dumps(facts.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"[oracle] chain={'..'.join(facts.chain)} paths={len(facts.openapi_paths)} "
            f"operations={len(facts.openapi_operations)} tables={len(facts.ddl_tables)} "
            f"columns={len(facts.ddl_columns)} indexes={len(facts.ddl_indexes)} "
            f"raw_indexes={len(facts.ddl_raw_indexes)} "
            f"hnsw={len(facts.ddl_hnsw_names)} sse={len(facts.sse_channels)} "
            f"error_codes={len(facts.error_codes)}"
        )
        print(f"[oracle] hnsw={list(facts.ddl_hnsw_names)}")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - manual diagnostics
    raise SystemExit(main())
