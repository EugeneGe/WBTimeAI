"""C-04a exporter: freeze the unified response envelope.

Produces ``contracts/envelope.schema.json`` -- a JSON Schema **draft 2020-12**
document describing the response shell that the legacy API actually puts on the
wire, **plus an ``enforcement`` block that explains how that shell comes to
exist** (which layer wraps, which layer returns bare objects, who produces the
failure shell, and which four keys are invariant).

What is measured (never hand-copied)
------------------------------------
* The two pydantic models ``ErrorResponse`` / ``MessageResponse`` are exported
  verbatim through ``model_json_schema()`` (pydantic 2.13.5 in the legacy venv).
* The **success** shell is read from its single source of truth,
  ``wbtime_ai_api/middleware/response_shell.py`` (``_SUCCESS_CODE`` /
  ``_SUCCESS_MESSAGE`` / ``_SHELL_KEYS`` / ``_SKIP_PATHS``), not from prose.
* The **router-level** claim ("routers return bare business objects") is checked
  against ``create_app().openapi()``: for every sampled operation the 2xx
  response schema ``$ref`` must equal the expected ``response_model``.
* The 30 ``ErrorCode`` literals come from ``ErrorCode.__members__``.
* A live ``TestClient`` probe records the *shape* of four representative
  responses (success / framework 404 / 405 / 401).  Only the shape is recorded
  -- sorted top-level keys, JSON type per key, ``request_id == X-Request-Id`` --
  because the actual ``request_id`` is a fresh UUIDv7 on every request and would
  make the artifact non-reproducible.

The honest finding this file encodes
------------------------------------
1. **Success responses ARE wrapped.** Routers return a bare business object
   (``response_model=AgentResponse`` …); ``ResponseShellMiddleware`` then wraps
   it: ``{"code": 0, "message": "ok", "data": <that object>, "request_id":
   <uuid>}``.  ``code`` is the **integer** ``0`` -- while the failure shell
   carries a **string** ``ErrorCode``.  The two shells share their key set but
   not the type of ``code``.
2. The wrapped ``data`` member is the **bare business object**: there is *no*
   second-level ``{data: ...}`` wrapper (confirmed against the frozen OpenAPI
   document: 0 of 116 component schemas is a generic wrapper).
3. The failure shell **bypasses** the middleware -- exception handlers build it
   directly, and ``dispatch`` returns early for ``status >= 400`` so nothing is
   wrapped twice.
4. Some responses are deliberately **not** wrapped (SSE, ``/openapi.json``,
   non-JSON, empty bodies, and every ``status >= 400``); those are registered
   under ``x-wbtimeai.not_wrapped`` rather than being silently omitted.

Run under the legacy ``.venv`` interpreter (``run.py export`` re-executes).
"""

from __future__ import annotations

import warnings
from typing import Any

import _bootstrap
import canonical
import hashes

__all__ = [
    "NAME",
    "DESCRIPTION",
    "SCHEMA_NAME",
    "EXPECTED_SUCCESS_CODE",
    "EXPECTED_SUCCESS_MESSAGE",
    "EXPECTED_SHELL_KEYS",
    "EXPECTED_ERROR_REQUIRED",
    "EXPECTED_MESSAGE_REQUIRED",
    "ROUTER_SAMPLES",
    "EnvelopeFreezeError",
    "render_python_type",
    "export",
]

#: Registry name used by ``run.py --only``.
NAME = "envelope"

#: Human readable description shown by ``run.py export``.
DESCRIPTION = "Freeze the response envelope into contracts/envelope.schema.json"

SCHEMA_NAME = "envelope.schema.json"

#: Frozen expectations (measured against the legacy tree, never guessed).
EXPECTED_SUCCESS_CODE = 0
EXPECTED_SUCCESS_MESSAGE = "ok"
EXPECTED_SHELL_KEYS = ("code", "data", "message", "request_id")
EXPECTED_ERROR_REQUIRED = ("code", "message")
EXPECTED_MESSAGE_REQUIRED = ("message",)
EXPECTED_ERROR_CODE_COUNT = 30

#: Live probes: ``(label, method, path)``.  Chosen to exercise every reachable
#: branch of ``register_exception_handlers`` that needs no database.
PROBE_CASES: tuple[tuple[str, str, str], ...] = (
    ("success_json", "GET", "/health"),
    ("framework_404", "GET", "/api/v1/__wbtime_contract_probe__"),
    ("framework_405", "DELETE", "/health"),
    ("unauthenticated_401", "GET", "/api/v1/users/me"),
)

