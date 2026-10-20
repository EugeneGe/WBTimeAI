"""C-04b exporter: freeze the 30 unified error codes.

Produces ``contracts/errors.json`` -- every :class:`ErrorCode` literal with the
HTTP status it actually resolves to at runtime, the exception class that raises
it, and a description.

How the status is resolved (measured, not looked up in one table)
----------------------------------------------------------------
``register_exception_handlers`` computes the status of a domain error as::

    status_code = _STATUS_BY_CODE.get(exc.code, exc.status_code)

so the resolution is a chain of three real inputs, in this order:

1. ``apps/api/src/wbtime_ai_api/errors.py::_STATUS_BY_CODE`` -- 27 entries, the
   operative API-layer map;
2. ``DomainError.status_code``, i.e. the exception class's own default
   (``packages/core/src/wbtime_ai_core/exception.py`` + ``error.py``);
3. the **call-site override** ``raise DomainError(..., status_code=N)``, read by
   AST-scanning the legacy source tree (no regex guessing: only literal
   ``code=ErrorCode.X`` / ``status_code=N`` keyword arguments are recorded).

Step 3 matters: ``DEPENDENCY_MISSING`` is in none of the first two sources, yet
production code mostly raises it with an explicit ``status_code=503`` and a
legacy integration test pins ``503`` + ``{"code": "DEPENDENCY_MISSING"}``
(``tests/integration/test_api_2c_surface.py::test_workspace_files_503_when_unassembled``).
Reporting ``null`` there would have been wrong; reporting a *guessed* 500 would
have been worse.  The measured answer is 503, tagged
``http_status_source = "call_site_override"`` and listing every raise site.

Per-call-site resolution -- the status is **not** one global constant
---------------------------------------------------------------------
A call-site override is a property of the *site*, not of the code, so the same
code can reach the wire with different statuses.  ``DEPENDENCY_MISSING`` is
exactly that case: **8** sites pass ``status_code=503``, **2** pass nothing and
therefore fall back to ``DomainError.status_code`` (**500**)
(``knowledge/parser/base.py::missing_dependency_error`` -- shared by the pdf /
docx / html parsers -- and ``plugin/marketplace/serialize.py::_yaml``).  A user
who installs the knowledge package without ``pypdf`` therefore gets **500** from
``POST .../files``, not 503.

The artifact must not hide that split.  For every code this exporter therefore
publishes, in addition to the headline ``http_status``:

* ``http_status_uniform`` -- ``true`` only when *every* raise site resolves to
  the same status, ``false`` when they disagree, ``null`` when the code has no
  raise site at all (nothing to judge, so the field refuses to answer);
* ``http_status_distribution`` -- ``{"<status>": <site count>}``, the measured
  split (``{"500": 2, "503": 8}`` for ``DEPENDENCY_MISSING``);
* ``http_status_default_without_override`` -- the status a site gets when it
  passes no ``status_code`` (500 for codes with no dedicated exception class);
* ``http_status_inconsistent_call_sites`` -- the sites that resolve to something
  other than the headline ``http_status`` (``[]`` when uniform);
* ``http_status_by_call_site_resolved`` -- every site with both its declared
  ``status_code`` and the status it actually resolves to, plus which link of the
  chain decided it;
* ``note`` -- a one-line warning whenever the headline value is *not* universal.

``meta.non_uniform_codes`` summarises which codes are split, and the split is
**frozen** in :data:`EXPECTED_NON_UNIFORM_CODES`, so neither a silently widened
disagreement nor a silently "cleaned up" table can pass the export.

Nothing is taken from ``docs/00-整体设计.md`` -- that table is known to be out of
date (it says 400 for ``VALIDATION_ERROR``; the code says 422).

Honest gaps (registered, not patched over)
------------------------------------------
``exception.py`` declares **7** exception classes, plus ``DomainError`` (which
carries ``ErrorCode.UNKNOWN``): **8** of the 30 codes have a dedicated class, the
other **22** do not.  ``python_exception`` is ``null`` for those 22 and
``python_exception_unmapped`` is ``true``; the list is published under
``meta.codes_without_exception_class`` and registered in ``contracts/README.md``.

Run under the legacy ``.venv`` interpreter (``run.py export`` re-executes).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import _bootstrap
import canonical
import hashes

__all__ = [
    "NAME",
    "DESCRIPTION",
    "OUTPUT_NAME",
    "EXPECTED_CODE_COUNT",
    "EXPECTED_EXCEPTION_CLASS_COUNT",
    "EXPECTED_API_STATUS_MAP_SIZE",
    "EXPECTED_CALL_SITE_RESOLVED",
    "EXPECTED_NON_UNIFORM_CODES",
    "DESCRIPTIONS",
    "ErrorCodeFreezeError",
    "export",
]

#: Registry name used by ``run.py --only``.
NAME = "errors"

#: Human readable description shown by ``run.py export``.
DESCRIPTION = "Freeze the 30 ErrorCode literals into contracts/errors.json"

OUTPUT_NAME = "errors.json"

#: Frozen expectations (measured against the legacy tree, never guessed).
EXPECTED_CODE_COUNT = 30
EXPECTED_EXCEPTION_CLASS_COUNT = 7
EXPECTED_API_STATUS_MAP_SIZE = 27
#: Codes that no map / no exception class resolves, but whose raise sites agree
#: on one explicit ``status_code``.  Frozen so a silent change fails the export.
EXPECTED_CALL_SITE_RESOLVED: dict[str, int] = {"DEPENDENCY_MISSING": 503}
#: Codes whose raise sites do **not** all resolve to the same HTTP status, with
#: the measured per-status site counts.  This is the D-1 regression gate: the
#: single entry says "8 sites emit 503, 2 emit 500", and any change to that split
#: (a new raise site, a removed override, a patched default) fails the export
#: instead of being silently re-labelled as a uniform 503.
EXPECTED_NON_UNIFORM_CODES: dict[str, dict[str, int]] = {
    "DEPENDENCY_MISSING": {"500": 2, "503": 8},
}

#: Human-written one-line descriptions, keyed by ``ErrorCode`` literal.
#:
#: Provenance: ``source: manual``.  Statuses are *measured*; descriptions are
#: editorial text because the legacy enum carries no machine-readable
#: description.  Where ``exception.py`` declares a class for the code, its
#: docstring is recorded separately as ``exception_docstring``.
DESCRIPTIONS: dict[str, str] = {
    "UNKNOWN": "未分类错误的兜底码（框架层 HTTPException 无对应码时回落）。",
    "INTERNAL_ERROR": "服务端未预期错误，由兜底异常处理器产出。",
    "VALIDATION_ERROR": "请求参数 / 数据校验失败；FastAPI RequestValidationError 亦映射到此码。",
    "NOT_FOUND": "资源不存在。",
    "METHOD_NOT_ALLOWED": "HTTP 方法不被该路径允许。",
    "CONFLICT": "资源状态冲突（版本、唯一性等）。",
    "PERMISSION_DENIED": "已认证但权限不足。",
    "UNAUTHORIZED": "未认证或凭证缺失 / 无效。",
    "NOT_IMPLEMENTED": "功能尚未实现（骨架路由占位、Feature Flag 降级）。",
    "CONFIGURATION_ERROR": "配置非法或缺失。",
    "DEPENDENCY_MISSING": (
        "可选依赖 / 能力未装配；非静默降级，须显式上报。"
        "状态由 call-site 决定：8 处显式 503，2 处未传 status_code 的构造点回落 500"
        "（见 http_status_uniform=false）。"
    ),
    "AUTH_INVALID_CREDENTIALS": "登录凭证（用户名 / 密码等）错误。",
    "AUTH_TOKEN_EXPIRED": "访问令牌已过期。",
    "AUTH_TOKEN_INVALID": "访问令牌非法（签名 / 格式错误）。",
    "AUTH_TOKEN_REVOKED": "访问令牌已撤销。",
    "AUTH_ACCOUNT_LOCKED": "账号已锁定。",
    "TENANT_NOT_FOUND": "租户不存在。",
    "USER_NOT_FOUND": "用户不存在。",
    "USER_ALREADY_EXISTS": "用户已存在（唯一性冲突）。",
    "ORGANIZATION_NOT_FOUND": "组织不存在。",
    "WORKSPACE_NOT_FOUND": "工作空间不存在。",
    "TASK_NOT_FOUND": "任务不存在。",
    "CREDENTIAL_NOT_FOUND": "凭证记录不存在。",
    "RESOURCE_LIMIT_EXCEEDED": "执行期资源限额超限（并行度 / 产物 / 等待队列）。",
    "MAX_ITERATIONS": "Agent 迭代次数达到上限。",
    "CONTEXT_LENGTH_EXCEEDED": "上下文长度超出模型窗口。",
    "TOOL_TIMEOUT": "工具调用超时。",
    "IDEMPOTENCY_KEY_REUSE": "幂等键复用但请求内容不一致。",
    "HEARTBEAT_TIMEOUT": "心跳超时（执行端失联）。",
    "EVENT_CURSOR_EXPIRED": "事件续读游标已过期（引用序号低于保留窗口低水位）。",
}


class ErrorCodeFreezeError(RuntimeError):
    """Raised when the error-code table diverges from the frozen baseline."""


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


def _collect_exception_classes() -> list[dict[str, Any]]:
    """Import and describe every exception class that carries an ``ErrorCode``.

    ``DomainError`` (``wbtime_ai_core/error.py``) is included because it is the
    class that actually carries ``ErrorCode.UNKNOWN`` as its default; the seven
    classes from ``wbtime_ai_core/exception.py`` are appended on top of it.

    Returns:
        One entry per class, least specific first.
    """
    from wbtime_ai_core import exception as exception_module  # noqa: PLC0415
    from wbtime_ai_core.error import DomainError  # noqa: PLC0415

    classes: list[type[DomainError]] = [DomainError]
    for name in exception_module.__all__:
        candidate = getattr(exception_module, name)
        if isinstance(candidate, type) and issubclass(candidate, DomainError):
            classes.append(candidate)

    described: list[dict[str, Any]] = []
    for cls in classes:
        docstring = (cls.__doc__ or "").strip().splitlines()
        described.append(
            {
                "class": cls.__name__,
                "module": cls.__module__,
                "code": str(cls.code),
                "http_status": int(cls.status_code),
                "message": getattr(cls, "message", None),
                "base": cls.__mro__[1].__name__ if len(cls.__mro__) > 1 else None,
                "docstring": docstring[0] if docstring else None,
            }
        )
    return described


def _pick_exception(code: str, described: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most specific exception class carrying ``code``.

    Args:
        code: ``ErrorCode`` literal.
        described: Output of :func:`_collect_exception_classes`.

    Returns:
        The last matching entry (most derived), or ``None``.
    """
    chosen: dict[str, Any] | None = None
    for entry in described:
        if entry["code"] == code:
            chosen = entry
    return chosen


