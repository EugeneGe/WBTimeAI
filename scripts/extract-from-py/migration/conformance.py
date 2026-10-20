"""Conformance skeletons frozen from the legacy repo (V0.0.1 / C-06).

Four cross-cutting契约 that the rebuild must **re-prove in TypeScript**, because
they are the ones a language switch quietly breaks:

===========================  ==================================================
``tenant-404``               跨租户访问返回 404 而不是 403/401
``idempotency``              幂等键复用语义（同键同体复用 / 同键异体 409）
``content-negotiation``      ``Accept`` 协商与响应 ``Content-Type``
``stringly-contracts``       字符串化契约（枚举字面值 / 时间格式 / uuid 形态）
===========================  ==================================================

Every ``source`` entry carries ``file`` + ``line`` + ``quote``.  The quote is
verified **at export time** against the read-only legacy tree: if the quoted
fragment is not on that exact line, the exporter fails.  This is what keeps the
skeletons honest — a fabricated line number cannot survive ``run.py export``.

The skeletons are deliberately ``status: skeleton``: they name the invariant and
give 2–4 seed cases, but the full parameterised matrix (e.g. the ≥11 resource
families for I-1) is filled by the owning version, not here.

Only the Python standard library is used here.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable

__all__ = [
    "SourceRef",
    "Case",
    "ConformanceSpec",
    "SPECS",
    "STATUS_SKELETON",
    "GENERATED_BY",
    "render_yaml",
    "LineReader",
    "SourceVerificationError",
    "verify_sources",
]

#: Marker written into every skeleton, so nobody mistakes it for a finished suite.
STATUS_SKELETON = "skeleton"

#: Producer recorded inside every skeleton (consumed by ``contract-manifest.json``).
GENERATED_BY = "scripts/extract-from-py/export_migration.py"


class SourceVerificationError(RuntimeError):
    """Raised when a ``source`` reference does not match the legacy tree."""


@dataclasses.dataclass(frozen=True)
class SourceRef:
    """One verified pointer into the legacy repository.

    Attributes:
        file: Path relative to the legacy source root (POSIX separators).
        line: 1-based line number.
        quote: Fragment that must occur on that line, verbatim.
        why: What the reference establishes for this conformance rule.
    """

    file: str
    line: int
    quote: str
    why: str


@dataclasses.dataclass(frozen=True)
class Case:
    """One seed conformance case.

    Attributes:
        name: Stable kebab-case identifier.
        given: Preconditions / request shape.
        expect: Observable expectation (status, body field, frame bytes, ...).
    """

    name: str
    given: str
    expect: str


@dataclasses.dataclass(frozen=True)
class ConformanceSpec:
    """One skeleton document."""

    id: str
    title: str
    applies_to: tuple[str, ...]
    scope: tuple[str, ...]
    roadmap: tuple[str, ...]
    source: tuple[SourceRef, ...]
    cases: tuple[Case, ...]
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The four skeletons
# ---------------------------------------------------------------------------

_TENANT_404 = ConformanceSpec(
    id="tenant-404",
    title="跨租户访问必须返回 404（不是 403 / 401）",
    applies_to=("V0.2.0",),
    scope=("@wbtime/security", "@wbtime/api", "@wbtime/identity"),
    roadmap=(
        "docs/V1.0/00-版本路线图.md §4.1「I-1 跨租户 404 / I-3 越权回归」归类 ①，"
        "判据逐字继承（≥11 资源族参数化）",
        "docs/V1.0/V0.2.0-身份与HTTP垂直切片（本版判据落点）",
    ),
    source=(
        SourceRef(
            file="tests/integration/test_cross_tenant_404.py",
            line=3,
            quote="越权（跨租户）返回 404 而非 403",
            why="不变量原文：跨租户一律 404，不泄露资源是否存在",
        ),
        SourceRef(
            file="tests/integration/test_cross_tenant_404.py",
            line=62,
            quote="跨租户 → NOT_FOUND（映射 HTTP 404）",
            why="领域层以 NOT_FOUND 承载，API 层再映射成 404",
        ),
        SourceRef(
            file="packages/core/src/wbtime_ai_core/error_codes.py",
            line=22,
            quote='NOT_FOUND = "NOT_FOUND"',
            why="错误码是 StrEnum 字面值，TS 侧需保持同一字符串",
        ),
        SourceRef(
            file="apps/api/src/wbtime_ai_api/errors.py",
            line=37,
            quote="ErrorCode.NOT_FOUND: 404,",
            why="领域码 → HTTP 状态映射表（唯一的 404 出口）",
        ),
        SourceRef(
            file="packages/application/src/wbtime_ai_application/queries/agent.py",
            line=56,
            quote="跨租户 / 不存在 → ``NOT_FOUND``",
            why="查询侧把「不存在」与「跨租户」折叠为同一可观测结果",
        ),
    ),
    cases=(
        Case(
            name="read-other-tenant-resource",
            given="租户 A 的会话读取租户 B 的 agent_id（GET /api/v1/agents/{id}）",
            expect="HTTP 404，body.code = NOT_FOUND；不得出现 403 / PERMISSION_DENIED，"
            "且响应体不含资源存在性线索",
        ),
        Case(
            name="write-other-tenant-resource",
            given="租户 A 的会话 PATCH / DELETE 租户 B 的资源",
            expect="HTTP 404（不是 403），且租户 B 的数据零副作用（写后读回原值）",
        ),
        Case(
            name="lookup-by-name-across-tenant",
            given="按名/按 slug 查找跨租户资源（仓储层按 tenant 过滤后应查不到）",
            expect="上层收到 NotFound（404）；不得因「名字已存在」返回 409 而泄露占用事实",
        ),
        Case(
            name="resource-family-parameterised",
            given="≥11 个资源族各跑一次越权读：agent / agent_version / run / conversation / "
            "workspace / model_credential / tool / skill / workflow / task / plugin",
            expect="全部 404 且 body.code ∈ {NOT_FOUND, *_NOT_FOUND}；断言必须参数化，"
            "禁止只测一个资源族（旧线口径）",
        ),
    ),
    notes=(
        "TS 侧必须由 ScopedRepo<T> + 全局 ScopeFilter 保证「裸 id 查不到」，"
        "而不是靠每个 handler 手写 tenant 条件（否则 I-2 在 TS 侧失守）。",
        "404 与 401 的边界：未认证/过期 → 401；已认证但对象不可见 → 404。",
    ),
)

_IDEMPOTENCY = ConformanceSpec(
    id="idempotency",
    title="幂等键复用语义（同键同体复用首次结果；同键异体 / 跨用户 409）",
    applies_to=("V0.1.0", "V0.5.0"),
    scope=("@wbtime/core", "@wbtime/api", "@wbtime/scheduler"),
    roadmap=(
        "docs/V1.0/00-版本路线图.md §4.1「平台基座」归类 ②（语义继承、实现重写）",
        "docs/V1.0/00-版本路线图.md §4.1「Task / TaskQueue / Scheduler」②"
        "（调度幂等键合成属 V0.5.0）",
    ),
    source=(
        SourceRef(
            file="tests/integration/test_idempotency.py",
            line=6,
            quote="同键不同体",
            why="同键异体 → 409 + IDEMPOTENCY_KEY_REUSE 的原始判据",
        ),
        SourceRef(
            file="tests/integration/test_idempotency.py",
            line=7,
            quote="键作用域 ``(tenant_id, idempotency_key)``",
            why="键作用域是 (tenant_id, key)，唯一索引已存在，重建期不得改语义",
        ),
        SourceRef(
            file="packages/application/src/wbtime_ai_application/services/idempotency_service.py",
            line=107,
            quote="IDEMPOTENCY_KEY_REUSE",
            why="跨用户串号与同键异体共用同一错误码，均映射 409",
        ),
        SourceRef(
            file="packages/application/src/wbtime_ai_application/services/idempotency_service.py",
            line=117,
            quote="code=ErrorCode.IDEMPOTENCY_KEY_REUSE",
            why="代码里的唯一抛出点（重建后应对应同一个 TS 错误类）",
        ),
        SourceRef(
            file="packages/database/src/wbtime_ai_database/models/task.py",
            line=52,
            quote="fire_time.isoformat()",
            why="调度侧幂等键的合成格式：{target_type}:{target_id}:{fire_time.isoformat()}",
        ),
        SourceRef(
            file="tests/unit/test_application_idempotency.py",
            line=6,
            quote="compute_request_fingerprint",
            why="请求指纹是 sha256 hex（64 字符），随 body 变化 —— 纯函数判据",
        ),
    ),
    cases=(
        Case(
            name="same-key-same-body-reuses-first-result",
            given="同一 (tenant_id, Idempotency-Key) 提交完全相同的 body 两次",
            expect="第二次不新建实体，返回首次的 run_id / 结果；库内实体计数不变",
        ),
        Case(
            name="same-key-different-body-conflicts",
            given="同一 (tenant_id, Idempotency-Key)，第二次 body 不同",
            expect="HTTP 409，body.code = IDEMPOTENCY_KEY_REUSE（不是 422）",
        ),
        Case(
            name="same-key-different-user-conflicts",
            given="同一 Idempotency-Key，但换了用户/租户",
            expect="HTTP 409 + IDEMPOTENCY_KEY_REUSE（防跨用户串号）；"
            "两用户即使 body 相同也不得共享结果",
        ),
        Case(
            name="fingerprint-is-stable-and-body-sensitive",
            given="compute_request_fingerprint 对同一 body 调两次；再换一个 body 调一次",
            expect="同 body → 完全相同的 64 位 sha256 hex；异 body → 不同摘要",
        ),
        Case(
            name="scheduler-key-embeds-fire-time",
            given="同 (target_type, target_id) 在相同 fire_time 重复入队两次",
            expect="第二次被幂等键拦截（唯一约束），不产生两条调度记录",
        ),
    ),
    notes=(
        "幂等记录的生命周期（TTL / 清理）旧线未定，重建期必须在 V0.1.0 一并定死，"
        "否则长期运行后唯一索引会无限膨胀。",
        "前端重试与后端幂等键必须共用同一生成规则，否则「重试即重复执行」。",
    ),
)

_CONTENT_NEGOTIATION = ConformanceSpec(
    id="content-negotiation",
    title="请求 / 响应 Content-Type 协商（含 SSE 不套壳例外）",
    applies_to=("V0.1.0", "V0.3.0"),
    scope=("@wbtime/api", "@wbtime/sse", "@wbtime/web"),
    roadmap=(
        "docs/V1.0/00-版本路线图.md §4.1「平台基座 错误码+响应壳」②",
        "docs/V1.0/00-版本路线图.md §4.1「Runtime + 19 通道 SSE」②（19 帧逐字节是硬判据）",
    ),
    source=(
        SourceRef(
            file="apps/api/src/wbtime_ai_api/middleware/response_shell.py",
            line=16,
            quote="text/event-stream",
            why="响应壳的例外条款：SSE 流式帧**不套壳**",
        ),
        SourceRef(
            file="apps/api/src/wbtime_ai_api/routers/v1/agents.py",
            line=311,
            quote="text/event-stream",
            why="Accept 协商实现：含 text/event-stream 或缺省 / */* → SSE",
        ),
        SourceRef(
            file="apps/api/src/wbtime_ai_api/routers/v1/agents.py",
            line=347,
            quote='media_type="text/event-stream"',
            why="流式响应的 media_type 出口",
        ),
        SourceRef(
            file="tests/e2e/test_phase1_flow.py",
            line=229,
            quote="text/event-stream",
            why="e2e 侧对响应头的既有断言（判据可逐字继承）",
        ),
        SourceRef(
            file="tests/integration/test_sse_contract.py",
            line=9,
            quote="X-Accel-Buffering: no",
            why="除 Content-Type 外还必须带反缓冲头，否则代理会攒帧",
        ),
        SourceRef(
            file="tests/integration/test_api_web_static.py",
            line=95,
            quote="text/html",
            why="静态资源按扩展名给出 text/html（非 JSON 壳）",
        ),
    ),
    cases=(
        Case(
            name="json-default",
            given="Accept 缺省（或 application/json）请求非流式端点",
            expect="HTTP 200 + content-type: application/json；body 为统一响应壳"
            "（data / request_id 等字段齐全）",
        ),
        Case(
            name="sse-on-accept-event-stream",
            given="Accept: text/event-stream 请求 run 流式端点",
            expect="HTTP 200 + content-type: text/event-stream + X-Accel-Buffering: no；"
            "每帧形如 `id: <seq>\\nevent: <channel>\\ndata: {...}\\n\\n`，且**不套 JSON 壳**",
        ),
        Case(
            name="sse-on-wildcard-accept",
            given="Accept: */* （或缺省）请求同一个流式端点",
            expect="与显式 text/event-stream 等价 → 走 SSE 分支（旧线 §2.3 口径）",
        ),
        Case(
            name="static-assets-keep-own-type",
            given="GET 前端构建产物（index.html / *.js）",
            expect="content-type 分别为 text/html、javascript；不得被响应壳包成 JSON",
        ),
        Case(
            name="error-still-json-inside-sse-negotiation",
            given="SSE 协商成功但首个事件即为错误（如 Agent 不存在）",
            expect="仍为 text/event-stream，错误以事件帧下发（不得中途改成 404 JSON），"
            "具体帧形状由 V0.3.0 冻结",
        ),
    ),
    notes=(
        "19 帧的逐字节判据由 V0.3.0 的 SSE 冻结件承接（本轮 C-05），"
        "本骨架只固定协商层，不复制帧内容。",
        "JSON 壳的字段集以 contracts/openapi.v1.frozen.json 为准。",
    ),
)

_STRINGLY = ConformanceSpec(
    id="stringly-contracts",
    title="字符串化契约（枚举字面值 / 时间格式 / uuid 形态）",
    applies_to=("V0.1.0",),
    scope=("@wbtime/core", "@wbtime/contracts", "@wbtime/database"),
    roadmap=(
        "docs/V1.0/00-版本路线图.md §4.1「平台基座」② /「数据层」②",
        "docs/V1.0/00-版本路线图.md §4.1「Task / TaskQueue」②（复合键字符串格式）",
    ),
    source=(
        SourceRef(
            file="packages/core/src/wbtime_ai_core/id.py",
            line=4,
            quote="UUIDv7",
            why="全平台唯一 ID 入口产出 UUIDv7 字符串（时间有序）",
        ),
        SourceRef(
            file="packages/core/src/wbtime_ai_core/error_codes.py",
            line=15,
            quote="class ErrorCode(StrEnum)",
            why="错误码是**字符串枚举**，JSON 里是 \"NOT_FOUND\" 而非数字",
        ),
        SourceRef(
            file="packages/common/src/wbtime_ai_common/time.py",
            line=40,
            quote="def to_iso8601",
            why="时间序列化唯一出口：ISO 8601 + UTC（形如 2025-01-01T00:00:00+00:00）",
        ),
        SourceRef(
            file="packages/common/src/wbtime_ai_common/time.py",
            line=52,
            quote="def from_iso8601",
            why="解析侧兼容 Z 后缀，并归一到 UTC",
        ),
        SourceRef(
            file="tests/unit/test_core_id.py",
            line=11,
            quote="test_generate_id_returns_uuid7_string",
            why="既有判据：generate_id() 可被 uuid.UUID 解析且版本位 = 7",
        ),
        SourceRef(
            file="tests/integration/test_id_convention.py",
            line=1,
            quote="ID 唯一入口约定扫描断言",
            why="扫描断言禁止 uuid4 旁路 —— TS 侧需等价的门禁（dependency-cruiser 或 eslint 规则）",
        ),
        SourceRef(
            file="packages/database/src/wbtime_ai_database/models/task.py",
            line=52,
            quote="f\"{target_type}:{target_id}:{fire_time.isoformat()}\"",
            why="复合幂等键是冒号拼接的字符串，格式本身是契约",
        ),
    ),
    cases=(
        Case(
            name="id-is-uuidv7-string",
            given="任一实体主键由唯一入口生成",
            expect="36 字符小写 UUID 字符串，version nibble = 7；同一毫秒内生成的序列仍单调递增",
        ),
        Case(
            name="id-entry-point-is-unique",
            given="在 packages/ 与 apps/ 中搜索裸 uuid4 / randomUUID",
            expect="零命中（等价门禁必须存在，否则 I-2 类不变量在 TS 侧消失）",
        ),
        Case(
            name="datetime-is-iso8601-utc",
            given="任何响应中的时间字段",
            expect="ISO 8601 字符串且带 +00:00 偏移（UTC）；解析侧接受 Z 并归一到 UTC；"
            "禁止 Unix 时间戳数字",
        ),
        Case(
            name="enum-is-literal-string",
            given="错误码 / 状态枚举出现在 JSON 里",
            expect="序列化为字面值字符串（\"NOT_FOUND\" / \"RUNNING\"），"
            "不得变成数字或大小写变形",
        ),
        Case(
            name="composite-key-string-format",
            given="调度幂等键由 (target_type, target_id, fire_time) 合成",
            expect="形如 `agent:01J...:2026-10-20T00:00:00+00:00`；时间部分用 ISO 8601，"
            "分隔符固定为 `:`",
        ),
    ),
    notes=(
        "「字符串化契约」是换栈时最容易悄悄变形的部分：TS 的 Date 默认序列化是 "
        "`toISOString()`（毫秒 + Z），与旧线 `+00:00` 不同 —— 必须显式归一，否则 19 帧与 "
        "openapi 示例都会漂移。",
        "枚举字面值以 contracts/openapi.v1.frozen.json 的 components.schemas 为准。",
    ),
)

#: The four skeletons, in stable order.
SPECS: tuple[ConformanceSpec, ...] = (
    _TENANT_404,
    _IDEMPOTENCY,
    _CONTENT_NEGOTIATION,
    _STRINGLY,
)


# ---------------------------------------------------------------------------
# Source verification
# ---------------------------------------------------------------------------


def verify_sources(spec: ConformanceSpec, source_root: str, read_line: LineReader) -> list[str]:
    """Check every :class:`SourceRef` of ``spec`` against the legacy tree.

    Args:
        spec: The skeleton to verify.
        source_root: Normalised legacy root (only used in error messages).
        read_line: Callable ``(absolute_posix_path, lineno) -> str`` returning the
            stripped line, or raising :class:`SourceVerificationError`.

    Returns:
        One human-readable ``"file:line ok"`` string per verified reference.

    Raises:
        SourceVerificationError: If a file is missing, the line is out of range,
            or the quoted fragment is absent from that exact line.
    """
    evidence: list[str] = []
    for reference in spec.source:
        absolute = f"{source_root.rstrip('/')}/{reference.file}"
        line_text = read_line(absolute, reference.line)
        if reference.quote not in line_text:
            raise SourceVerificationError(
                f"{spec.id}: quote not found at {reference.file}:{reference.line}\n"
                f"  expected fragment: {reference.quote!r}\n"
                f"  actual line      : {line_text!r}"
            )
        evidence.append(f"{reference.file}:{reference.line} ok")
    return evidence


@dataclasses.dataclass
class LineReader:
    """Reads and memoises specific lines of the read-only legacy tree.

    Attributes:
        cache: ``absolute path -> lines`` memo, so a spec with several refs into
            the same file reads it once.
    """

    cache: dict[str, list[str]] = dataclasses.field(default_factory=dict)

    def __call__(self, absolute_posix_path: str, lineno: int) -> str:
        """Return the stripped text of ``lineno`` (1-based) of the given file.

        Args:
            absolute_posix_path: Absolute path with forward slashes.
            lineno: 1-based line number.

        Returns:
            The line without trailing newline (not stripped of leading spaces, so
            indentation-based quotes stay meaningful).

        Raises:
            SourceVerificationError: When the file or line does not exist.
        """
        lines = self.cache.get(absolute_posix_path)
        if lines is None:
            try:
                with open(absolute_posix_path, encoding="utf-8", errors="replace") as handle:
                    lines = handle.read().splitlines()
            except OSError as error:
                raise SourceVerificationError(
                    f"cannot read legacy source file: {absolute_posix_path}: {error}"
                ) from error
            self.cache[absolute_posix_path] = lines
        if lineno < 1 or lineno > len(lines):
            raise SourceVerificationError(
                f"line {lineno} out of range (file has {len(lines)} lines): {absolute_posix_path}"
            )
        return lines[lineno - 1]


# ---------------------------------------------------------------------------
# YAML rendering (stdlib only: JSON scalars are valid YAML 1.2 scalars)
# ---------------------------------------------------------------------------


def _scalar(value: object) -> str:
    """Render one scalar as a YAML-safe token.

    Strings go through :func:`json.dumps` (double-quoted, escapes control chars)
    which is a valid YAML 1.2 double-quoted scalar; integers are emitted bare.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _render_list(lines: list[str], key: str, values: Iterable[str], indent: int) -> None:
    """Append a block sequence of strings under ``key``."""
    pad = " " * indent
    lines.append(f"{pad}{key}:")
    for value in values:
        lines.append(f"{pad}  - {_scalar(value)}")