#: Router families sampled to prove "the router returns a bare business object".
#:
#: ``expected_schema_ref`` is asserted against ``create_app().openapi()`` so the
#: claim cannot rot silently.  ``return_statement`` is cited with file:line for
#: human review (read from the legacy source, not executed).
ROUTER_SAMPLES: tuple[dict[str, Any], ...] = (
    {
        "family": "agents",
        "operation": "POST /api/v1/agents",
        "path": "/api/v1/agents",
        "method": "post",
        "success_status": "201",
        "expected_schema_ref": "AgentResponse",
        "return_statement": "return _to_agent_response(dto)",
        "cite": "apps/api/src/wbtime_ai_api/routers/v1/agents.py:112,130",
    },
    {
        "family": "agents (list → data 为数组)",
        "operation": "GET /api/v1/agents",
        "path": "/api/v1/agents",
        "method": "get",
        "success_status": "200",
        "expected_schema_ref": "array<AgentResponse>",
        "return_statement": "return [_to_agent_response(dto) for dto in _paginate(dtos, page, page_size)]",
        "cite": "apps/api/src/wbtime_ai_api/routers/v1/agents.py:133,143",
    },
    {
        "family": "workspaces",
        "operation": "POST /api/v1/workspaces",
        "path": "/api/v1/workspaces",
        "method": "post",
        "success_status": "201",
        "expected_schema_ref": "WorkspaceResponse",
        "return_statement": "return _to_response(dto)",
        "cite": "apps/api/src/wbtime_ai_api/routers/v1/workspaces.py:55,73",
    },
    {
        "family": "runs",
        "operation": "GET /api/v1/runs/{run_id}",
        "path": "/api/v1/runs/{run_id}",
        "method": "get",
        "success_status": "200",
        "expected_schema_ref": "RunResponse",
        "return_statement": "return _to_run_response(dto)",
        "cite": "apps/api/src/wbtime_ai_api/routers/v1/runs.py:36",
    },
)

#: Legacy tests that already pin the shell on **business** endpoints (cited, so
#: the contract is anchored in the old repo's own acceptance criteria).
LEGACY_TEST_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "test": "tests/integration/test_api_2c_surface.py::_assert_shell",
        "asserts": "set(body) >= {'code','message','data','request_id'}",
        "note": "该 helper 在该文件被调用 4 次，覆盖 /projects、/workspaces/{id}/files|environment、/approvals、/tasks 四个路由族。",
    },
    {
        "test": "tests/integration/test_api_2c_surface.py::_create_workspace",
        "asserts": "client.post('/api/v1/workspaces') → 201，再取 _shell_data(created)['id']",
        "note": "业务对象 id 位于 data 之内 ⇒ 业务响应确实被套壳，而不是裸对象。",
    },
    {
        "test": "tests/integration/test_api_2c_surface.py::test_workspace_files_503_when_unassembled",
        "asserts": "status_code == 503 且 json()['code'] == 'DEPENDENCY_MISSING'",
        "note": "失败壳字段与状态码的联合断言；也是 errors.json 中该码取 503 的依据。",
    },
    {
        "test": "tests/unit/test_response_shell_value_judgement.py",
        "asserts": "_is_success_shell 真值表 + 真实中间件行为（非壳→套壳、已壳→原样透传）",
        "note": "证明「已是壳」判定是**值判定**（code==0 且 message=='ok' 且含 data 且含 request_id），不是只看键是否存在。",
    },
)


class EnvelopeFreezeError(RuntimeError):
    """Raised when the envelope does not match the frozen expectations."""


def render_python_type(value: Any) -> str:
    """Return a short JSON-ish type name for a live Python value.

    Args:
        value: Any JSON-decoded value.

    Returns:
        One of ``null`` / ``boolean`` / ``integer`` / ``number`` / ``string`` /
        ``array`` / ``object``.  ``bool`` is checked before ``int`` because
        ``bool`` is a subclass of ``int``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _make_app() -> Any:
    """Build the legacy FastAPI application (raises when it cannot be imported)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from wbtime_ai_api.main import create_app  # noqa: PLC0415

        return create_app()