# ---------------------------------------------------------------------------
# Call-site overrides (AST scan, never regex)
# ---------------------------------------------------------------------------


def _scan_roots(source: str) -> list[Path]:
    """Return the source roots scanned for ``DomainError`` construction sites.

    Args:
        source: Normalised legacy source root.

    Returns:
        ``<source>/packages/*/src`` (sorted) then ``<source>/apps/*/src`` for the
        three app names, restricted to directories that exist.
    """
    root = Path(source)
    roots: list[Path] = []
    packages = root / "packages"
    if packages.is_dir():
        for child in sorted(packages.iterdir(), key=lambda path: path.name):
            candidate = child / "src"
            if child.is_dir() and candidate.is_dir():
                roots.append(candidate)
    for app_name in ("api", "cli", "worker"):
        candidate = root / "apps" / app_name / "src"
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _error_code_of(call: ast.Call) -> str | None:
    """Return the ``ErrorCode`` literal passed as ``code=`` to ``call``.

    Only the explicit form ``code=ErrorCode.<NAME>`` is recognised; anything
    dynamic (a variable, ``ErrorCode`` member passed positionally, …) is ignored
    rather than guessed.

    Args:
        call: An AST call node.

    Returns:
        The member name, or ``None``.
    """
    for keyword in call.keywords:
        if keyword.arg != "code":
            continue
        value = keyword.value
        if not isinstance(value, ast.Attribute):
            continue
        owner = value.value
        if isinstance(owner, ast.Name) and owner.id == "ErrorCode":
            return value.attr
    return None


