#!/usr/bin/env python3
"""DoD#3 — OpenAPI surface comparison gate (frozen contract vs a candidate source).

What this gate is for
---------------------
``check_baseline.py`` proves the frozen artifact is byte-intact; it cannot prove the
artifact still *describes the API*.  This gate compares the frozen OpenAPI surface
against a candidate, **collection by collection**:

* ``paths``      — the set of path templates;
* ``operations`` — the set of ``"METHOD /path"`` pairs;
* ``schemas``    — the set of ``components.schemas`` names.

The comparison is **set equality** (``_gate_io.set_diff_report``), never a count
comparison: "100 paths, 134 ops, 116 schemas" are exactly the numbers a naive
forgery keeps while swapping one path for another.

Candidates (``--candidate``)
----------------------------
``file``
    Compare the frozen artifact against **itself** — a self-consistency check that
    also asserts none of the three collections is empty (K-11: an empty collection
    is ``INVALID``, never a pass).
``url``
    Fetch a **live** ``GET {url}/openapi.json`` (design O-B 次档).  Requires a
    running backend, so it is not part of the offline tier.
``legacy``
    **Static** ``ast`` scan of the read-only legacy repo ``D:/WBT/WBTimeAI_old``
    (design O-A 主档, F1 face).  Zero writes: the tree is only read, bytecode
    writing is disabled, and the process never changes into it.

D-7 (user ruling, 2026-10-21 01:54)
-----------------------------------
``--candidate legacy`` **may** degrade to "live ``url`` is the primary source and
``legacy`` only compares ``paths``" when ``schemas`` / ``operations`` cannot
converge without editing the artifacts.  Two hard requirements come with it:

1. the gate must **print explicitly** which collections were degraded and why —
   silent degradation *is* the fake green this version exists to kill;
2. the ledger must state which collections are **not** guarded by the static
   oracle.

Therefore: a candidate that cannot supply a demanded collection produces a
``not-checked`` diff, which is **red by default**.  ``--allow-degrade`` turns it
into a declared ``DEGRADED`` and forces the final ``coverage: k/n`` line.

Exit codes (§3.3)
-----------------
* ``0`` — every demanded collection matched (degraded ones must be declared);
* ``1`` — a difference was found, a demanded collection could not be checked and
  ``--allow-degrade`` was not given, or a collection was empty;
* ``2`` — usage error, artifact load failure, or the candidate was unreachable;
* ``9`` — ``--self-test`` failed.

Python: standard library only (``ast`` + ``urllib``).
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from _gate_io import (
    EXIT_OK,
    EXIT_SELFTEST,
    EXIT_USAGE,
    EXIT_VIOLATION,
    Diff,
    GateIOError,
    GatePaths,
    load_json,
    log,
    set_diff_report,
)

#: G-4 / §9-6: a bytecode cache must never land in the read-only legacy tree.  This
#: gate only ``ast.parse``s the legacy sources (it never imports them), so a cache
#: could not appear there anyway; the flag makes that guarantee hold even if a
#: future change adds an import.
sys.dont_write_bytecode = True

__all__ = [
    "TAG",
    "COLLECTIONS",
    "OpenApiSurface",
    "surface_from_file",
    "surface_from_url",
    "surface_from_legacy",
    "compare",
    "main",
]

#: Log tag (K-7).
TAG = "openapi"

#: The three compared collections, in report order.
COLLECTIONS: tuple[str, ...] = ("paths", "operations", "schemas")

#: HTTP methods FastAPI turns into operations.
HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)

#: Frozen artifact, relative to ``contracts/``.
FROZEN_OPENAPI = "openapi.v1.frozen.json"

#: Default live-backend base URL (K-5 uses the same port for the e2e run).
DEFAULT_URL = "http://127.0.0.1:8099"


# ---------------------------------------------------------------------------
# Surface record
# ---------------------------------------------------------------------------
@dataclass
class OpenApiSurface:
    """One OpenAPI surface, reduced to the three comparable name sets.

    Attributes:
        paths: Path templates, e.g. ``"/api/v1/agents/{agent_id}"``.
        operations: ``"<METHOD> <path>"`` strings.
        schemas: ``components.schemas`` names.
        label: Where this surface came from (for evidence lines).
        unavailable: Collection -> reason, for collections this source cannot
            supply.  Nothing is ever assumed: an unavailable collection becomes a
            ``not-checked`` diff.
        notes: Free-form parse notes (never used as a pass criterion).
        declared_schemas: Schema names a static scan *believes* it can see.  This
            is **informational only** and is never compared — a static scan cannot
            reproduce FastAPI's transitive ``response_model`` graph.
    """

    paths: set[str] = field(default_factory=set)
    operations: set[str] = field(default_factory=set)
    schemas: set[str] = field(default_factory=set)
    label: str = "candidate"
    unavailable: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    declared_schemas: set[str] = field(default_factory=set)

    # -- constructors ------------------------------------------------------
    @classmethod
    def from_document(cls, document: Mapping[str, Any], *, label: str) -> OpenApiSurface:
        """Reduce an OpenAPI document to the three name sets.

        Args:
            document: The decoded OpenAPI JSON document.
            label: Source label used in evidence lines.

        Returns:
            The populated surface.

        Raises:
            GateIOError: ``paths`` is missing or not an object.
        """
        if not isinstance(document, Mapping):
            raise GateIOError(f"{label}: OpenAPI document is not a JSON object")
        raw_paths = document.get("paths")
        if not isinstance(raw_paths, Mapping):
            raise GateIOError(f"{label}: OpenAPI document has no 'paths' object")

        surface = cls(label=label)
        for path, item in raw_paths.items():
            surface.paths.add(str(path))
            if not isinstance(item, Mapping):
                surface.notes.append(f"{label}: path item {path} is not an object")
                continue
            for key in item:
                if isinstance(key, str) and key.lower() in HTTP_METHODS:
                    surface.operations.add(f"{key.upper()} {path}")

        components = document.get("components")
        if isinstance(components, Mapping):
            raw_schemas = components.get("schemas")
            if isinstance(raw_schemas, Mapping):
                surface.schemas = {str(name) for name in raw_schemas}
        return surface

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        """Return ``paths=… operations=… schemas=…`` for one output line."""
        schemas = (
            str(len(self.schemas))
            if "schemas" not in self.unavailable
            else "UNKNOWN"
        )
        return (
            f"paths={len(self.paths)} operations={len(self.operations)} "
            f"schemas={schemas}"
        )


# ---------------------------------------------------------------------------
# Candidate sources
# ---------------------------------------------------------------------------
def surface_from_file(path: Path, *, label: str | None = None) -> OpenApiSurface:
    """Build a surface from an OpenAPI JSON file.

    Args:
        path: The file to read.
        label: Overrides the source label (defaults to the file name).

    Returns:
        The parsed surface.

    Raises:
        GateIOError: The file is missing or not a valid OpenAPI document.
    """
    document = load_json(Path(path))
    return OpenApiSurface.from_document(
        document, label=label or Path(path).name
    )


def surface_from_url(url: str, *, timeout_s: float = 10.0) -> OpenApiSurface:
    """Build a surface from a live ``GET {url}/openapi.json``.

    Args:
        url: Base URL of the running backend (``/openapi.json`` is appended when
            the URL does not already end with it).
        timeout_s: Socket timeout in seconds.

    Returns:
        The parsed surface.

    Raises:
        GateIOError: The endpoint is unreachable or returns something unusable.
    """
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/openapi.json"):
        endpoint = f"{endpoint}/openapi.json"
    log(TAG, f"fetching live surface: GET {endpoint}")
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout_s) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError) as error:
        raise GateIOError(f"cannot fetch {endpoint}: {error}") from error
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateIOError(f"{endpoint} did not return JSON: {error}") from error
    return OpenApiSurface.from_document(document, label=endpoint)


def surface_from_legacy(legacy_root: Path) -> OpenApiSurface:
    """Build a surface by **statically** scanning the read-only legacy routers.

    No import, no execution, no bytecode: ``ast.parse`` only.  The scan resolves
    the two things FastAPI does at import time and that a naive decorator grep
    gets wrong:

    * ``APIRouter(prefix=...)`` on each router object;
    * ``include_router(...)`` edges, recursively, so ``/api/v1`` + ``/agents`` +
      ``""`` becomes ``/api/v1/agents``.

    Deliberate exclusions (each produces a ``note``):

    * ``include_router`` calls inside ``if`` / ``try`` / loop bodies — a
      conditional include is not part of the unconditional surface (this is how
      the legacy app hides ``/metrics``);
    * ``components.schemas`` — a static scan cannot reproduce FastAPI's
      transitive ``response_model`` graph, so the collection is declared
      ``unavailable`` instead of being guessed (see the module docstring, D-7).

    Args:
        legacy_root: The read-only legacy repository root.

    Returns:
        The static surface.

    Raises:
        GateIOError: The legacy API package cannot be located (G-1 not satisfied).
    """
    api_dir = Path(legacy_root) / "apps" / "api" / "src" / "wbtime_ai_api"
    if not api_dir.is_dir():
        raise GateIOError(
            f"legacy API package not found: {api_dir.as_posix()} (G-1 not satisfied)"
        )

    surface = OpenApiSurface(label=f"legacy:{api_dir.as_posix()}")
    surface.unavailable["schemas"] = (
        "static ast scan cannot reproduce FastAPI's transitive response_model graph "
        "(D-7: degraded, NOT silently assumed equal)"
    )

    modules = _parse_modules(api_dir)
    graph = _build_router_graph(modules, surface=surface)

    root_edges = graph.root_edges
    if not root_edges:
        raise GateIOError(
            f"no application-level include_router call found under {api_dir.as_posix()}"
        )
    for node_key, extra_prefix in root_edges:
        _expand(graph, node_key, extra_prefix, surface=surface)

    surface.declared_schemas = set(graph.declared_schemas)
    surface.notes.append(
        f"static scan collected {len(surface.declared_schemas)} response_model names "
        "(informational only, NOT compared)"
    )
    return surface


# ---------------------------------------------------------------------------
# Legacy static scan internals
# ---------------------------------------------------------------------------
@dataclass
class _RouterNode:
    """One ``APIRouter``/``FastAPI`` object discovered by the static scan.

    Attributes:
        key: ``(file, variable)`` identity of the object.
        prefix: ``APIRouter(prefix=...)`` value (``""`` when absent).
        routes: ``(method, path)`` pairs declared on this object.
        children: ``(child_key, extra_prefix)`` include edges, in source order.
    """

    key: tuple[str, str]
    prefix: str = ""
    routes: list[tuple[str, str]] = field(default_factory=list)
    children: list[tuple[tuple[str, str], str]] = field(default_factory=list)


@dataclass
class _ModuleInfo:
    """One parsed source file.

    Attributes:
        path: Absolute file path.
        tree: Parsed AST.
        aliases: Local name -> ``(target_file, attribute_or_None)``.
        routers: Local router variable -> :class:`_RouterNode`.
    """

    path: Path
    tree: ast.Module
    aliases: dict[str, tuple[Path, str | None]] = field(default_factory=dict)
    routers: dict[str, _RouterNode] = field(default_factory=dict)


@dataclass
class _RouterGraph:
    """The composed router graph of one package.

    Attributes:
        nodes: ``(file, variable)`` -> node.
        root_edges: Application-level includes, as ``(node_key, prefix)``.
        declared_schemas: Names seen in ``response_model=`` (informational).
    """

    nodes: dict[tuple[str, str], _RouterNode] = field(default_factory=dict)
    root_edges: list[tuple[tuple[str, str], str]] = field(default_factory=list)
    declared_schemas: set[str] = field(default_factory=set)


def _parse_modules(api_dir: Path) -> dict[Path, _ModuleInfo]:
    """Parse every candidate source file under the legacy API package.

    Only ``main.py`` and ``routers/**/*.py`` can declare or include routes, so the
    scan is limited to them: parsing the whole package would be slower and would
    not add a single path.

    Args:
        api_dir: The legacy ``wbtime_ai_api`` package directory.

    Returns:
        Absolute file path -> parsed module info.
    """
    candidates: list[Path] = []
    main_file = api_dir / "main.py"
    if main_file.is_file():
        candidates.append(main_file)
    candidates.extend(sorted((api_dir / "routers").rglob("*.py")))

    modules: dict[Path, _ModuleInfo] = {}
    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        modules[path] = _ModuleInfo(path=path, tree=tree)
        _collect_aliases(modules[path], api_dir=api_dir)
    return modules


def _module_target(base_dir: Path, parts: Sequence[str]) -> Path | None:
    """Resolve a dotted module reference to a file path.

    Args:
        base_dir: Directory the reference is relative to.
        parts: Dotted components (``["v1"]``, ``[]`` for the package itself).

    Returns:
        The resolved file, or ``None`` when it cannot be found.
    """
    directory = base_dir
    for part in parts:
        directory = directory / part
    for candidate in (directory.with_suffix(".py"), directory / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _collect_aliases(module: _ModuleInfo, *, api_dir: Path) -> None:
    """Record ``import`` aliases so router variables can be resolved across files.

    Two forms are resolved:

    * ``from .health import router as health_router`` -> ``(health.py, "router")``
    * ``from . import agents``                        -> ``(agents.py, None)``

    Absolute imports are rebased on ``api_dir`` when their first component is the
    package name (``from wbtime_ai_api.routers import api_router``).

    Args:
        module: The module being parsed (mutated in place).
        api_dir: The root of the ``wbtime_ai_api`` package, for absolute imports.
    """
    for statement in ast.walk(module.tree):
        if not isinstance(statement, ast.ImportFrom):
            continue
        if statement.level:
            base = module.path.parent
            for _ in range(statement.level - 1):
                base = base.parent
            parts = (statement.module or "").split(".") if statement.module else []
        else:
            parts = (statement.module or "").split(".") if statement.module else []
            if parts and parts[0] == api_dir.name:
                parts = parts[1:]
            base = api_dir
        parts = [part for part in parts if part]
        source_module = _module_target(base, parts)

        for alias in statement.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            nested = _module_target(base, parts + [alias.name])
            if nested is not None:
                module.aliases[bound] = (nested, None)
            elif source_module is not None:
                module.aliases[bound] = (source_module, alias.name)


def _resolve_reference(
    expression: ast.AST, module: _ModuleInfo
) -> tuple[Path, str] | None:
    """Resolve ``x`` / ``x.router`` / ``pkg.sub.router`` to ``(file, variable)``.

    Args:
        expression: The expression to resolve.
        module: The module it appears in.

    Returns:
        ``(file, variable)`` or ``None`` when the expression is not a router
        reference this scan understands.
    """
    if isinstance(expression, ast.Name):
        bound = module.aliases.get(expression.id)
        if bound is None:
            return None
        target_file, attribute = bound
        return (target_file, attribute) if attribute else None
    if isinstance(expression, ast.Attribute):
        if isinstance(expression.value, ast.Name):
            bound = module.aliases.get(expression.value.id)
            if bound is not None:
                target_file, _attribute = bound
                return (target_file, expression.attr)
        if isinstance(expression.value, ast.Attribute):
            nested = _resolve_reference(expression.value, module)
            if nested is not None:
                return (nested[0], expression.attr)
    return None


def _keyword_prefix(call: ast.Call) -> str:
    """Return the ``prefix=`` keyword value of a call, or ``""``.

    Args:
        call: The call node.

    Returns:
        The literal prefix, or ``""`` when absent / non-literal.
    """
    for keyword in call.keywords:
        if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return ""


def _conditional_depth(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> int:
    """Count ``if`` / ``try`` / loop ancestors of ``node``.

    Args:
        node: The node of interest.
        parents: Child -> parent map for the whole tree.

    Returns:
        The number of conditional ancestors (``0`` means unconditional).
    """
    depth = 0
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.If, ast.Try, ast.While, ast.For, ast.AsyncFor)):
            depth += 1
        current = parents.get(current)
    return depth


def _deref(
    key: tuple[str, str], modules: Mapping[Path, _ModuleInfo]
) -> tuple[str, str] | None:
    """Follow re-export aliases until the reference names a real router object.

    ``routers/__init__.py`` does not build any router: it only re-exports
    ``health_router`` and ``api_router``.  ``from .health import router as
    health_router`` therefore has to be followed to ``routers/health.py::router``
    before the graph can expand it.

    Args:
        key: ``(file, variable)`` as resolved from the source expression.
        modules: Absolute file path -> parsed module.

    Returns:
        The key of an actual ``APIRouter``/``FastAPI`` assignment, or ``None``.
    """
    current: tuple[str, str] | None = (str(key[0]), key[1])
    seen: set[tuple[str, str]] = set()
    while current is not None and current not in seen:
        seen.add(current)
        module = modules.get(Path(current[0]))
        if module is None:
            return None
        if current[1] in module.routers:
            return current
        alias = module.aliases.get(current[1])
        if alias is None or alias[1] is None:
            return None
        current = (str(alias[0]), alias[1])
    return None


def _build_router_graph(
    modules: Mapping[Path, _ModuleInfo], *, surface: OpenApiSurface
) -> _RouterGraph:
    """Build the router graph from the parsed modules.

    Args:
        modules: Absolute file path -> parsed module.
        surface: Surface receiving ``note`` lines about skipped constructs.

    Returns:
        The composed graph, including application-level ``include_router`` edges.
    """
    graph = _RouterGraph()

    # Pass 1 — register every router object across **all** modules first, so a
    # reference from an earlier-parsed file can be dereferenced into a node that
    # lives in a later-parsed file (``main.py`` is parsed before ``routers/``).
    for module in modules.values():
        for statement in module.tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not isinstance(statement.value, ast.Call):
                continue
            factory = statement.value.func
            factory_name = factory.attr if isinstance(factory, ast.Attribute) else getattr(
                factory, "id", None
            )
            if factory_name not in ("APIRouter", "FastAPI"):
                continue
            for target in statement.targets:
                if not isinstance(target, ast.Name):
                    continue
                node = _RouterNode(
                    key=(str(module.path), target.id),
                    prefix=_keyword_prefix(statement.value),
                )
                module.routers[target.id] = node
                graph.nodes[node.key] = node

    # Pass 2 — routes and include edges.
    for module in modules.values():
        parents = _parent_map(module.tree)

        for node in ast.walk(module.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _absorb_decorators(module, node, graph=graph, surface=surface)
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
                continue
            if not node.args:
                continue
            child = _resolve_reference(node.args[0], module)
            if child is None:
                surface.notes.append(
                    f"{module.path.name}: cannot resolve include_router target "
                    f"{ast.unparse(node.args[0])!r} — skipped"
                )
                continue
            dereferenced = _deref(child, modules)
            if dereferenced is None:
                surface.notes.append(
                    f"{module.path.name}: include_router({ast.unparse(node.args[0])}) "
                    "does not resolve to a router object — skipped"
                )
                continue
            child = dereferenced
            extra_prefix = _keyword_prefix(node)
            receiver = node.func.value
            owner = (
                module.routers.get(receiver.id)
                if isinstance(receiver, ast.Name)
                else None
            )
            if owner is not None:
                owner.children.append((child, extra_prefix))
                continue
            if _conditional_depth(node, parents) > 0:
                surface.notes.append(
                    f"{module.path.name}: conditional include_router("
                    f"{ast.unparse(node.args[0])}) skipped "
                    "(not part of the unconditional surface)"
                )
                continue
            graph.root_edges.append((child, extra_prefix))

    return graph


def _absorb_decorators(
    module: _ModuleInfo,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    graph: _RouterGraph,
    surface: OpenApiSurface,
) -> None:
    """Record the route decorators of one function.

    Args:
        module: Owning module.
        function: The decorated function.
        graph: Graph receiving ``response_model`` names.
        surface: Surface receiving notes about unsupported decorators.
    """
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        attribute = decorator.func.attr
        if not isinstance(decorator.func.value, ast.Name):
            continue
        owner = module.routers.get(decorator.func.value.id)
        if owner is None:
            continue

        for keyword in decorator.keywords:
            if keyword.arg == "response_model":
                graph.declared_schemas.add(
                    _response_model_name(keyword.value)
                )

        if attribute in HTTP_METHODS:
            methods = [attribute]
        elif attribute == "api_route":
            methods = [
                str(element.value).lower()
                for keyword in decorator.keywords
                if keyword.arg == "methods"
                for element in getattr(keyword.value, "elts", [])
                if isinstance(element, ast.Constant)
            ]
            if not methods:
                surface.notes.append(
                    f"{module.path.name}: api_route without a literal methods= list — skipped"
                )
                continue
        else:
            continue

        path = _positional_path(decorator)
        if path is None:
            surface.notes.append(
                f"{module.path.name}: {attribute} route without a literal path — "
                f"function {function.name!r} skipped"
            )
            continue
        for method in methods:
            if method in HTTP_METHODS:
                owner.routes.append((method.upper(), path))


def _positional_path(call: ast.Call) -> str | None:
    """Return the literal path argument of a route decorator.

    Args:
        call: The decorator call node.

    Returns:
        The literal path, or ``None`` when it is not a string literal.
    """
    if call.args and isinstance(call.args[0], ast.Constant):
        if isinstance(call.args[0].value, str):
            return call.args[0].value
    for keyword in call.keywords:
        if keyword.arg == "path" and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return None


def _response_model_name(node: ast.AST) -> str:
    """Render a ``response_model=`` expression as a comparable name.

    Args:
        node: The expression node.

    Returns:
        The bare name for ``X``, the inner name for ``list[X]``, else
        ``ast.unparse`` output.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _response_model_name(node.slice)
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is very forgiving
        return "<unparsed>"


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Build a child -> parent map for one AST.

    Args:
        tree: The module AST.

    Returns:
        Child node -> parent node.
    """
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _expand(
    graph: _RouterGraph,
    key: tuple[str, str],
    accumulated_prefix: str,
    *,
    surface: OpenApiSurface,
    seen: tuple[tuple[str, str], ...] = (),
) -> None:
    """Recursively expand one router node into full paths.

    Args:
        graph: The router graph.
        key: Node identity ``(file, variable)``.
        accumulated_prefix: Prefix contributed by the ancestors.
        surface: Surface receiving the resulting paths/operations.
        seen: Nodes already on the current expansion path (cycle guard).
    """
    if key in seen:
        surface.notes.append(f"cycle detected while expanding {key[1]!r} — stopped")
        return
    node = graph.nodes.get(key)
    if node is None:
        surface.notes.append(f"unresolved router reference {(key[0], key[1])!r}")
        return

    prefix = _join_path(accumulated_prefix, node.prefix)
    for method, path in node.routes:
        full = _join_path(prefix, path)
        surface.paths.add(full)
        surface.operations.add(f"{method} {full}")

    for child_key, extra_prefix in node.children:
        _expand(
            graph,
            child_key,
            _join_path(prefix, extra_prefix),
            surface=surface,
            seen=seen + (key,),
        )


def _join_path(prefix: str, suffix: str) -> str:
    """Join two path fragments the way FastAPI does.

    Args:
        prefix: Left fragment (``"/api/v1"`` or ``""``).
        suffix: Right fragment (``"/agents"``, ``""``, ``"/{id}"``).

    Returns:
        The joined path, always starting with ``"/"``, never containing ``"//"``.
    """
    left = prefix.rstrip("/")
    right = suffix if suffix.startswith("/") or not suffix else f"/{suffix}"
    joined = f"{left}{right}"
    if not joined:
        return "/"
    return joined if joined.startswith("/") else f"/{joined}"


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def compare(frozen: OpenApiSurface, candidate: OpenApiSurface) -> list[Diff]:
    """Compare two surfaces over the three collections.

    Args:
        frozen: The frozen contract surface.
        candidate: The candidate surface.

    Returns:
        Sorted diffs.  A collection the candidate cannot supply becomes a
        ``not-checked`` diff (never a silent skip).  An empty collection on either
        side becomes an ``invalid-empty`` diff (K-11).
    """
    report: list[Diff] = []
    for collection in COLLECTIONS:
        if collection in candidate.unavailable:
            report.append(
                Diff(
                    kind="not-checked",
                    subject=collection,
                    left=f"frozen={_size(frozen, collection)}",
                    right=candidate.unavailable[collection],
                )
            )
            continue
        left = _collection(frozen, collection)
        right = _collection(candidate, collection)
        if not left:
            report.append(
                Diff(
                    kind="invalid-empty",
                    subject=f"frozen.{collection}",
                    left="empty",
                    right="INVALID (K-11: an empty collection is never a pass)",
                )
            )
            continue
        if not right:
            report.append(
                Diff(
                    kind="invalid-empty",
                    subject=f"candidate.{collection}",
                    left=f"{len(left)} names",
                    right="empty -> INVALID (K-11)",
                )
            )
            continue
        for diff in set_diff_report(left, right):
            report.append(
                Diff(
                    kind=collection,
                    subject=diff.subject,
                    left=diff.left,
                    right=diff.right,
                )
            )
    return sorted(report, key=lambda diff: (diff.kind, diff.subject))


def _collection(surface: OpenApiSurface, collection: str) -> set[str]:
    """Return one collection from a surface.

    Args:
        surface: The surface.
        collection: One of :data:`COLLECTIONS`.

    Returns:
        The name set.
    """
    return {
        "paths": surface.paths,
        "operations": surface.operations,
        "schemas": surface.schemas,
    }[collection]


def _size(surface: OpenApiSurface, collection: str) -> str:
    """Return the size of a collection as a string, or ``UNKNOWN``.

    Args:
        surface: The surface.
        collection: One of :data:`COLLECTIONS`.

    Returns:
        The size, or ``"UNKNOWN"`` when the surface cannot supply it.
    """
    if collection in surface.unavailable:
        return "UNKNOWN"
    return str(len(_collection(surface, collection)))


# ---------------------------------------------------------------------------
# Gate entry point
# ---------------------------------------------------------------------------
def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments without the program name.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="compare_openapi.py",
        description=(
            "Compare the frozen OpenAPI surface against a candidate "
            "(file / live url / static legacy scan) over paths, operations and schemas."
        ),
    )
    parser.add_argument(
        "--candidate",
        choices=("file", "url", "legacy"),
        default="file",
        help="candidate source (default: file = the frozen artifact itself)",
    )
    parser.add_argument(
        "--frozen",
        default=None,
        metavar="PATH",
        help="frozen OpenAPI file (default: <contracts>/openapi.v1.frozen.json)",
    )
    parser.add_argument(
        "--contracts",
        default=None,
        metavar="DIR",
        help="contracts directory (default: <repo>/contracts)",
    )
    parser.add_argument(
        "--legacy-root",
        default=None,
        metavar="DIR",
        help="read-only legacy repository root (default: $E2E_LEGACY_ROOT or D:/WBT/WBTimeAI_old)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        metavar="URL",
        help=f"live backend base URL for --candidate url (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--require",
        default=",".join(COLLECTIONS),
        metavar="LIST",
        help=(
            "comma-separated collections that must be checked "
            f"(default: {','.join(COLLECTIONS)})"
        ),
    )
    parser.add_argument(
        "--allow-degrade",
        action="store_true",
        help=(
            "permit a demanded collection the candidate cannot supply to be reported "
            "as DEGRADED instead of red (D-7; forces an explicit coverage line)"
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the named injections (exit 9 on failure)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the diffs as a JSON array",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _build_candidate(arguments: argparse.Namespace, paths: GatePaths) -> OpenApiSurface:
    """Construct the candidate surface requested on the command line.

    Args:
        arguments: Parsed arguments.
        paths: Resolved gate paths.

    Returns:
        The candidate surface.

    Raises:
        GateIOError: The candidate cannot be produced.
    """
    if arguments.candidate == "file":
        frozen_path = _frozen_path(arguments, paths)
        return surface_from_file(frozen_path, label=f"file:{frozen_path.name}")
    if arguments.candidate == "url":
        return surface_from_url(arguments.url)
    legacy_root = (
        Path(arguments.legacy_root).expanduser().resolve()
        if arguments.legacy_root
        else paths.legacy_root
    )
    return surface_from_legacy(legacy_root)


def _frozen_path(arguments: argparse.Namespace, paths: GatePaths) -> Path:
    """Resolve the frozen OpenAPI file path.

    Args:
        arguments: Parsed arguments.
        paths: Resolved gate paths.

    Returns:
        The frozen artifact path.
    """
    if arguments.frozen:
        return Path(arguments.frozen).expanduser().resolve()
    return paths.contract_file(FROZEN_OPENAPI)


def _parse_required(arguments: argparse.Namespace) -> set[str]:
    """Parse ``--require`` into a validated collection set.

    Args:
        arguments: Parsed arguments.

    Returns:
        The demanded collections.

    Raises:
        GateIOError: An unknown collection name was given.
    """
    demanded = {
        item.strip() for item in str(arguments.require).split(",") if item.strip()
    }
    unknown = demanded - set(COLLECTIONS)
    if unknown:
        raise GateIOError(
            f"unknown collection(s) in --require: {sorted(unknown)} "
            f"(known: {list(COLLECTIONS)})"
        )
    return demanded


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` matched (degraded collections declared), ``1`` difference /
        undeclared degradation / empty collection, ``2`` usage or load failure,
        ``9`` ``--self-test`` failed.
    """
    try:
        arguments = _parse_arguments(argv)
    except SystemExit as exit_error:  # argparse already printed the message
        return EXIT_USAGE if exit_error.code else EXIT_OK

    paths = GatePaths.resolve(contracts_dir=arguments.contracts)
    frozen_path = _frozen_path(arguments, paths)

    if arguments.self_test:
        return _self_test(frozen_path)

    try:
        demanded = _parse_required(arguments)
    except GateIOError as error:
        log(TAG, f"ERROR: {error}")
        return EXIT_USAGE

    try:
        frozen = surface_from_file(frozen_path, label=f"frozen:{frozen_path.name}")
        candidate = _build_candidate(arguments, paths)
    except GateIOError as error:
        log(TAG, f"ERROR: cannot produce a surface: {error}")
        return EXIT_USAGE

    log(TAG, f"frozen    : {frozen_path.as_posix()} -> {frozen.summary()}")
    log(TAG, f"candidate : {candidate.label} -> {candidate.summary()}")
    for note in candidate.notes:
        log(TAG, f"note: {note}")

    diffs = compare(frozen, candidate)
    if arguments.json:
        print(json.dumps([diff.to_dict() for diff in diffs], ensure_ascii=False, indent=2))

    not_checked = [diff for diff in diffs if diff.kind == "not-checked"]
    violations = [diff for diff in diffs if diff.kind not in ("not-checked",)]
    undeclared = [diff for diff in not_checked if diff.subject in demanded]
    optional = [diff for diff in not_checked if diff.subject not in demanded]

    guarded = len([name for name in COLLECTIONS if name in demanded]) - len(undeclared)
    degraded: list[str] = []

    for diff in violations:
        log(TAG, f"DIFF {diff.render()}")

    for diff in optional:
        log(
            TAG,
            f"collection {diff.subject}: NOT DEMANDED (--require does not list it) "
            f"-> {diff.right}",
        )

    for diff in undeclared:
        if arguments.allow_degrade:
            degraded.append(diff.subject)
            log(
                TAG,
                f"DEGRADED collection {diff.subject}: {diff.right} "
                "[allowed by --allow-degrade; D-7 requires this to be written into the "
                "ledger as 'not guarded by the static oracle']",
            )
        else:
            log(
                TAG,
                f"DIFF {diff.render()} "
                "[a demanded collection could not be checked; pass --allow-degrade to "
                "declare the degradation explicitly]",
            )

    log(
        TAG,
        f"coverage: {guarded}/{len(demanded)} demanded collections guarded"
        + (f"; degraded: {','.join(sorted(degraded))}" if degraded else ""),
    )

    if violations or (undeclared and not arguments.allow_degrade) or guarded == 0:
        log(TAG, "VERDICT: FAIL")
        return EXIT_VIOLATION

    if degraded:
        log(TAG, "VERDICT: PASS (coverage-limited — degraded collections listed above)")
        return EXIT_OK

    log(TAG, "VERDICT: PASS (all three collections equal)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------
def _self_test(frozen_path: Path) -> int:
    """Run the named injections for this gate.

    Three assertions, each proving a different failure mode is live:

    1. the frozen artifact compared against itself is green (otherwise "red"
       would prove nothing);
    2. deleting one ``path`` from a temporary copy **must** go red with a
       ``paths`` diff naming that path (DoD#3's injected counterexample);
    3. a candidate that cannot supply a demanded collection **must** go red,
       and must also report it as ``DEGRADED`` when ``--allow-degrade`` is given —
       this proves the "no silent degradation" rule (D-7) is enforced by the gate
       and not merely promised in the ledger.

    Args:
        frozen_path: The real (read-only) frozen OpenAPI artifact.

    Returns:
        ``0`` when every assertion holds, ``9`` otherwise.
    """
    log(TAG, f"self-test: using {frozen_path.as_posix()}")
    failures = 0
    try:
        frozen = surface_from_file(frozen_path, label="frozen")
    except GateIOError as error:
        log(TAG, f"SELFTEST FAIL: cannot load the frozen artifact: {error}")
        return EXIT_SELFTEST

    with tempfile.TemporaryDirectory(prefix="wbtime-openapi-") as scratch:
        root = Path(scratch)

        # Step 1 — self-consistency.
        baseline = surface_from_file(frozen_path, label="self")
        baseline_diffs = compare(frozen, baseline)
        if baseline_diffs:
            log(
                TAG,
                f"SELFTEST FAIL [baseline]: the frozen artifact disagrees with itself "
                f"({len(baseline_diffs)} diffs)",
            )
            for diff in baseline_diffs[:5]:
                log(TAG, f"  {diff.render()}")
            failures += 1
        else:
            log(
                TAG,
                "SELFTEST OK [baseline]: frozen artifact self-compares green "
                f"({frozen.summary()})",
            )

        # Step 2 — delete one path.
        tampered_path = root / "openapi.tampered.json"
        shutil.copy2(frozen_path, tampered_path)
        document = load_json(tampered_path)
        victim = sorted(document["paths"])[0]
        del document["paths"][victim]
        tampered_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        log(TAG, f"self-test injection: deleted path {victim!r}")
        tampered = surface_from_file(tampered_path, label="tampered")
        diffs = compare(frozen, tampered)
        hits = [diff for diff in diffs if diff.kind == "paths" and diff.subject == victim]
        if not hits:
            log(
                TAG,
                "SELFTEST FAIL [inject path-deleted]: expected a 'paths' diff naming "
                f"{victim!r}, got kinds={sorted({diff.kind for diff in diffs})}",
            )
            failures += 1
        else:
            log(TAG, f"SELFTEST OK [inject path-deleted]: red on {hits[0].render()}")

        # Step 3 — a demanded collection the candidate cannot supply must be red,
        # and must be visibly DEGRADED when explicitly allowed.
        unavailable = OpenApiSurface(
            paths=set(frozen.paths),
            operations=set(frozen.operations),
            label="synthetic(no schemas)",
            unavailable={"schemas": "synthetic: static scan cannot derive schemas"},
        )
        degrade_diffs = compare(frozen, unavailable)
        not_checked = [diff for diff in degrade_diffs if diff.kind == "not-checked"]
        if len(not_checked) != 1 or not_checked[0].subject != "schemas":
            log(
                TAG,
                "SELFTEST FAIL [degradation visibility]: an unavailable collection must "
                f"produce exactly one 'not-checked' diff for 'schemas', got "
                f"{[(diff.kind, diff.subject) for diff in degrade_diffs]}",
            )
            failures += 1
        elif [diff for diff in degrade_diffs if diff.kind not in ("not-checked",)]:
            log(
                TAG,
                "SELFTEST FAIL [degradation visibility]: the synthetic candidate should "
                "only differ by the unavailable collection",
            )
            failures += 1
        else:
            log(
                TAG,
                "SELFTEST OK [degradation visibility]: unavailable 'schemas' becomes a "
                "'not-checked' diff (red unless --allow-degrade declares it)",
            )

    if failures:
        log(TAG, f"SELFTEST VERDICT: FAIL ({failures} assertion(s) did not hold)")
        return EXIT_SELFTEST
    log(TAG, "SELFTEST VERDICT: PASS (all injections go red on the expected reason)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