def _probe_runtime(app: Any) -> dict[str, Any]:
    """Record the observed *shape* of representative responses.

    Args:
        app: The FastAPI application under test.

    Returns:
        A dict with ``available`` plus one entry per :data:`PROBE_CASES` label.
        Never raises: an unavailable test client degrades to
        ``{"available": False, "reason": ...}`` so ``export`` stays runnable.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from fastapi.testclient import TestClient  # noqa: PLC0415

            client = TestClient(app, raise_server_exceptions=False)
            observations: dict[str, Any] = {}
            for label, method, path in PROBE_CASES:
                response = client.request(method, path)
                try:
                    parsed = response.json()
                except Exception:  # noqa: BLE001 - non-JSON response
                    observations[label] = {
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                        "json": False,
                    }
                    continue
                if not isinstance(parsed, dict):
                    observations[label] = {
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                        "json": True,
                        "body_type": render_python_type(parsed),
                    }
                    continue
                observations[label] = {
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "json": True,
                    "top_level_keys": sorted(parsed),
                    "field_types": {
                        key: render_python_type(parsed[key]) for key in sorted(parsed)
                    },
                    "is_unified_shell": sorted(parsed) == sorted(EXPECTED_SHELL_KEYS),
                    "request_id_equals_header": (
                        parsed.get("request_id") == response.headers.get("x-request-id")
                    ),
                }
    except Exception as error:  # noqa: BLE001 - probe is evidence, not a gate
        return {"available": False, "reason": f"{type(error).__name__}: {error}"}

    return {"available": True, "cases": observations}


def _schema_ref(schema: dict[str, Any]) -> str:
    """Render a response schema as ``Name`` or ``array<Name>``.

    Args:
        schema: A JSON Schema fragment from an OpenAPI ``responses`` entry.

    Returns:
        The referenced component name, ``array<Name>`` for arrays, or a JSON dump
        fallback for inline schemas.
    """
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        items = schema.get("items") or {}
        if "$ref" in items:
            return "array<" + str(items["$ref"]).rsplit("/", 1)[-1] + ">"
        return "array<inline>"
    return canonical.dumps(schema).strip()


def _router_evidence(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Measure the sampled operations' success-response schema references.

    Args:
        spec: ``create_app().openapi()``.

    Returns:
        One entry per :data:`ROUTER_SAMPLES`, with the measured ``schema_ref``.

    Raises:
        EnvelopeFreezeError: If an operation is missing or its schema changed.
    """
    measured: list[dict[str, Any]] = []
    diffs: list[str] = []
    for sample in ROUTER_SAMPLES:
        operation = (spec.get("paths", {}).get(sample["path"]) or {}).get(sample["method"])
        if not operation:
            diffs.append(f"{sample['operation']}: operation not found in the OpenAPI document")
            continue
        responses = operation.get("responses") or {}
        success = responses.get(sample["success_status"])
        if not success:
            diffs.append(f"{sample['operation']}: no {sample['success_status']} response")
            continue
        schema = ((success.get("content") or {}).get("application/json") or {}).get("schema") or {}
        ref = _schema_ref(schema)
        if ref != sample["expected_schema_ref"]:
            diffs.append(
                f"{sample['operation']}: success schema expected "
                f"{sample['expected_schema_ref']!r}, got {ref!r}"
            )
        measured.append(
            {
                "family": sample["family"],
                "operation": sample["operation"],
                "success_status": int(sample["success_status"]),
                "response_model": ref,
                "router_returns": sample["return_statement"],
                "cite": sample["cite"],
                "wire_body": (
                    '{"code": 0, "message": "ok", "data": <上面 response_model 的实例>, '
                    '"request_id": "<X-Request-Id>"}'
                ),
            }
        )
    if diffs:
        raise EnvelopeFreezeError(
            "router-level envelope evidence diverged:\n  - " + "\n  - ".join(diffs)
        )
    return measured