def _status_code_of(call: ast.Call) -> int | None:
    """Return the literal ``status_code=`` passed to ``call``, when it is an int.

    Args:
        call: An AST call node.

    Returns:
        The integer status, or ``None`` when absent / non-literal.
    """
    for keyword in call.keywords:
        if keyword.arg != "status_code":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return int(value.value)
    return None


def _scan_call_sites(source: str) -> dict[str, list[dict[str, Any]]]:
    """Find every ``ErrorCode``-carrying construction site in the legacy tree.

    A "call site" is any call passing ``code=ErrorCode.<NAME>`` -- both
    ``raise DomainError(...)`` statements and factory helpers that *return* one
    (e.g. ``missing_dependency_error()``) are captured, because both decide the
    status that eventually reaches the wire.

    Files that fail to parse are skipped and counted, never silently trusted.

    Args:
        source: Normalised legacy source root.

    Returns:
        ``{code: [{"module", "line", "status_code"}, ...]}`` in path order.
    """
    sites: dict[str, list[dict[str, Any]]] = {}
    root = Path(source)
    for scan_root in _scan_roots(source):
        for path in sorted(scan_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            relative = path.relative_to(root).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                code = _error_code_of(node)
                if code is None:
                    continue
                sites.setdefault(code, []).append(
                    {
                        "module": relative,
                        "line": int(getattr(node, "lineno", 0)),
                        "status_code": _status_code_of(node),
                    }
                )
    return sites


# ---------------------------------------------------------------------------
# Per-call-site status resolution (D-1: never publish "all sites agree")
# ---------------------------------------------------------------------------


def _domain_error_default_status(described: list[dict[str, Any]]) -> int:
    """Return ``DomainError.status_code`` -- the status a bare construction gets.

    This is the class whose default decides the wire status for the 22 codes that
    have no dedicated exception class (e.g. ``DEPENDENCY_MISSING``).

    Args:
        described: Output of :func:`_collect_exception_classes`.

    Returns:
        The integer default status.

    Raises:
        ErrorCodeFreezeError: When ``DomainError`` is not in the collected list,
            because then the fallback number would be a guess.
    """
    for entry in described:
        if entry["class"] == "DomainError":
            return int(entry["http_status"])
    raise ErrorCodeFreezeError(
        "DomainError was not collected -- cannot measure the fallback status of "
        "codes without a dedicated exception class"
    )


def _resolve_sites(
    sites: list[dict[str, Any]],
    api_status: int | None,
    exception_status: int | None,
    domain_default_status: int,
) -> list[dict[str, Any]]:
    """Resolve the status each raise site actually puts on the wire.

    Mirrors ``_domain_error_handler`` exactly: the API-layer map wins, otherwise
    the exception instance's ``status_code`` decides -- which is the site's own
    ``status_code=`` override when present, and the class default (``500`` for
    codes carried by bare ``DomainError``) when absent.

    Args:
        sites: Entries from :func:`_scan_call_sites` for one code.
        api_status: ``_STATUS_BY_CODE`` value for the code, or ``None``.
        exception_status: Dedicated exception class default, or ``None``.
        domain_default_status: ``DomainError.status_code`` (the last link).

    Returns:
        One dict per site: ``file`` / ``line`` / ``declared_status_code`` /
        ``actual_status`` / ``status_origin``.
    """
    resolved: list[dict[str, Any]] = []
    for site in sites:
        declared: int | None = site["status_code"]
        if api_status is not None:
            actual, origin = int(api_status), "api_status_map"
        elif declared is not None:
            actual, origin = int(declared), "call_site_explicit"
        elif exception_status is not None:
            actual, origin = int(exception_status), "exception_class_default"
        else:
            actual, origin = int(domain_default_status), "domain_error_default"
        resolved.append(
            {
                "file": site["module"],
                "line": site["line"],
                "declared_status_code": declared,
                "actual_status": actual,
                "status_origin": origin,
            }
        )
    return resolved


def _status_distribution(resolved_sites: list[dict[str, Any]]) -> dict[str, int]:
    """Count resolved sites per status, sorted by status for byte stability."""
    counts: dict[str, int] = {}
    for site in resolved_sites:
        key = str(site["actual_status"])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: int(pair[0])))


