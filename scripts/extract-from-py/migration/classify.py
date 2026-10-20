"""Classification rules that turn a legacy pytest node id into a disposition.

The migration map answers one question per old test case: *what do we do with
it?*  The answer (``bucket``) and its destination (``target_module`` /
``target_version``) are **derived from the roadmap**, not from taste:

* ``docs/V1.0/00-版本路线图.md`` §4.1 「归并总表」 gives every legacy capability
  a 归类 ①/②/③ and a new landing version;
* §3.2 gives the product-version → engineering-phase mapping used to fill
  ``target_version``.

This module encodes that table as an **ordered, first-match-wins** rule list
keyed on the relative test path.  Ordering is load-bearing: e.g.
``tests/unit/test_domain_workspace.py`` must hit the workspace rule before the
generic ``test_domain_*`` rule.

Anything that matches no rule is reported as ``TBD`` with an explicit note — the
builder then fails loudly (``strict=True``) rather than inventing a version
number, which is the whole point of having a table instead of a guess.

Case-level overrides
--------------------
Rules key on the *file*.  Some files mix cases with genuinely different
dispositions (a legacy redirect shim next to an API-level fail-closed security
assertion), so :data:`CASE_OVERRIDES` narrows a disposition down to one node id
and each override carries its **own** note.  Sharing one note across cases is
forbidden in spirit: it makes the dispositions unauditable, which is how the
only fail-closed gate in the tree nearly got dropped.

Buckets
-------
``1``
    ① 原样移植 — semantics *and* the assertion survive the language switch.
``2``
    ② 需重设计 — capability continues, implementation and gate are rewritten.
``3``
    ③ 放弃或合并 — dropped, deferred out of 1.0, or folded into another case.

Only the Python standard library is used here.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

__all__ = [
    "BUCKET_PLAIN_PORT",
    "BUCKET_REDESIGN",
    "BUCKET_DROP",
    "BUCKET_LABELS",
    "TARGET_VERSION_UNKNOWN",
    "UnmatchedPathError",
    "UnmatchedCaseOverrideError",
    "Rule",
    "Disposition",
    "CaseOverride",
    "RULES",
    "CASE_OVERRIDES",
    "classify",
    "case_override",
    "known_override_ids",
    "ROADMAP_DOC",
    "ROADMAP_SECTION_BUCKETS",
]

#: ① 原样移植.
BUCKET_PLAIN_PORT = 1
#: ② 需重设计.
BUCKET_REDESIGN = 2
#: ③ 放弃或合并.
BUCKET_DROP = 3


class UnmatchedPathError(RuntimeError):
    """Raised in strict mode when a test file matches no classification rule.

    Carrying the offending paths in the message (instead of silently emitting
    ``TBD``) is the mechanism that stops the builder from inventing versions.
    """

    def __init__(self, paths: Sequence[str]) -> None:
        self.paths = list(paths)
        joined = "\n  ".join(self.paths)
        super().__init__(
            f"{len(self.paths)} test file(s) match no classification rule "
            f"(add a rule to migration/classify.py):\n  {joined}"
        )


class UnmatchedCaseOverrideError(RuntimeError):
    """Raised in strict mode when a :data:`CASE_OVERRIDES` entry names a test that no longer exists.

    A stale override is worse than a missing one: it reads like a decision about a
    live test while the test it describes is gone.  Failing the build forces the
    table to be pruned instead of accumulating fiction.
    """

    def __init__(self, test_ids: Sequence[str]) -> None:
        self.test_ids = list(test_ids)
        joined = "\n  ".join(self.test_ids)
        super().__init__(
            f"{len(self.test_ids)} case override(s) reference test ids that are not in the "
            f"collection ledger (remove them from migration/classify.py::CASE_OVERRIDES):\n  {joined}"
        )


#: Human-readable bucket names, aligned with roadmap §4.1 wording.
BUCKET_LABELS: dict[int, str] = {
    BUCKET_PLAIN_PORT: "① 原样移植",
    BUCKET_REDESIGN: "② 需重设计",
    BUCKET_DROP: "③ 放弃或合并",
}

#: Sentinel used when no rule could decide the target version.
TARGET_VERSION_UNKNOWN = "TBD"

#: Roadmap document that supplies the ①/②/③ classes (relative to repo root).
ROADMAP_DOC = "docs/V1.0/00-版本路线图.md"

#: Roadmap section holding the merge table.
ROADMAP_SECTION_BUCKETS = "§4.1 归并总表"

#: Roadmap section holding the product-version → engineering-phase mapping.
ROADMAP_SECTION_VERSIONS = "§3.2"


@dataclasses.dataclass(frozen=True)
class Rule:
    """One classification rule.

    Attributes:
        pattern: Regex matched against the POSIX relative test path
            (``tests/unit/test_core_id.py``).  Matched with :func:`re.search`
            anchored at the start by convention (``^``).
        capability: Legacy capability cluster name (roadmap §4.1 wording).
        bucket: ①/②/③ classification.
        target_module: Destination TS package/workspace path.
        target_version: Landing version of the capability, or
            :data:`TARGET_VERSION_UNKNOWN`.
        note: Why this disposition; merged into the CSV ``note`` column.
    """

    pattern: str
    capability: str
    bucket: int
    target_module: str
    target_version: str
    note: str

    def matches(self, relative_path: str) -> bool:
        """Return ``True`` when ``relative_path`` selects this rule."""
        return re.search(self.pattern, relative_path) is not None


@dataclasses.dataclass(frozen=True)
class Disposition:
    """The answer for one test case."""

    capability: str
    bucket: int
    target_module: str
    target_version: str
    note: str
    rule_pattern: str


@dataclasses.dataclass(frozen=True)
class CaseOverride:
    """A per-test-case disposition that overrides its file's rule.

    File-level rules answer "what happens to this capability"; they are too coarse
    when a single file mixes a genuine legacy-only shim with a semantically
    different assertion.  ``test_mcp_permissions_redirect.py`` is the case in
    point: two of its three tests assert redirect-shim behaviour (droppable), one
    asserts an **API-level fail-closed security invariant** that must be rebuilt.
    A single shared note would have hidden that difference -- which is exactly the
    defect (D-2) this table exists to prevent.

    Attributes:
        test_id: Exact pytest node id (POSIX relative path ``::`` test name).
        capability: Legacy capability cluster name; overrides the rule's value so
            the CSV can be grouped by the *real* semantics of the case.
        bucket: ①/②/③ classification.
        target_module: Destination TS package/workspace path.
        target_version: Landing version of the capability.
        note: Why this case differs from its file rule; merged into the CSV note.
    """

    test_id: str
    capability: str
    bucket: int
    target_module: str
    target_version: str
    note: str

    @property
    def test_name(self) -> str:
        """Return the bare test name (the part after ``::``)."""
        return self.test_id.rsplit("::", 1)[-1]


# ---------------------------------------------------------------------------
# Rule table — ORDER IS LOAD-BEARING (first match wins)
# ---------------------------------------------------------------------------
#
# Version anchors from roadmap §3.2 / §4.1:
#   V0.1.0  基座 / 数据层 / common-core-config-logging-event / 契约层
#   V0.2.0  identity / auth / permission / tenant / organization / workspace(Files·Env)
#   V0.3.0  agent / runtime / tool / skill / mcp / conversation / sandbox(LocalProcess)
#   V0.4.0  knowledge / memory
#   V0.5.0  workflow / task / queue / evaluation / approval
#   V0.6.0  workspace 完整档 / sandbox Docker+Egress / retention
#   V0.7.0  plugin / marketplace
#   V0.8.0  cli / worker / 前端
#   V1.0.0  制度：审计体系 / 三层门禁 / 五件套

RULES: tuple[Rule, ...] = (
    # -- 制度 / 门禁工具链（① 制度继承，工具链替换） -------------------------
    Rule(
        r"^tests/unit/test_check_manual_evidence\.py$",
        "审计体系·manual 证据校验",
        BUCKET_PLAIN_PORT,
        "tools/governance",
        "V1.0.0",
        "§4.1「审计体系/三层门禁/五件套/check_docs.py」→ ① 制度继承（工具链替换）",
    ),
    Rule(
        r"^tests/integration/test_discipline_scan\.py$",
        "审计体系·纪律扫描",
        BUCKET_PLAIN_PORT,
        "tools/governance",
        "V1.0.0",
        "§4.1 同上；脚本换成 TS 侧实现，四类违规样本判据逐字继承",
    ),
    Rule(
        r"^tests/integration/test_open_source\.py$",
        "审计体系·开源纪律（禁 edition gate）",
        BUCKET_PLAIN_PORT,
        "tools/governance",
        "V1.0.0",
        "§4.1 同上；断言「源码无商业分流 / flag 非 edition gate」语言无关",
    ),
    Rule(
        r"^tests/unit/test_scan_wiring\.py$",
        "装配可达性扫描（防假绿）",
        BUCKET_PLAIN_PORT,
        "tools/governance",
        "V1.0.0",
        "§4.1 制度继承；J-1 接线面自检，违规样本判据可原样搬",
    ),
    # -- 分层纪律（② mypy 插件 → dependency-cruiser） ------------------------
    Rule(
        r"^tests/integration/test_layering\.py$",
        "I-2 强制分层（禁裸 id / 分层依赖）",
        BUCKET_REDESIGN,
        "tools/dependency-cruiser",
        "V0.1.0",
        "§4.1「I-2 强制 ScopeFilter」②：mypy 插件 → dependency-cruiser + ScopedRepo<T>；"
        "分层断言语义继承，实现换成 3 条规则",
    ),
    # -- 数据层（②） ---------------------------------------------------------
    Rule(
        r"^tests/integration/migrations/",
        "数据层·迁移链（0008→0018 双方言）",
        BUCKET_REDESIGN,
        "@wbtime/database",
        "V0.1.0",
        "§4.1「数据层」②：61 表 / 双方言 / 软删，重设计率 70%；迁移用例按新迁移工具重写，"
        "版本推进与回滚语义继承",
    ),
    Rule(
        r"^tests/integration/test_(migrations|migration_phase1)\.py$",
        "数据层·迁移入口",
        BUCKET_REDESIGN,
        "@wbtime/database",
        "V0.1.0",
        "§4.1「数据层」②：同上",
    ),
    Rule(
        r"^tests/integration/test_postgres_smoke\.py$",
        "数据层·PG 冒烟",
        BUCKET_REDESIGN,
        "@wbtime/database",
        "V0.1.0",
        "§4.1「数据层」②：双档 DDL 零差异判据由 §3.3 M-01 接管",
    ),
    Rule(
        r"^tests/nfr/test_pg_baselines\.py$",
        "数据层·PG 侧 NFR 基线",
        BUCKET_REDESIGN,
        "@wbtime/database",
        "V0.1.0",
        "§4.1「数据层」②：基线数值继承，测量脚本重写",
    ),
    Rule(
        r"^tests/unit/test_storage_local\.py$",
        "存储端口（LocalStorage）",
        BUCKET_REDESIGN,
        "@wbtime/storage",
        "V0.1.0",
        "§4.1「平台基座」②：端口语义继承，实现换 node:fs",
    ),
    Rule(
        r"^tests/unit/test_domain_workspace\.py$",
        "Workspace 领域模型",
        BUCKET_REDESIGN,
        "@wbtime/workspace",
        "V0.2.0",
        "§4.1「Workspace 基础（Files/Env）」①②：领域模型继承，路径逃逸防护重写",
    ),
    Rule(
        r"^tests/unit/workspace/test_managed_paths\.py$",
        "Workspace·ManagedPaths 路径逃逸防护",
        BUCKET_REDESIGN,
        "@wbtime/workspace",
        "V0.2.0",
        "§4.1「Workspace 基础」②：路径规范化/逃逸判据逐条继承，实现重写（node:path）",
    ),
    # -- 平台基座（②） -------------------------------------------------------
    Rule(
        r"^tests/unit/test_core_",
        "平台基座·core（id / result）",
        BUCKET_REDESIGN,
        "@wbtime/core",
        "V0.1.0",
        "§4.1「平台基座 common/core」②：语义继承，实现重写；uuid 形态另见 "
        "contracts/conformance/stringly-contracts.yaml",
    ),
    Rule(
        r"^tests/unit/test_config_(settings|mode_branch)\.py$",
        "平台基座·config",
        BUCKET_REDESIGN,
        "@wbtime/config",
        "V0.1.0",
        "§4.1「平台基座 config」②：配置项语义继承，Schema 换 TypeBox",
    ),
    Rule(
        r"^tests/unit/test_feature_flags\.py$",
        "平台基座·Feature Flag",
        BUCKET_REDESIGN,
        "@wbtime/config",
        "V0.1.0",
        "§4.1「平台基座」②；flag 语义受开源纪律约束（禁 edition gate）",
    ),
    Rule(
        r"^tests/integration/test_feature_flags\.py$",
        "平台基座·Feature Flag（API 面）",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.1.0",
        "§4.1「平台基座」②：同上",
    ),
    Rule(
        r"^tests/unit/test_event_(base_consistency|bus|dispatcher_scope|loop_non_blocking)\.py$",
        "平台基座·事件总线",
        BUCKET_REDESIGN,
        "@wbtime/events",
        "V0.1.0",
        "§4.1「平台基座 event」②：Protocol → interface，LocalEventBus 重写",
    ),
    Rule(
        r"^tests/integration/test_event_bus_agent\.py$",
        "平台基座·事件总线（Agent 消费）",
        BUCKET_REDESIGN,
        "@wbtime/events",
        "V0.1.0",
        "§4.1「平台基座 event」②：同上",
    ),
    Rule(
        r"^tests/integration/event/test_event_inventory\.py$",
        "平台基座·事件清单（含 SSE 域→通道映射）",
        BUCKET_REDESIGN,
        "@wbtime/events",
        "V0.1.0",
        "§4.1「平台基座 event」②；清单断言跨版本增量追加（SSE 通道映射归 V0.3.0）",
    ),
    Rule(
        r"^tests/unit/test_domain_(entities|phase1_entities|value_objects)\.py$",
        "数据层·领域实体与值对象",
        BUCKET_REDESIGN,
        "@wbtime/domain",
        "V0.1.0",
        "§4.1「数据层」②：实体/值对象语义继承，实现换 TypeBox + ScopedRepo",
    ),
    Rule(
        r"^tests/unit/test_response_shell_value_judgement\.py$",
        "平台基座·响应壳 / 错误码",
        BUCKET_REDESIGN,
        "@wbtime/contracts",
        "V0.1.0",
        "§4.1「平台基座 错误码+响应壳」②：壳形状与错误码集继承（裁定书 §11.2 改码值）",
    ),
    Rule(
        r"^tests/integration/test_errors\.py$",
        "平台基座·错误映射（域码 → HTTP）",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.1.0",
        "§4.1「平台基座」②；错误码表按裁定书 §11.2 口径（VALIDATION_ERROR=422 / "
        "UNAUTHORIZED=401）重写",
    ),
    Rule(
        r"^tests/integration/test_observability\.py$",
        "平台基座·logging / metrics",
        BUCKET_REDESIGN,
        "@wbtime/observability",
        "V0.1.0",
        "§4.1「平台基座 logging」②：structlog → pino；字段名判据继承",
    ),
    Rule(
        r"^tests/integration/test_health\.py$",
        "平台基座·health 端点",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.1.0",
        "§4.1「平台基座」②；`GET /health` 是 134 operation 中唯一非 /api/v1 端点"
        "（见 contracts/README.md）",
    ),
    Rule(
        r"^tests/unit/test_env_readiness\.py$",
        "测试基座·环境就绪门",
        BUCKET_REDESIGN,
        "@wbtime/testing",
        "V0.1.0",
        "§4.1「平台基座」②：pytest 就绪探针 → vitest setup；就绪判据继承",
    ),
    Rule(
        r"^tests/unit/test_application_idempotency\.py$",
        "平台基座·幂等记录（请求指纹）",
        BUCKET_REDESIGN,
        "@wbtime/core",
        "V0.1.0",
        "§4.1「平台基座」②；口径冻结进 contracts/conformance/idempotency.yaml",
    ),
    Rule(
        r"^tests/integration/test_idempotency\.py$",
        "平台基座·幂等记录（HTTP 面）",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.1.0",
        "§4.1「平台基座」②；口径冻结进 contracts/conformance/idempotency.yaml",
    ),
    Rule(
        r"^tests/integration/test_id_convention\.py$",
        "平台基座·ID 唯一入口（UUIDv7）",
        BUCKET_REDESIGN,
        "@wbtime/core",
        "V0.1.0",
        "§4.1「平台基座」②；uuid 形态冻结进 "
        "contracts/conformance/stringly-contracts.yaml",
    ),
    Rule(
        r"^tests/contracts/test_extension_points\.py$",
        "契约层·9 个扩展点 interface",
        BUCKET_REDESIGN,
        "@wbtime/contracts",
        "V0.1.0",
        "§4.1 plugin 行 + M-05 E-3：interface 声明归 V0.1.0；ABI 换 TS，"
        "断言以类型断言重写（loader/签名/沙箱留 V0.7.0）",
    ),
    # -- 身份与权限（V0.2.0） ------------------------------------------------
    Rule(
        r"^tests/unit/test_security_(jwt|password|crypto|login_guard|secret_provider)\.py$",
        "身份·密码学原语（JWT / argon2id / AES-GCM）",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：argon2id→@node-rs/argon2、JWT→jose、AES-GCM→node:crypto",
    ),
    Rule(
        r"^tests/unit/test_secret_key_min_length\.py$",
        "身份·密钥长度下限",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：密钥强度判据继承",
    ),
    Rule(
        r"^tests/integration/test_security_session_revocation\.py$",
        "身份·会话吊销",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：吊销语义（refresh 链失效）继承，存储重写",
    ),
    Rule(
        r"^tests/integration/test_identity_persistence\.py$",
        "身份·持久化",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：表结构按 61 表 DDL 冻结件，实现重写",
    ),
    Rule(
        r"^tests/unit/test_identity_bootstrap\.py$",
        "身份·引导",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：同上",
    ),
    Rule(
        r"^tests/unit/test_bootstrap_admin_seed\.py$",
        "身份·管理员种子",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：种子语义继承（首启幂等）",
    ),
    Rule(
        r"^tests/integration/test_api_(auth|login_lock)\.py$",
        "身份·登录 / 锁定",
        BUCKET_REDESIGN,
        "@wbtime/identity",
        "V0.2.0",
        "§4.1「身份与多租户」②：登录失败计数与锁定判据继承",
    ),
    Rule(
        r"^tests/unit/test_permission_checker\.py$",
        "权限·SDK / RBAC 判定",
        BUCKET_PLAIN_PORT,
        "@wbtime/permission",
        "V0.2.0",
        "§4.1「权限 SDK / RBAC / 资源×动作矩阵」①：模型语义与权限码命名空间原样继承",
    ),
    Rule(
        r"^tests/unit/security/test_(resource_permission|capability)\.py$",
        "权限·资源×动作矩阵",
        BUCKET_PLAIN_PORT,
        "@wbtime/permission",
        "V0.2.0",
        "§4.1「权限 SDK」①：判定矩阵是纯逻辑，判据逐字继承",
    ),
    Rule(
        r"^tests/integration/test_api_rbac\.py$",
        "权限·RBAC HTTP 面",
        BUCKET_PLAIN_PORT,
        "@wbtime/permission",
        "V0.2.0",
        "§4.1「权限 SDK」①：状态码与错误码判据继承",
    ),
    Rule(
        r"^tests/integration/permission/test_single_chain\.py$",
        "权限·单一判定链",
        BUCKET_PLAIN_PORT,
        "@wbtime/permission",
        "V0.2.0",
        "§4.1「权限 SDK」①：单链不变量继承",
    ),
    Rule(
        r"^tests/integration/permission/test_(mcp|tools)_permissions_redirect\.py$",
        "权限·旧路径 redirect shim",
        BUCKET_DROP,
        "@wbtime/permission",
        "V0.2.0",
        "**文件默认判定，本文件 4 条用例均已由 CASE_OVERRIDES 逐条覆盖**（不得直接沿用本句）："
        "旧线 `/mcp/*`、`/tools/*` 权限入口是 redirect 到单一判定链的历史 shim，TS 线无历史路径，"
        "shim 与其判据一并放弃；判定链语义由 tests/integration/permission/test_single_chain.py 覆盖。"
        "⚠️ 该文件内**不是**每条都属 shim——`test_unmapped_mcp_tool_is_fail_closed_and_roundtrips` "
        "是 API 级 fail-closed 安全断言，已单独改判 ②（D-2）；新增用例必须显式判定",
    ),
    Rule(
        r"^tests/integration/test_cross_tenant_404\.py$",
        "I-1 跨租户 404 不变量",
        BUCKET_PLAIN_PORT,
        "@wbtime/security",
        "V0.2.0",
        "§4.1「I-1 跨租户 404 / I-3 越权回归」①：判据逐字继承（≥11 资源族参数化）；"
        "口径冻结进 contracts/conformance/tenant-404.yaml",
    ),
    Rule(
        r"^tests/(integration/test_audit_|unit/test_audit_masking)",
        "审计落库（who/action/resource/outcome）",
        BUCKET_REDESIGN,
        "@wbtime/audit",
        "V0.2.0",
        "§4.1 未单列 audit 能力簇；按「身份与多租户」同版落位推定（审计四要素由身份/API "
        "中间件写入）。⚠️ 推定项，架构师复核后可改",
    ),
    # -- 敏感扫描（M-04 下沉 @wbtime/security，V0.2.0） ----------------------
    Rule(
        r"^tests/integration/test_(secret_scan|credential_scan|sandbox_scan)\.py$",
        "敏感扫描 scan_sensitive（M-04 下沉）",
        BUCKET_REDESIGN,
        "@wbtime/security",
        "V0.2.0",
        "§4.1「plugin.marketplace.scan_sensitive」②：纯函数下沉 @wbtime/security（≈0.5 人日），"
        "正则为判据、逐条继承",
    ),
    Rule(
        r"^tests/integration/test_api_workspaces\.py$",
        "Workspace·HTTP 面",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.2.0",
        "§4.1「Workspace 基础」①②：路由与错误码继承，文件操作重写",
    ),
    Rule(
        r"^tests/integration/test_workspace_persistence\.py$",
        "Workspace·持久化",
        BUCKET_REDESIGN,
        "@wbtime/workspace",
        "V0.2.0",
        "§4.1「Workspace 基础」②：同上",
    ),
    # -- Model Provider（V0.3.0，②） ----------------------------------------
    Rule(
        r"^tests/contracts/test_(model_provider|model_registry|registry_coverage)\.py$",
        "Model Provider·契约套件",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider + 凭证 + Router + 计价」②：7 个手写 httpx 适配器 → AI SDK"
        "（仅借 Provider 矩阵，不借 agent loop）",
    ),
    Rule(
        r"^tests/unit/model/",
        "Model Provider·共享客户端",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider」②：同上",
    ),
    Rule(
        r"^tests/unit/test_(model_catalog|model_provider_contract|model_registry|model_router)\.py$",
        "Model Provider·目录 / Router",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider」②：路由与选型判据继承",
    ),
    Rule(
        r"^tests/unit/test_(cost_calculator|domain_price_item_effective)\.py$",
        "Model Provider·计价",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider … 计价」②：计价是纯逻辑，数值判据逐字继承",
    ),
    Rule(
        r"^tests/unit/test_provider_errors\.py$",
        "Model Provider·错误归一",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider」②：错误分类继承，异常类型换 TS",
    ),
    Rule(
        r"^tests/unit/test_providers(_container|_w2)?\.py$",
        "Model Provider·装配容器",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider」②：容器/装配语义继承",
    ),
    Rule(
        r"^tests/unit/test_providers_worker\.py$",
        "Worker·依赖装配",
        BUCKET_REDESIGN,
        "@wbtime/worker",
        "V0.8.0",
        "§4.1「Worker（队列消费 + 恢复）」②：Arq → BullMQ，装配判据继承",
    ),
    Rule(
        r"^tests/integration/test_model_(credentials|persistence|provider_binding)\.py$",
        "Model Provider·凭证绑定与持久化",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider + 凭证」②：AES-GCM → node:crypto，绑定语义继承",
    ),
    Rule(
        r"^tests/integration/credential/test_multi_credential\.py$",
        "Model Provider·多凭证",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider + 凭证」②：同上",
    ),
    Rule(
        r"^tests/integration/test_credential_encryption\.py$",
        "Model Provider·凭证加密",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider + 凭证」②：AES-GCM → node:crypto round-trip 判据继承",
    ),
    Rule(
        r"^tests/integration/test_api_credentials\.py$",
        "Model Provider·凭证 HTTP 面",
        BUCKET_REDESIGN,
        "@wbtime/provider",
        "V0.3.0",
        "§4.1「Model Provider」②：脱敏判据继承",
    ),
    Rule(
        r"^tests/integration/test_api_models_tools\.py$",
        "Model Provider·模型/工具清单面",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.3.0",
        "§4.1「Model Provider」②：清单形状继承",
    ),
    # -- Agent / Runtime / Tool / Skill / MCP / Sandbox（V0.3.0） ------------
    Rule(
        r"^tests/unit/test_agent_version_immutable\.py$",
        "Agent·版本不可变",
        BUCKET_PLAIN_PORT,
        "@wbtime/agent",
        "V0.3.0",
        "§4.1「Agent / Agent Version（数据驱动配置）」①：核心不变量原样继承",
    ),
    Rule(
        r"^tests/unit/test_application_agent_commands\.py$",
        "Agent·命令面",
        BUCKET_PLAIN_PORT,
        "@wbtime/agent",
        "V0.3.0",
        "§4.1「Agent」①：命令/校验语义继承",
    ),
    Rule(
        r"^tests/unit/test_domain_agent_values\.py$",
        "Agent·值对象",
        BUCKET_PLAIN_PORT,
        "@wbtime/agent",
        "V0.3.0",
        "§4.1「Agent」①：值约束语义继承",
    ),
    Rule(
        r"^tests/integration/test_agent_data_driven\.py$",
        "Agent·配置驱动（不写死在代码类）",
        BUCKET_PLAIN_PORT,
        "@wbtime/agent",
        "V0.3.0",
        "§4.1「Agent / Agent Version」①：核心不变量原样继承",
    ),
    Rule(
        r"^tests/unit/test_agent_events\.py$",
        "Conversation/Run·AgentEvent 回放",
        BUCKET_PLAIN_PORT,
        "@wbtime/conversation",
        "V0.3.0",
        "§4.1「Conversation / Message / Run / ToolCall / AgentEvent 回放」①："
        "回放与续传语义原样继承（判据 = 19 帧 + Last-Event-ID）",
    ),
    Rule(
        r"^tests/unit/test_domain_conversation_values\.py$",
        "Conversation·值对象",
        BUCKET_PLAIN_PORT,
        "@wbtime/conversation",
        "V0.3.0",
        "§4.1「Conversation / Message / Run」①：同上",
    ),
    Rule(
        r"^tests/integration/test_conversation_(rename|replay)\.py$",
        "Conversation·改名 / 回放",
        BUCKET_PLAIN_PORT,
        "@wbtime/conversation",
        "V0.3.0",
        "§4.1「Conversation / Message / Run」①：回放判据原样继承",
    ),
    Rule(
        r"^tests/unit/test_runtime_",
        "Runtime·ReAct 循环 / 上下文",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime（Context/Prompt/Planner/Event/Sandbox 执行链）」②：重设计率 55%，"
        "本线最难点",
    ),
    Rule(
        r"^tests/unit/test_context_truncate\.py$",
        "Runtime·上下文截断",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：截断策略语义继承，实现重写",
    ),
    Rule(
        r"^tests/unit/test_execution_policy_retry\.py$",
        "Runtime·执行策略（重试）",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：重试/退避判据继承",
    ),
    Rule(
        r"^tests/integration/test_sse_",
        "Runtime·SSE 19 通道（seq / resume / heartbeat）",
        BUCKET_REDESIGN,
        "@wbtime/sse",
        "V0.3.0",
        "§4.1「Runtime + 19 通道 SSE」②：**19 帧逐字节是硬判据**；"
        "本轮另由 C-05（SSE 冻结件）承接",
    ),
    Rule(
        r"^tests/integration/test_run_",
        "Runtime·Run 生命周期",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：Run 状态机语义继承，实现重写",
    ),
    Rule(
        r"^tests/integration/test_(cancel_timeout|startup_recovery|concurrency_limit)\.py$",
        "Runtime·取消 / 兜底 / 并发上界",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：HEARTBEAT_TIMEOUT 兜底与并发上界判据继承",
    ),
    Rule(
        r"^tests/nfr/test_concurrency\.py$",
        "Runtime·并发基线（max_runs_per_conversation）",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：并发上界数值与无丢失/无重复判据继承；"
        "SELECT FOR UPDATE → PG/事务等价物",
    ),
    Rule(
        r"^tests/nfr/test_perf_baseline\.py$",
        "Runtime·性能基线（SSE p95 / 事件批量写）",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "§4.1「Runtime」②：p95 首帧判据继承；事件批量写基线归 V0.1.0 数据层",
    ),
    Rule(
        r"^tests/integration/test_api_2a_routers\.py$",
        "API·阶段 2a 路由面",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.3.0",
        "§4.1「Runtime」②的下游面：路由存在性与错误码判据继承",
    ),
    Rule(
        r"^tests/integration/test_api_2c_surface\.py$",
        "API·阶段 2c 表面",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.3.0",
        "§4.1「Runtime」②的下游面：同上",
    ),
    Rule(
        r"^tests/contracts/test_tool_interface\.py$",
        "Tool·接口契约",
        BUCKET_REDESIGN,
        "@wbtime/tools",
        "V0.3.0",
        "§4.1「Tool（5 内置 + 权限 + SSRF/路径逃逸）」②：负向用例语义继承，spawner 重写",
    ),
    Rule(
        r"^tests/unit/test_tool_",
        "Tool·注册 / 执行 / 文件作用域",
        BUCKET_REDESIGN,
        "@wbtime/tools",
        "V0.3.0",
        "§4.1「Tool」②：同上",
    ),
    Rule(
        r"^tests/integration/test_tool_(security|permission)\.py$",
        "Tool·SSRF / 路径逃逸 / 权限",
        BUCKET_REDESIGN,
        "@wbtime/tools",
        "V0.3.0",
        "§4.1「Tool」②：负向用例语义继承（SSRF 与路径逃逸判据逐条搬）",
    ),
    Rule(
        r"^tests/integration/test_dangerous_actions\.py$",
        "Tool·危险动作确认",
        BUCKET_REDESIGN,
        "@wbtime/tools",
        "V0.3.0",
        "§4.1「Tool」②：危险动作清单与确认语义继承",
    ),
    Rule(
        r"^tests/contracts/test_mcp\.py$",
        "MCP·Server/Tool 契约",
        BUCKET_REDESIGN,
        "@wbtime/mcp",
        "V0.3.0",
        "§4.1「MCP Server/Tool + 权限链」②：换 @modelcontextprotocol/sdk",
    ),
    Rule(
        r"^tests/integration/mcp/",
        "MCP·权限链",
        BUCKET_REDESIGN,
        "@wbtime/mcp",
        "V0.3.0",
        "§4.1「MCP」②：权限链判定顺序继承",
    ),
    Rule(
        r"^tests/unit/skill/",
        "Skill·领域 / 清单 / 注册表 / 解析",
        BUCKET_REDESIGN,
        "@wbtime/skills",
        "V0.3.0",
        "§4.1「Skill 包 / 清单 / 解析」②：包格式与解析可机械翻译，Loader 重做",
    ),
    Rule(
        r"^tests/integration/runtime/test_skill_",
        "Skill·上下文与装配",
        BUCKET_REDESIGN,
        "@wbtime/skills",
        "V0.3.0",
        "§4.1「Skill」②：同上",
    ),
    Rule(
        r"^tests/contracts/test_sandbox_provider\.py$",
        "Sandbox·Provider 契约（最小档）",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.3.0",
        "§4.1「Sandbox 最小档（LocalProcess）」②：Agent e2e 需要能执行的最小档",
    ),
    Rule(
        r"^tests/unit/test_sandbox_(availability|factory)\.py$",
        "Sandbox·可用性 / 工厂",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.3.0",
        "§4.1「Sandbox 最小档」②：同上；Docker 完整档后移 V0.6.0",
    ),
    Rule(
        r"^tests/integration/test_sandbox_session_repository\.py$",
        "Sandbox·会话仓储",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.3.0",
        "§4.1「Sandbox 最小档」②：同上",
    ),
    # -- 知识 / 记忆（V0.4.0） ----------------------------------------------
    Rule(
        r"^tests/(unit|integration)/knowledge/",
        "Knowledge·切分 / 嵌入 / 检索 / 降级",
        BUCKET_REDESIGN,
        "@wbtime/knowledge",
        "V0.4.0",
        "§4.1「Knowledge」②：Drizzle vector(1536) + hnsw（2 个 raw SQL 索引）；"
        "缺 pgvector 必须显式退化告警；SQLite 档依赖 FTS5",
    ),
    Rule(
        r"^tests/nfr/test_knowledge_perf\.py$",
        "Knowledge·NFR 检索性能",
        BUCKET_REDESIGN,
        "@wbtime/knowledge",
        "V0.4.0",
        "§4.1「Knowledge」②：基线数值继承，测量重写",
    ),
    Rule(
        r"^tests/(unit|integration)/memory/",
        "Memory·短期 / 长期 / 项目 / Agent",
        BUCKET_REDESIGN,
        "@wbtime/memory",
        "V0.4.0",
        "§4.1「Memory」①②：抽取与召回策略继承（①），存储与索引重写（②）⇒ 按 ② 处置",
    ),
    Rule(
        r"^tests/integration/test_api_memory_knowledge\.py$",
        "Knowledge/Memory·HTTP 面",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.4.0",
        "§4.1「Knowledge」「Memory」②的下游面",
    ),
    # -- 工作流 / 评测 / 任务 / 审批（V0.5.0） ------------------------------
    Rule(
        r"^tests/unit/workflow/",
        "Workflow·8 类节点状态机 / 图执行",
        BUCKET_PLAIN_PORT,
        "@wbtime/workflow",
        "V0.5.0",
        "§4.1「Workflow」①：状态机语义原样继承（含 HUMAN_APPROVAL 中断-恢复），"
        "DSL 实现重写",
    ),
    Rule(
        r"^tests/integration/workflow/",
        "Workflow·API / 回放 / 运行",
        BUCKET_PLAIN_PORT,
        "@wbtime/workflow",
        "V0.5.0",
        "§4.1「Workflow」①：同上",
    ),
    Rule(
        r"^tests/integration/evaluation/",
        "Evaluation·评测集 / 批量执行 / scorer / 双版本回归",
        BUCKET_PLAIN_PORT,
        "@wbtime/evaluation",
        "V0.5.0",
        "§4.1「Evaluation」①：scorer 是确定性纯逻辑，桶①直接移植（~357 用例的主力）",
    ),
    Rule(
        r"^tests/integration/approval/",
        "Approval·基础审批",
        BUCKET_PLAIN_PORT,
        "@wbtime/approval",
        "V0.5.0",
        "§4.1「Approval 基础」① + 补口：语义继承，并顺带补 UI 入口（旧线已知缺口）",
    ),
    Rule(
        r"^tests/unit/test_task_(states|queue|scheduler|background_executor)\.py$",
        "Task·TaskQueue / Scheduler",
        BUCKET_REDESIGN,
        "@wbtime/task",
        "V0.5.0",
        "§4.1「Task / TaskQueue / Scheduler（Arq / APScheduler 双档）」②："
        "BullMQ + 自研 InProcessQueue，**双档同构**是判据",
    ),
    Rule(
        r"^tests/integration/scheduler/",
        "Scheduler·冲突 / 幂等 / 装配探针",
        BUCKET_REDESIGN,
        "@wbtime/scheduler",
        "V0.5.0",
        "§4.1「Task / TaskQueue / Scheduler」②：冲突与幂等判据继承",
    ),
    Rule(
        r"^tests/integration/test_agent_task_link\.py$",
        "Task·Agent 关联",
        BUCKET_REDESIGN,
        "@wbtime/task",
        "V0.5.0",
        "§4.1「Task」②：M-05 E-1 明确 Task 实体归 V0.1.0 表结构、行为判据归 V0.5.0",
    ),
    # -- 保留策略（V0.6.0） --------------------------------------------------
    Rule(
        r"^tests/nfr/test_retention_(cleanup|stub)\.py$",
        "数据保留与清理 90/90/90/180",
        BUCKET_REDESIGN,
        "@wbtime/retention",
        "V0.6.0",
        "§4.1「数据保留与清理 90/90/90/180 + 备份恢复」②：策略值继承；"
        "test_retention_stub 的「Phase1 全量保留」断言在参数化后重写",
    ),
    # -- Workspace 完整档 / 远程 / Sandbox Docker（V0.6.0） ------------------
    Rule(
        r"^tests/integration/workspace/",
        "Workspace 完整档·Git 副本 / 文件操作",
        BUCKET_REDESIGN,
        "@wbtime/workspace-git",
        "V0.6.0",
        "§4.1「Workspace 完整档 + Git 副本 + PTY + 远程任务」②：simple-git + node-pty",
    ),
    Rule(
        r"^tests/(security|nfr)/test_remote_workspace_",
        "Remote·边界 / 限额",
        BUCKET_REDESIGN,
        "@wbtime/remote",
        "V0.6.0",
        "§4.1「Workspace 完整档 … 远程任务」②：远程开发是 v0.4 GA 的前置钩子；"
        "边界与限额判据继承",
    ),
    Rule(
        r"^tests/integration/test_remote_(api_authorization|execution_|workspace_profiles)",
        "Remote·授权 / 执行 / 档位",
        BUCKET_REDESIGN,
        "@wbtime/remote",
        "V0.6.0",
        "§4.1「Workspace 完整档 … 远程任务」②：同上",
    ),
    Rule(
        r"^tests/integration/task/test_remote_task_recovery\.py$",
        "Remote·远程任务恢复",
        BUCKET_REDESIGN,
        "@wbtime/remote",
        "V0.6.0",
        "§4.1「Workspace 完整档 … 远程任务」②：恢复判据继承",
    ),
    Rule(
        r"^tests/e2e/test_remote_",
        "Remote·e2e 流",
        BUCKET_REDESIGN,
        "@wbtime/remote",
        "V0.6.0",
        "§4.1「Workspace 完整档 … 远程任务」②：e2e 编排重写，断言语义继承",
    ),
    Rule(
        r"^tests/integration/test_egress_covered\.py$",
        "Sandbox·EgressPolicy 默认拒绝",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.6.0",
        "§4.1「Sandbox 完整档（Docker + EgressPolicy）」②：dockerode；"
        "默认拒绝的 Egress 语义继承",
    ),
    Rule(
        r"^tests/unit/security/test_egress_policy\.py$",
        "Sandbox·EgressPolicy 判定",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.6.0",
        "§4.1「Sandbox 完整档」②：判定矩阵是纯逻辑，判据逐字继承",
    ),
    Rule(
        r"^tests/integration/sandbox/test_remote_egress_enforcement\.py$",
        "Sandbox·Egress 强制执行",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.6.0",
        "§4.1「Sandbox 完整档」②：同上",
    ),
    Rule(
        r"^tests/integration/test_sandbox_isolation\.py$",
        "Sandbox·隔离强度（docker）",
        BUCKET_REDESIGN,
        "@wbtime/sandbox",
        "V0.6.0",
        "§4.1「Sandbox 完整档」②：无 Docker 时 skip/xfail 的门禁语义继承",
    ),
    # -- Plugin / Marketplace（V0.7.0） -------------------------------------
    Rule(
        r"^tests/integration/marketplace/",
        "Marketplace·包格式 / 导入导出 / 静态注册表",
        BUCKET_REDESIGN,
        "@wbtime/marketplace",
        "V0.7.0",
        "§4.1「Marketplace」①②：canonical_dump/load/normalize 语义继承；"
        "v3 追加 dsh SKILL.md 导入（只读不反写）/ 导出（降级 + sidecar）",
    ),
    Rule(
        r"^tests/integration/test_plugin_loading\.py$",
        "Plugin·loader / 9 扩展点",
        BUCKET_REDESIGN,
        "@wbtime/plugin",
        "V0.7.0",
        "§4.1「Plugin：9 扩展点 / loader / 签名信任 / 沙箱」②：ABI 语言变更，唯一窗口；"
        "interface 声明已在 V0.1.0",
    ),
    Rule(
        r"^tests/integration/test_api_loads_plugins\.py$",
        "Plugin·API 装配面",
        BUCKET_REDESIGN,
        "@wbtime/plugin",
        "V0.7.0",
        "§4.1「Plugin」②：同上",
    ),
    # -- CLI / Worker / 前端（V0.8.0） --------------------------------------
    Rule(
        r"^tests/integration/test_cli\.py$",
        "CLI·init/run/doctor/data/remote/marketplace",
        BUCKET_REDESIGN,
        "@wbtime/cli",
        "V0.8.0",
        "§4.1「CLI」②：Typer → commander；doctor/remote 语义等价是判据",
    ),
    Rule(
        r"^tests/integration/test_doctor_registry_wiring\.py$",
        "CLI·doctor 注册表装配",
        BUCKET_REDESIGN,
        "@wbtime/cli",
        "V0.8.0",
        "§4.1「CLI」②：装配可达性判据继承",
    ),
    Rule(
        r"^tests/unit/test_worker_runtime\.py$",
        "Worker·队列消费 + 恢复",
        BUCKET_REDESIGN,
        "@wbtime/worker",
        "V0.8.0",
        "§4.1「Worker（队列消费 + 恢复）」②：Arq → BullMQ",
    ),
    Rule(
        r"^tests/integration/test_(api_web_static|api_web_static_qa_verify|web_static_sse_redoc)",
        "前端·静态资源托管 / docs 面",
        BUCKET_PLAIN_PORT,
        "@wbtime/web",
        "V0.8.0",
        "§4.1「Agent Studio 15 面板 / 19 渲染页」①（前端业务代码 0 改动）+ "
        "「CLI/Worker/前端」落 V0.8.0；本轮测的是托管判据，逐字继承",
    ),
    # -- e2e 流（按阶段） ---------------------------------------------------
    Rule(
        r"^tests/e2e/test_phase0_flow\.py$",
        "e2e·基座流（health / 登录壳）",
        BUCKET_REDESIGN,
        "@wbtime/api",
        "V0.1.0",
        "phase0 覆盖基座：编排重写，断言语义继承",
    ),
    Rule(
        r"^tests/e2e/test_phase1_flow\.py$",
        "e2e·对话流（Chat SSE）",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "phase1 覆盖对话主链：19 帧判据 + Last-Event-ID 续传；"
        "前端 baseline runner 的 4/4 口径见路线图 §3.2",
    ),
    Rule(
        r"^tests/e2e/test_phase2[abc]?_flow\.py$",
        "e2e·阶段 2 流（工具 / 知识 / 记忆）",
        BUCKET_REDESIGN,
        "@wbtime/runtime",
        "V0.3.0",
        "phase2/2a/2b/2c 覆盖 Agent 运行时扩展：编排重写，断言语义继承",
    ),
)


# ---------------------------------------------------------------------------
# Per-case overrides — applied *after* the file rule (D-2)
# ---------------------------------------------------------------------------
#
# Why these exist: a file-level rule cannot express "3 cases here are a legacy
# shim (droppable) but 1 case is an API-level fail-closed security assertion
# (must be rebuilt)".  Before this table all four carried one copy-pasted note,
# which made the dispositions unauditable -- and hid the single most expensive
# mistake in the whole map (dropping the only fail-closed gate).
#
# Every entry must exist in the collection ledger; ``migration.build`` fails the
# export otherwise (a stale override is a lie about a test that no longer runs).

#: Cases whose disposition differs from their file's rule.  Keyed by node id.
CASE_OVERRIDES: tuple[CaseOverride, ...] = (
    CaseOverride(
        test_id=(
            "tests/integration/permission/test_mcp_permissions_redirect.py"
            "::test_grant_redirects_write_to_resource_permission"
        ),
        capability="权限·旧路径 redirect shim（MCP 专属入口）",
        bucket=BUCKET_DROP,
        target_module="@wbtime/permission",
        target_version="V0.2.0",
        note=(
            "**它断的是什么**：经 legacy `POST /mcp/permissions`（请求体 `mcp_tool_id`）授予 ALLOW 后——"
            "①落实例级 `resource_permission` 行（subject=agent / resource_type=TOOL / resource_id=tool 行 id）、"
            "②deprecated `mcp_permission` 模板无新增、③运行期 `ResourcePermissionChecker` 命中该行（revoke 后回 DENY）、"
            "④`mcp_tool.id ↔ tool.tool_ref[\"id\"] ↔ MCPToolAdapter.tool_id` 映射链一致。"
            "**为什么放弃**：断言对象是「旧 MCP 专属权限入口 redirect 到单一链」，TS 线只有单一链、"
            "**不存在 `/mcp/permissions` 端点**，redirect 前提连同断言一起消失（非能力缺失）；"
            "「判定链命中 / 撤销后失效」的语义由 `tests/integration/permission/test_single_chain.py` 单元级 checker 覆盖。"
            "**残余风险（明示，勿当已覆盖）**：授予→落库→判定→撤销的**写路径 HTTP 端到端**自证，"
            "须随 `@wbtime/permission` 的工具权限 API（V0.2.0）重建——本行不构成该门禁"
        ),
    ),
    CaseOverride(
        test_id=(
            "tests/integration/permission/test_tools_permissions_redirect.py"
            "::test_grant_redirects_write_to_resource_permission"
        ),
        capability="权限·旧路径 redirect shim（tools 专属入口）",
        bucket=BUCKET_DROP,
        target_module="@wbtime/permission",
        target_version="V0.2.0",
        note=(
            "**它断的是什么**：经 legacy `POST /tools/permissions`（请求体 `tool_id`）授予 ALLOW 后——"
            "落实例级 `resource_permission` 行（resource_id = tool_id）、deprecated `tool_permission` 无新增、"
            "运行期 `ResourcePermissionChecker` 命中（非默认拒绝）。"
            "**为什么放弃**：与 MCP 那条同因——断言的是「旧 tools 专属写入口 redirect 到单一 `resource_permission` 链」，"
            "TS 线无 `/tools/permissions` 端点，redirect 前提不存在；判定链语义由 `test_single_chain` 覆盖。"
            "**残余风险（明示）**：工具权限的 HTTP 写路径端到端自证同样须在 V0.2.0 随新 API 重建，本行不算已覆盖"
        ),
    ),
    CaseOverride(
        test_id=(
            "tests/integration/permission/test_tools_permissions_redirect.py"
            "::test_grant_response_contract_unchanged"
        ),
        capability="权限·旧路径响应壳快照",
        bucket=BUCKET_DROP,
        target_module="@wbtime/permission",
        target_version="V0.2.0",
        note=(
            "**它断的是什么**：`POST /tools/permissions` 的**响应字段列表**逐字段不变——"
            "`id` / `tenant_id` / `agent_id` / `tool_id` / `action` / `effect` / `scope`（原样回填），"
            "且 `agent_version_id` 因无对应列恒为 `null`（与迁移 0010 回填口径一致）。"
            "**为什么放弃**：这是**兼容期端点的壳快照**，绑定的正是即将下线的 legacy `/tools/permissions` 与其"
            "「授权记录」返回形状；TS 线该端点不存在，壳字段由新的资源权限 API 决定，逐字段快照**无对象可对**。"
            "**未放弃的部分**：通用四键错误壳（`{code,message,data,request_id}`）由 `contracts/envelope.schema.json` "
            "冻结（DoD#6），与具体端点无关；本行只承载旧端点专属字段列表。V0.2.0 若重建同名端点，"
            "须按新端点**重新生成**壳快照，不得引用本行"
        ),
    ),
    CaseOverride(
        test_id=(
            "tests/integration/permission/test_mcp_permissions_redirect.py"
            "::test_unmapped_mcp_tool_is_fail_closed_and_roundtrips"
        ),
        capability="权限·MCP tool 未同步 fail-closed",
        bucket=BUCKET_REDESIGN,
        target_module="@wbtime/mcp",
        target_version="V0.2.0",
        note=(
            "**不是 redirect shim，是 API 级 fail-closed 安全断言**：`mcp_tool_id` 未同步进 `tool` 表时——"
            "①**拒绝写运行期唯一判定源** `resource_permission`（fail-closed：授了权也不生效，绝不放行）、"
            "②落 deprecated 模板以保留 `/mcp/*` 往返契约、③发结构化告警 `mcp.permission.unmapped_tool`（不静默吞没）、"
            "④list 接口仍能读回该记录（契约往返）。"
            "**为什么必须重设计而非放弃**：QA 全仓检索确认这是**唯一**一处「未同步 → fail-closed + 告警 + 往返」"
            "语义断言；`test_single_chain` 的 5 条（default_deny / type_level_allow / deny_priority_over_allow / "
            "type_level_upsert_dedupes / escalation_denied_and_audited）**均为单元级 checker 断言，不覆盖该语义**"
            "（它们是「已同步资源的判定」，本条是「映射缺失时的写入侧拒绝」）。"
            "**TS 线必须重建此门禁**：端点归属 `@wbtime/mcp`，但断言同时钉住 `@wbtime/permission` 的 "
            "`resource_permission` 表「不得被写入」——重建时两包需同时满足。V0.0.2 判据「桶③ 100% 有替代门禁」"
            "改判后不再依赖本条被放弃"
        ),
    ),
)


def classify(relative_path: str, test_id: str | None = None) -> Disposition:
    """Classify one test file (or one test case, when ``test_id`` is given).

    Args:
        relative_path: POSIX relative path, e.g. ``tests/unit/test_core_id.py``.
        test_id: Optional full pytest node id (``<path>::<test name>``).  When it
            matches an entry of :data:`CASE_OVERRIDES`, that entry wins over the
            file-level rule -- a file may legitimately hold cases with different
            dispositions.

    Returns:
        The first matching :class:`Disposition`, or a ``TBD`` disposition with
        an explicit "no rule matched" note when nothing matches.
    """
    override = case_override(test_id) if test_id else None
    base = _classify_path(relative_path)
    if override is None:
        return base
    return Disposition(
        capability=override.capability,
        bucket=override.bucket,
        target_module=override.target_module,
        target_version=override.target_version,
        note=override.note,
        rule_pattern=base.rule_pattern,
    )


def _classify_path(relative_path: str) -> Disposition:
    """Classify one test file using the ordered rule table only.

    Args:
        relative_path: POSIX relative path.

    Returns:
        The first matching :class:`Disposition`, or the ``TBD`` fallback.
    """
    for rule in RULES:
        if rule.matches(relative_path):
            return Disposition(
                capability=rule.capability,
                bucket=rule.bucket,
                target_module=rule.target_module,
                target_version=rule.target_version,
                note=rule.note,
                rule_pattern=rule.pattern,
            )
    return Disposition(
        capability="未归类",
        bucket=BUCKET_REDESIGN,
        target_module="TBD",
        target_version=TARGET_VERSION_UNKNOWN,
        note="无匹配规则：路径未落入 §4.1 任一能力簇，需人工判定（禁止猜测版本号）",
        rule_pattern="",
    )


def case_override(test_id: str) -> CaseOverride | None:
    """Return the :class:`CaseOverride` for ``test_id``, when one exists.

    Args:
        test_id: Full pytest node id.

    Returns:
        The matching override, or ``None``.
    """
    for override in CASE_OVERRIDES:
        if override.test_id == test_id:
            return override
    return None


def known_override_ids() -> tuple[str, ...]:
    """Return every overridden node id (used by the builder's existence gate)."""
    return tuple(override.test_id for override in CASE_OVERRIDES)