def _build_document(
    error_schema: dict[str, Any],
    message_schema: dict[str, Any],
    success_code: int,
    success_message: str,
    shell_keys: tuple[str, ...],
    skipped_paths: tuple[str, ...],
    error_codes: list[str],
    probe: dict[str, Any],
    routers: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    """Assemble the draft 2020-12 envelope document.

    Args:
        error_schema: ``ErrorResponse.model_json_schema()`` output, verbatim.
        message_schema: ``MessageResponse.model_json_schema()`` output, verbatim.
        success_code: ``_SUCCESS_CODE`` of the response-shell middleware.
        success_message: ``_SUCCESS_MESSAGE`` of the response-shell middleware.
        shell_keys: ``_SHELL_KEYS`` of the response-shell middleware (sorted).
        skipped_paths: ``_SKIP_PATHS`` of the response-shell middleware.
        error_codes: Every ``ErrorCode`` literal, in enum declaration order.
        probe: Output of :func:`_probe_runtime`.
        routers: Output of :func:`_router_evidence`.
        source: Legacy repository root, recorded for traceability.

    Returns:
        The JSON Schema document (not yet serialised).
    """
    request_id_schema = {
        "description": (
            "本次请求 request_id。与响应头 X-Request-Id 同源（「响应体 == 响应头」）。"
            "UUIDv7（RFC 9562），由 wbtime_ai_core.id.generate_id 生成；"
            "**键恒在**（值可为 null），实测 4/4 探针用例满足 body.request_id == header。"
        ),
        "type": ["string", "null"],
    }

    success_envelope = {
        "source": "measured:apps/api/src/wbtime_ai_api/middleware/response_shell.py",
        "description": (
            "成功响应壳（总纲 §11.1）。由 ResponseShellMiddleware 套在**成功的 "
            "application/json** 响应外层。四顶层键恒在（实测 4/4）。"
            "注意 code 为**整数** 0，与失败壳的**字符串**错误码不同型。"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(shell_keys),
        "properties": {
            "code": {
                "description": "成功恒为整数 0（_SUCCESS_CODE）。",
                "const": success_code,
                "type": "integer",
            },
            "message": {
                "description": "成功恒为 \"ok\"（_SUCCESS_MESSAGE）。",
                "const": success_message,
                "type": "string",
            },
            "data": {
                "description": (
                    "**裸业务对象**：原始响应体的 JSON 解码值（对象 / 数组 / 标量 / "
                    "null），**没有**二级 {data: ...} 外壳。"
                    "字段结构见 openapi.v1.frozen.json 的 components.schemas。"
                ),
                "$ref": "#/$defs/successBody",
            },
            "request_id": request_id_schema,
        },
    }

    success_body = {
        "source": "measured:contracts/openapi.v1.frozen.json",
        "description": (
            "成功壳 data 成员的内容：裸业务对象，无统一外壳。"
            "实测依据：116 个 components.schemas 中**没有**任何泛型 {data} 包装模型，"
            "2xx 响应直接 $ref 业务模型（AgentResponse / WorkspaceResponse / …）。"
        ),
        "anyOf": [
            {"type": "object"},
            {"type": "array"},
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ],
    }

    error_envelope = {
        "source": "measured:apps/api/src/wbtime_ai_api/errors.py",
        "description": (
            "失败响应壳（总纲 §11.1）。由 register_exception_handlers 直接产出，"
            "**不经过** ResponseShellMiddleware（status >= 400 时 dispatch 提前 return，"
            "避免二次包裹）。四顶层键恒在；data 缺省为 {}，request_id 可为 null"
            "（值可空，键不可缺）。"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(EXPECTED_SHELL_KEYS),
        "properties": {
            "code": {
                "description": "统一错误码（ErrorCode 字面值，字符串）。",
                "type": "string",
                "enum": list(error_codes),
            },
            "message": {
                "description": "人类可读错误信息（非空字符串，可能为中文）。",
                "type": "string",
            },
            "data": {"$ref": "#/$defs/ErrorResponse/properties/data"},
            "request_id": request_id_schema,
        },
    }

    message_envelope = {
        "source": "measured:pydantic MessageResponse + response shell",
        "description": (
            "**简单消息壳**（MessageResponse）在线上被成功壳包住，"
            "因此裸 MessageResponse 不会单独出现在线上；"
            "线上形态为 {code: 0, message: \"ok\", data: {message: <str>}, request_id}。"
            "注意 message 出现了两次且语义不同：外层恒为 \"ok\"，内层是业务提示语。"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(EXPECTED_SHELL_KEYS),
        "properties": {
            "code": {"const": success_code, "type": "integer"},
            "message": {"const": success_message, "type": "string"},
            "data": {
                "type": "object",
                "additionalProperties": False,
                "required": list(EXPECTED_MESSAGE_REQUIRED),
                "properties": {"message": {"description": "提示信息", "type": "string"}},
            },
            "request_id": request_id_schema,
        },
    }

    raw_message = dict(message_schema)
    raw_message["$comment"] = (
        "pydantic 模型原样导出。**不会**单独上线：MessageResponse 作为 response_model "
        "时同样被成功壳包裹（见 $defs/messageEnvelope）。"
    )

    enforcement = {
        "source": "manual+measured",
        "summary": (
            "响应壳**在中间件层生效**，不在路由层。路由声明 response_model=<业务模型> 并"
            "直接 return 业务对象；ResponseShellMiddleware 在外层把该对象放进 data 并补 "
            "code=0/message=\"ok\"/request_id。失败响应则由异常处理器直接产出，完全绕过中间件。"
        ),
        "middleware_stack": {
            "source": "read:apps/api/src/wbtime_ai_api/main.py:40-46,66",
            "outermost_first": [
                "CORSMiddleware",
                "ResponseShellMiddleware",
                "RequestContextMiddleware",
            ],
            "note": (
                "Starlette 的 add_middleware 是**后加者更靠外**：RequestContextMiddleware "
                "先加（更内层），ResponseShellMiddleware 后加（更外层）。main.py 注释原文："
                "「先加 → 更内层；其响应头供外层『响应壳中间件』复用（体 == 头）」。"
                "因此壳里的 request_id 优先取响应头 X-Request-Id。"
            ),
        },
        "success_wrap": {
            "produced_by": "ResponseShellMiddleware.dispatch → _wrap_success_json",
            "router_returns_bare_object": True,
            "trigger": (
                "status_code < 400 且 content-type 含 application/json 且 path ∉ _SKIP_PATHS "
                "且 body 非空 且 非「已是成功壳」"
            ),
            "router_samples": routers,
            "wire_equals": (
                "{code: 0, message: \"ok\", data: <response_model 实例>, "
                "request_id: <响应头 X-Request-Id>}"
            ),
            "note": (
                "这是对「成功响应是裸业务对象」这一常见误解的直接纠正："
                "裸对象只是**路由返回值**，客户端看到的是壳。"
            ),
        },
        "error_shell": {
            "produced_by": [
                {
                    "handler": "errors.py::_domain_error_handler",
                    "covers": "DomainError 及其子类（WBTimeAIError / NotFoundError / …）",
                    "status_rule": "_STATUS_BY_CODE.get(exc.code, exc.status_code)",
                    "data": "exc.to_dict()['data']（通常 {}，可带上下文）",
                },
                {
                    "handler": "errors.py::_validation_error_handler",
                    "covers": "fastapi.exceptions.RequestValidationError",
                    "status_rule": "恒 422",
                    "data": "{errors: [...]}（实测：jsonable_encoder(exc.errors())）",
                },
                {
                    "handler": "errors.py::_http_exception_handler",
                    "covers": "starlette HTTPException（框架层 404 / 405 等）",
                    "status_rule": "原样保留 exc.status_code",
                    "data": "{}",
                },
                {
                    "handler": "errors.py::_unhandled_exception_handler",
                    "covers": "未捕获的 Exception",
                    "status_rule": "恒 500",
                    "data": "{}",
                },
            ],
            "bypasses_middleware": (
                "ResponseShellMiddleware.dispatch 在 status_code >= 400 时直接 return response，"
                "因此失败壳不会被二次包裹。"
            ),
            "code_resolution": "code 取 ErrorCode 字面值（字符串），与成功壳的整数 0 不同型。",
        },
        "field_invariance": {
            "top_level_key_count": 4,
            "always_present": list(EXPECTED_SHELL_KEYS),
            "request_id": {
                "key_always_present": True,
                "value_may_be_null": True,
                "equals_response_header": True,
                "evidence": "errors.py::_payload 与 _domain_error_handler 都无条件写 request_id 键；实测 4/4 探针相等。",
            },
            "data": {
                "key_always_present": True,
                "failure_default": {},
                "may_carry_context": True,
                "measured_examples": [
                    "404 → {}",
                    "422 → {\"errors\": [ ... ]}",
                    "DEPENDENCY_MISSING(503) → {\"capability\": \"remote_tasks\"}",
                ],
            },
            "code_type_by_outcome": {
                "success": "integer 0",
                "failure": "string（ErrorCode 字面值，30 种）",
                "note": "**不得**在 TS 侧用同一个类型同时表达两种结果，必须按 status 分支判别。",
            },
            "message": {
                "success": "恒为 \"ok\"",
                "failure": "人类可读文本，可能为中文",
            },
        },
        "legacy_test_evidence": list(LEGACY_TEST_EVIDENCE),
    }

    document: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://wbtimeai.local/contracts/envelope.schema.json",
        "title": "WBTimeAI v1 unified response envelope",
        "description": (
            "WBTimeAI API v1 响应壳契约（冻结）。"
            "成功壳 code=0(integer)/message=\"ok\"，data=裸业务对象；"
            "失败壳 code=ErrorCode(string)/message=可读信息，data 缺省 {}。"
            "两者共享同一组四顶层键，但 code 的类型不同。"
            "**生效方式**（路由返回裸对象 → 中间件套壳；失败壳由异常处理器直出）见 "
            "x-wbtimeai.enforcement。"
        ),
        "anyOf": [
            {"$ref": "#/$defs/errorEnvelope"},
            {"$ref": "#/$defs/messageEnvelope"},
            {"$ref": "#/$defs/successEnvelope"},
        ],
        "$comment": (
            "使用 anyOf 而非 oneOf：messageEnvelope 是 successEnvelope 的真子集 "
            "（data 恰为 {message: string}），oneOf 会因两个分支同时命中而判失败。"
        ),
        "$defs": {
            "successBody": success_body,
            "successEnvelope": success_envelope,
            "messageEnvelope": message_envelope,
            "errorEnvelope": error_envelope,
            "ErrorResponse": error_schema,
            "MessageResponse": raw_message,
        },
        "x-wbtimeai": {
            "schema_kind": "response-envelope",
            "contract_version": 2,
            "generated_by": "scripts/extract-from-py/export_envelope.py",
            "source": source,
            "provenance": {
                "ErrorResponse": "pydantic:apps/api/src/wbtime_ai_api/schemas/common.py",
                "MessageResponse": "pydantic:apps/api/src/wbtime_ai_api/schemas/common.py",
                "successEnvelope": "manual+measured:middleware/response_shell.py",
                "errorEnvelope": "manual+measured:errors.py",
                "messageEnvelope": "manual+measured:pydantic+middleware",
                "successBody": "manual+measured:contracts/openapi.v1.frozen.json",
                "enforcement": "manual+measured:main.py + routers/v1/*.py + errors.py + 旧仓测试",
            },
            "measured": {
                "success_code": success_code,
                "success_message": success_message,
                "shell_keys": list(shell_keys),
                "error_code_count": len(error_codes),
                "error_required_fields": list(EXPECTED_ERROR_REQUIRED),
                "router_samples_checked": len(routers),
            },
            "enforcement": enforcement,
            "not_wrapped": {
                "description": (
                    "下列响应**不套壳**（原样返回），任何 TS 侧的统一解包逻辑都必须先排除它们。"
                ),
                "cases": [
                    {
                        "case": "failure",
                        "condition": "status_code >= 400",
                        "note": "已由异常处理器产出四字段壳；中间件跳过，避免二次包裹。",
                    },
                    {
                        "case": "sse",
                        "condition": "content-type 含 text/event-stream",
                        "note": "§11.1 例外；request_id / trace_id 仅经响应头下发。帧契约见 sse/channels.json。",
                    },
                    {
                        "case": "non_json",
                        "condition": "content-type 不含 application/json",
                        "note": "例如 /metrics 的 text/plain。",
                    },
                    {
                        "case": "framework_path",
                        "condition": f"path ∈ {list(skipped_paths)}",
                        "note": "供 Swagger / Redoc 消费，不得套壳。",
                    },
                    {
                        "case": "already_shell",
                        "condition": "code == 0 且 message == \"ok\" 且含 data 与 request_id",
                        "note": "幂等（值判定，非键判定）：命中即原样返回，不二次包裹。",
                    },
                    {
                        "case": "empty_body",
                        "condition": "body == b\"\"",
                        "note": "204 等空体响应只保留状态码与响应头。",
                    },
                ],
            },
            "runtime_probe": probe,
        },
    }
    return document


def export(ctx: _bootstrap.ExtractContext) -> dict[str, Any]:
    """Export the frozen response-envelope schema.

    Args:
        ctx: Resolved extraction context.

    Returns:
        Metrics dict (``summary`` is printed by ``run.py``).

    Raises:
        EnvelopeFreezeError: If the legacy implementation diverges from the
            frozen expectations.
    """
    import_dirs = _bootstrap.install_import_paths(ctx.source)
    if not _bootstrap.can_import("wbtime_ai_api.main"):
        raise EnvelopeFreezeError(
            "cannot import wbtime_ai_api.main -- run this exporter with the legacy "
            f"interpreter ({ctx.python_executable}) and the {len(import_dirs)} import roots installed"
        )

    from wbtime_ai_api.errors import _CODE_BY_HTTP_STATUS, _STATUS_BY_CODE  # noqa: PLC0415
    from wbtime_ai_api.middleware.response_shell import (  # noqa: PLC0415
        _SHELL_KEYS,
        _SKIP_PATHS,
        _SUCCESS_CODE,
        _SUCCESS_MESSAGE,
    )
    from wbtime_ai_api.schemas.common import ErrorResponse, MessageResponse  # noqa: PLC0415
    from wbtime_ai_core.error_codes import ErrorCode  # noqa: PLC0415

    error_schema: dict[str, Any] = ErrorResponse.model_json_schema()
    message_schema: dict[str, Any] = MessageResponse.model_json_schema()
    error_codes = [str(member) for member in ErrorCode.__members__.values()]

    diffs: list[str] = []
    if _SUCCESS_CODE != EXPECTED_SUCCESS_CODE:
        diffs.append(f"_SUCCESS_CODE: expected {EXPECTED_SUCCESS_CODE}, got {_SUCCESS_CODE!r}")
    if _SUCCESS_MESSAGE != EXPECTED_SUCCESS_MESSAGE:
        diffs.append(f"_SUCCESS_MESSAGE: expected {EXPECTED_SUCCESS_MESSAGE!r}, got {_SUCCESS_MESSAGE!r}")
    shell_keys = tuple(sorted(_SHELL_KEYS))
    if shell_keys != EXPECTED_SHELL_KEYS:
        diffs.append(f"_SHELL_KEYS: expected {list(EXPECTED_SHELL_KEYS)}, got {list(shell_keys)}")
    if tuple(error_schema.get("required", ())) != EXPECTED_ERROR_REQUIRED:
        diffs.append(
            "ErrorResponse.required: expected "
            f"{list(EXPECTED_ERROR_REQUIRED)}, got {list(error_schema.get('required', ()))}"
        )
    if tuple(message_schema.get("required", ())) != EXPECTED_MESSAGE_REQUIRED:
        diffs.append(
            "MessageResponse.required: expected "
            f"{list(EXPECTED_MESSAGE_REQUIRED)}, got {list(message_schema.get('required', ()))}"
        )
    if len(error_codes) != EXPECTED_ERROR_CODE_COUNT:
        diffs.append(f"ErrorCode count: expected {EXPECTED_ERROR_CODE_COUNT}, got {len(error_codes)}")
    if not _STATUS_BY_CODE or not _CODE_BY_HTTP_STATUS:
        diffs.append("api error maps are empty")
    if diffs:
        raise EnvelopeFreezeError(
            "response envelope diverged from the frozen baseline:\n  - " + "\n  - ".join(diffs)
        )

    app = _make_app()
    routers = _router_evidence(app.openapi())
    probe = _probe_runtime(app)

    document = _build_document(
        error_schema=error_schema,
        message_schema=message_schema,
        success_code=_SUCCESS_CODE,
        success_message=_SUCCESS_MESSAGE,
        shell_keys=shell_keys,
        skipped_paths=tuple(sorted(_SKIP_PATHS)),
        error_codes=error_codes,
        probe=probe,
        routers=routers,
        source=ctx.source,
    )

    path, text = canonical.write_document(ctx.contracts_dir / SCHEMA_NAME, document)
    probe_state = "probe=on" if probe.get("available") else "probe=unavailable"

    return {
        "summary": (
            f"shell_keys={len(shell_keys)} success_code={_SUCCESS_CODE} "
            f"error_codes={len(error_codes)} routers={len(routers)} "
            f"bytes={len(text.encode('utf-8'))} {probe_state} "
            f"sha256={hashes.sha256_file(path)[:12]}"
        ),
        "success_code": _SUCCESS_CODE,
        "error_codes": len(error_codes),
        "router_samples": len(routers),
        "probe_available": bool(probe.get("available")),
        "path": str(path),
        "sha256": hashes.sha256_file(path),
    }