def _dominant_status(distribution: dict[str, int]) -> int:
    """Return the most frequent resolved status (ties broken by the smaller code).

    Args:
        distribution: ``{status: count}``; must not be empty.

    Returns:
        The dominant status as an int.

    Raises:
        ErrorCodeFreezeError: When called with an empty distribution.
    """
    if not distribution:
        raise ErrorCodeFreezeError("cannot pick a dominant status from an empty distribution")
    return int(min(distribution.items(), key=lambda pair: (-pair[1], int(pair[0])))[0])


def _uniformity_note(
    code: str,
    http_status: int,
    distribution: dict[str, int],
    default_without_override: int,
    site_count: int,
) -> str | None:
    """Explain a non-universal ``http_status``; ``None`` when it is universal.

    Args:
        code: ``ErrorCode`` literal (used in the message).
        http_status: The headline (dominant) status.
        distribution: Measured ``{status: site count}``.
        default_without_override: Status obtained by a site passing nothing.
        site_count: Total number of raise sites.

    Returns:
        A warning string, or ``None`` when every site agrees.
    """
    if len(distribution) < 2:
        return None
    split = " / ".join(f"{status} × {count}" for status, count in distribution.items())
    deviating = {
        status: count for status, count in distribution.items() if int(status) != http_status
    }
    deviating_text = " / ".join(f"{status} × {count}" for status, count in deviating.items())
    return (
        f"**非全量成立**：`http_status = {http_status}` 是 {site_count} 处构造点中的多数值，"
        f"实测分布 = {split}；其中 {deviating_text} 不是 {http_status}——"
        f"未传 `status_code=` 的构造点回落到 `DomainError` 默认 {default_without_override}。"
        f"下游（V0.2.0 参数化测试 / TS 侧）**必须按 call-site 取值**，"
        f"不得假设 `{code}` 恒为 {http_status}；逐点明细见 "
        f"`http_status_by_call_site_resolved`，偏离点见 `http_status_inconsistent_call_sites`。"
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export(ctx: _bootstrap.ExtractContext) -> dict[str, Any]:
    """Export the frozen error-code table.

    Args:
        ctx: Resolved extraction context.

    Returns:
        Metrics dict (``summary`` is printed by ``run.py``).

    Raises:
        ErrorCodeFreezeError: If the legacy tree diverges from the frozen
            expectations, or a description is missing.
    """
    import_dirs = _bootstrap.install_import_paths(ctx.source)
    if not _bootstrap.can_import("wbtime_ai_api.errors"):
        raise ErrorCodeFreezeError(
            "cannot import wbtime_ai_api.errors -- run this exporter with the legacy "
            f"interpreter ({ctx.python_executable}) and the {len(import_dirs)} import roots installed"
        )

    from wbtime_ai_api.errors import _CODE_BY_HTTP_STATUS, _STATUS_BY_CODE  # noqa: PLC0415
    from wbtime_ai_core.error_codes import ErrorCode  # noqa: PLC0415

    members = list(ErrorCode.__members__.items())
    described = _collect_exception_classes()
    call_sites = _scan_call_sites(ctx.source)

    diffs: list[str] = []
    if len(members) != EXPECTED_CODE_COUNT:
        diffs.append(f"ErrorCode count: expected {EXPECTED_CODE_COUNT}, got {len(members)}")
    if len(described) - 1 != EXPECTED_EXCEPTION_CLASS_COUNT:
        diffs.append(
            "exception.py class count: expected "
            f"{EXPECTED_EXCEPTION_CLASS_COUNT}, got {len(described) - 1}"
        )
    if len(_STATUS_BY_CODE) != EXPECTED_API_STATUS_MAP_SIZE:
        diffs.append(
            f"_STATUS_BY_CODE size: expected {EXPECTED_API_STATUS_MAP_SIZE}, got {len(_STATUS_BY_CODE)}"
        )
    for name, _member in members:
        if name not in DESCRIPTIONS:
            diffs.append(f"missing manual description for {name}")
    unknown_descriptions = sorted(set(DESCRIPTIONS) - {name for name, _ in members})
    if unknown_descriptions:
        diffs.append(f"descriptions for unknown codes: {unknown_descriptions}")
    unknown_call_sites = sorted(set(call_sites) - {name for name, _ in members})
    if unknown_call_sites:
        diffs.append(f"call sites reference unknown codes: {unknown_call_sites}")
    if diffs:
        raise ErrorCodeFreezeError(
            "error-code table diverged from the frozen baseline:\n  - " + "\n  - ".join(diffs)
        )

    codes: dict[str, Any] = {}
    status_histogram: dict[str, int] = {}
    without_exception: list[str] = []
    without_any_status: list[str] = []
    call_site_resolved: dict[str, int] = {}
    non_uniform_codes: dict[str, dict[str, int]] = {}
    domain_default_status = _domain_error_default_status(described)

    for index, (name, member) in enumerate(members):
        code = str(member)
        exception_entry = _pick_exception(code, described)
        api_status = _STATUS_BY_CODE.get(member)
        exception_status = exception_entry["http_status"] if exception_entry else None
        sites = call_sites.get(code, [])
        overrides = sorted(
            {site["status_code"] for site in sites if site["status_code"] is not None}
        )
        resolved_sites = _resolve_sites(sites, api_status, exception_status, domain_default_status)
        distribution = _status_distribution(resolved_sites)
        # Status a site gets when it passes no ``status_code=`` at all.
        default_without_override = (
            int(exception_status) if exception_status is not None else domain_default_status
        )

        # Exact reproduction of ``_STATUS_BY_CODE.get(exc.code, exc.status_code)``,
        # extended with the call-site override that decides the status when both
        # of the first two sources are silent.
        if api_status is not None:
            http_status: int | None = int(api_status)
            status_source = "api_status_map"
        elif exception_status is not None:
            http_status = int(exception_status)
            status_source = "exception_class"
        elif overrides:
            # Per-site resolution: the headline value is the *dominant* measured
            # status, never "the only override", because the sites that pass
            # nothing resolve to the class default instead (D-1).
            http_status = _dominant_status(distribution)
            status_source = "call_site_override"
            call_site_resolved[code] = http_status
        elif sites:
            http_status = _dominant_status(distribution)
            status_source = "domain_error_default"
        else:
            http_status = None
            status_source = "none"

        if len(distribution) > 1 and http_status is not None:
            non_uniform_codes[code] = distribution

        inconsistent_sites = [
            {
                "file": site["file"],
                "line": site["line"],
                "actual_status": site["actual_status"],
                "declared_status_code": site["declared_status_code"],
                "status_origin": site["status_origin"],
            }
            for site in resolved_sites
            if site["actual_status"] != http_status
        ]

        bucket = "null" if http_status is None else str(http_status)
        status_histogram[bucket] = status_histogram.get(bucket, 0) + 1
        if exception_entry is None:
            without_exception.append(code)
        if http_status is None:
            without_any_status.append(code)

        codes[code] = {
            "code": code,
            "enum_name": name,
            "enum_index": index,
            "http_status": http_status,
            "http_status_source": status_source,
            # ``true`` = every raise site resolves to ``http_status``;
            # ``false`` = the sites disagree (see the split below);
            # ``null`` = no raise site exists, so the question is unanswerable.
            "http_status_uniform": (None if not resolved_sites else len(distribution) <= 1),
            "http_status_distribution": distribution,
            "http_status_default_without_override": default_without_override,
            "http_status_by_api_map": None if api_status is None else int(api_status),
            "http_status_by_exception_class": exception_status,
            "http_status_by_call_site": overrides,
            "http_status_inconsistent_call_sites": inconsistent_sites,
            "http_status_by_call_site_resolved": resolved_sites,
            "note": (
                _uniformity_note(
                    code,
                    http_status,
                    distribution,
                    default_without_override,
                    len(resolved_sites),
                )
                if http_status is not None
                else None
            ),
            "python_exception": exception_entry["class"] if exception_entry else None,
            "python_exception_module": exception_entry["module"] if exception_entry else None,
            "python_exception_unmapped": exception_entry is None,
            "exception_docstring": exception_entry["docstring"] if exception_entry else None,
            # Every raise site is materialised twice on purpose: ``status_code_overrides``
            # keeps the *declared* fact (8 sites pass 503), while
            # ``http_status_by_call_site_resolved`` keeps the *resolved* fact (those 8
            # emit 503, the 2 silent ones emit 500). Collapsing them was D-1.
            "raise_site_count": len(sites),
            "raise_site_modules": sorted({site["module"] for site in sites}),
            "status_code_overrides": [
                {"module": site["module"], "line": site["line"]}
                for site in sites
                if site["status_code"] is not None
            ],
            "description": DESCRIPTIONS[code],
            "description_source": "manual",
            "unmapped": http_status is None,
        }

    if call_site_resolved != EXPECTED_CALL_SITE_RESOLVED:
        raise ErrorCodeFreezeError(
            "codes resolved only by call-site override changed: expected "
            f"{EXPECTED_CALL_SITE_RESOLVED}, got {call_site_resolved}"
        )
    if without_any_status:
        raise ErrorCodeFreezeError(
            f"codes without any HTTP status: {without_any_status} -- extend the resolution chain "
            "instead of leaving them null"
        )
    if non_uniform_codes != EXPECTED_NON_UNIFORM_CODES:
        raise ErrorCodeFreezeError(
            "codes whose raise sites disagree on the HTTP status changed: expected "
            f"{EXPECTED_NON_UNIFORM_CODES}, got {non_uniform_codes} -- either a raise site was added/"
            "removed without updating EXPECTED_NON_UNIFORM_CODES, or an override silently disappeared. "
            "Do NOT re-freeze the expectation to match a widened split without checking the source tree."
        )
    # Shape gate: the split must account for every raise site, and the uniformity
    # flag must agree with the split.  This is what makes "claim 503, hide 500"
    # impossible to reintroduce silently.
    for code, entry in codes.items():
        resolved = entry["http_status_by_call_site_resolved"]
        distribution = entry["http_status_distribution"]
        if sum(distribution.values()) != entry["raise_site_count"]:
            raise ErrorCodeFreezeError(
                f"{code}: http_status_distribution sums to {sum(distribution.values())} but "
                f"raise_site_count is {entry['raise_site_count']}"
            )
        expected_uniform = None if not resolved else len(distribution) <= 1
        if entry["http_status_uniform"] is not expected_uniform:
            raise ErrorCodeFreezeError(
                f"{code}: http_status_uniform={entry['http_status_uniform']!r} contradicts the "
                f"measured split {distribution}"
            )
        if entry["http_status_uniform"] is False and entry["note"] is None:
            raise ErrorCodeFreezeError(
                f"{code}: raise sites disagree on the status but no note explains it"
            )
        for site in entry["http_status_inconsistent_call_sites"]:
            if site["actual_status"] == entry["http_status"]:
                raise ErrorCodeFreezeError(
                    f"{code}: http_status_inconsistent_call_sites lists {site['file']}:{site['line']} "
                    f"but its actual status equals the headline {entry['http_status']}"
                )

    reverse_map = {
        str(status): str(code) for status, code in sorted(_CODE_BY_HTTP_STATUS.items())
    }

    document: dict[str, Any] = {
        "schema": "wbtimeai.contracts/errors",
        "contract_version": 3,
        "generated_by": "scripts/extract-from-py/export_errors.py",
        "source": ctx.source,
        "sources": {
            "error_codes": "packages/core/src/wbtime_ai_core/error_codes.py::ErrorCode",
            "exceptions": "packages/core/src/wbtime_ai_core/exception.py (+ error.py::DomainError)",
            "api_status_map": "apps/api/src/wbtime_ai_api/errors.py::_STATUS_BY_CODE",
            "api_reverse_map": "apps/api/src/wbtime_ai_api/errors.py::_CODE_BY_HTTP_STATUS",
            "call_sites": (
                "AST scan of <source>/{packages/*,apps/{api,cli,worker}}/src for calls passing "
                "code=ErrorCode.<NAME> (literal keyword arguments only)"
            ),
            "resolution_rule": (
                "apps/api/src/wbtime_ai_api/errors.py::_domain_error_handler -> "
                "_STATUS_BY_CODE.get(exc.code, exc.status_code). Per raise site: (1) the API-layer "
                "map wins when the code is in it; (2) else the exception instance's status_code, i.e. "
                "the site's own status_code= override when present; (3) else the exception class "
                "default -- DomainError.status_code (=500) for codes with no dedicated class. "
                "`http_status` is the dominant measured value; read `http_status_uniform` / "
                "`http_status_distribution` / `http_status_by_call_site_resolved` before assuming it "
                "holds for every site"
            ),
        },
        "meta": {
            "count": len(codes),
            "http_status_histogram": status_histogram,
            "with_api_status_map": sum(
                1 for entry in codes.values() if entry["http_status_source"] == "api_status_map"
            ),
            "with_exception_status_fallback": sum(
                1 for entry in codes.values() if entry["http_status_source"] == "exception_class"
            ),
            "with_call_site_override": sum(
                1 for entry in codes.values() if entry["http_status_source"] == "call_site_override"
            ),
            "codes_with_uniform_http_status": sum(
                1 for entry in codes.values() if entry["http_status_uniform"] is True
            ),
            "codes_with_non_uniform_http_status": sorted(non_uniform_codes),
            "non_uniform_codes": non_uniform_codes,
            "http_status_uniformity_rule": (
                "http_status_uniform = true ⇔ every raise site resolves to `http_status`; "
                "false ⇔ at least two distinct statuses are measured; null ⇔ the code has no raise "
                "site, so uniformity is not claimed either way"
            ),
            "domain_error_default_status": domain_default_status,
            "exception_class_count": len(described) - 1,
            "codes_without_exception_class": without_exception,
            "codes_without_exception_class_count": len(without_exception),
            "codes_without_any_http_status": without_any_status,
            "unmapped_codes": without_any_status,
            "call_site_resolved": call_site_resolved,
            "raise_site_total": sum(len(sites) for sites in call_sites.values()),
            "codes_with_raise_sites": sorted(call_sites),
            "description_source": "manual",
            "codes_digest_sha256": hashes.sha256_bytes(canonical.dumps(codes).encode("utf-8")),
        },
        "exceptions": described,
        "reverse_map_by_http_status": reverse_map,
        "codes": codes,
    }

    path, text = canonical.write_document(ctx.contracts_dir / OUTPUT_NAME, document)

    return {
        "summary": (
            f"codes={len(codes)} exception_classes={len(described) - 1} "
            f"api_map={len(_STATUS_BY_CODE)} call_site={len(call_site_resolved)} "
            f"raise_sites={document['meta']['raise_site_total']} unmapped={len(without_any_status)} "
            f"non_uniform={len(non_uniform_codes)} "
            f"bytes={len(text.encode('utf-8'))} sha256={hashes.sha256_file(path)[:12]}"
        ),
        "codes": len(codes),
        "call_site_resolved": call_site_resolved,
        "non_uniform_codes": non_uniform_codes,
        "unmapped": without_any_status,
        "path": str(path),
        "sha256": hashes.sha256_file(path),
    }