def render_yaml(spec: ConformanceSpec) -> str:
    """Render one skeleton as deterministic YAML text.

    Determinism matters: the artifact is covered by
    ``contracts/manifest.sha256``, so re-running ``export`` must not change a
    single byte.

    Args:
        spec: The skeleton to render.

    Returns:
        YAML text, UTF-8, LF, ending with exactly one newline.
    """
    lines: list[str] = [
        "# GENERATED by scripts/extract-from-py/export_migration.py -- do not edit by hand.",
        "# Re-generate with: python scripts/extract-from-py/run.py export --only migration",
        f"# status: {STATUS_SKELETON} -- invariants named;"
        " full matrix filled by the owning version.",
        "---",
        f"id: {_scalar(spec.id)}",
        f"title: {_scalar(spec.title)}",
        f"status: {_scalar(STATUS_SKELETON)}",
        f"generated_by: {_scalar(GENERATED_BY)}",
    ]
    _render_list(lines, "applies_to", spec.applies_to, 0)
    _render_list(lines, "scope", spec.scope, 0)
    _render_list(lines, "roadmap", spec.roadmap, 0)
    lines.append("source:")
    for reference in spec.source:
        lines.append(f"  - file: {_scalar(reference.file)}")
        lines.append(f"    line: {reference.line}")
        lines.append(f"    quote: {_scalar(reference.quote)}")
        lines.append(f"    why: {_scalar(reference.why)}")
    lines.append("cases:")
    for case in spec.cases:
        lines.append(f"  - name: {_scalar(case.name)}")
        lines.append(f"    given: {_scalar(case.given)}")
        lines.append(f"    expect: {_scalar(case.expect)}")
    if spec.notes:
        _render_list(lines, "notes", spec.notes, 0)
    return "\n".join(lines) + "\n"
