"""跨包共享 DTO / 值对象（预留位输入输出类型；W5 / T1-25，总纲 §12.1）。

Phase 2 预留位（RP-01~RP-05）的**输入输出类型**落在 ``astra_domain``（跨包共享），
随其 Protocol 一并冻结；填充实现时**不得改签名**。

🔴 本子包**零框架依赖**（禁 fastapi / starlette / sqlalchemy / alembic / pydantic / sqlmodel），
   受 ``tests/integration/test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖。

- RP-01 ``SkillResolver``：:class:`SkillQuery` / :class:`ResolvedSkill`；
- RP-02 ``KnowledgeRetriever``：:class:`KnowledgeQuery` / :class:`KnowledgeChunk`；
- RP-03 ``MemoryManager``：:class:`MemoryRecord` / :class:`MemoryQuery`；
- RP-04 ``MCPExecutor``：:class:`MCPCallRequest` / :class:`MCPCallResult`；
- RP-05 ``Planner``：:class:`PlanStep` / :class:`Plan`；
- 出网原语（W1 / T2-03）：:class:`EgressPolicy` / :class:`EgressDecision` / ``DENY_RANGES`` /
  ``is_blocked_ip`` / ``host_matches`` / ``resolve_all``（``astra_tool`` 与
  ``astra_security.egress`` 共享的**唯一原语来源**）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .credential_decoder import CredentialDecoder
from .egress import (
    ALLOWED_SCHEMES,
    DENY_RANGES,
    METADATA_IPS,
    EgressDecision,
    EgressPolicy,
    host_matches,
    is_blocked_ip,
    is_metadata_ip,
    resolve_all,
)

__all__ = [
    # RP-01
    "SkillQuery",
    "ResolvedSkill",
    # RP-02
    "KnowledgeQuery",
    "KnowledgeChunk",
    # RP-03
    "MemoryRecord",
    "MemoryQuery",
    # RP-04
    "MCPCallRequest",
    "MCPCallResult",
    # RP-05
    "PlanStep",
    "Plan",
    # 审批网关（W4 / T2-22；机制归 T2-26，表随 0010）
    "ApprovalGateway",
    # 凭证解码（W6 / T1-30）
    "CredentialDecoder",
    # 出网原语（W1 / T2-03）
    "METADATA_IPS",
    "DENY_RANGES",
    "ALLOWED_SCHEMES",
    "is_metadata_ip",
    "is_blocked_ip",
    "host_matches",
    "resolve_all",
    "EgressDecision",
    "EgressPolicy",
]


# -- RP-01 · SkillResolver ---------------------------------------------------


@dataclass(frozen=True)
class SkillQuery:
    """技能解析请求（RP-01 输入）。

    W3 裁定 §19.2.1（T2-09.1）**加性**扩展：``agent_version_id`` 可选、默认 ``None``——
    按 ``agent_skill`` 绑定解析（设计 §2.3）；缺省时回落注册表全量（向后兼容）。
    """

    text: str = ""
    workspace_id: str | None = None
    limit: int = 5
    agent_version_id: str | None = None


@dataclass(frozen=True)
class ResolvedSkill:
    """已解析的技能（RP-01 输出）。"""

    name: str
    description: str = ""
    content: str = ""
    version: str | None = None


# -- RP-02 · KnowledgeRetriever ---------------------------------------------


@dataclass(frozen=True)
class KnowledgeQuery:
    """知识检索请求（RP-02 输入）。

    W5 裁定 B7（T2-30）**加性**扩展：``agent_version_id`` 可选、默认 ``None``——
    非空时按 ``agent_knowledge`` 绑定解析 KB；缺省时**回落该 ``workspace_id`` 的全部启用 KB**
    （与 ``SkillQuery`` 一致，F22）。填充实现时**签名不变、仅新增可选字段**。
    """

    text: str = ""
    workspace_id: str | None = None
    top_k: int = 5
    agent_version_id: str | None = None


@dataclass(frozen=True)
class KnowledgeChunk:
    """召回的知片段（RP-02 输出）。"""

    content: str
    source: str = ""
    score: float = 0.0


# -- RP-03 · MemoryManager ---------------------------------------------------


@dataclass(frozen=True)
class MemoryRecord:
    """一条记忆记录（RP-03 输入 / 输出）。

    W6 裁定 B4（T2-32 开工前冻）**加性**扩展：新增可选字段（``kind`` / 作用域 /
    可见性 / 权重 / 隔离维度 / TTL）——**签名不变、仅新增**；缺省值保持 Phase 1 语义。
    """

    key: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # -- W6 / B4 加性可选字段（隔离 / 作用域 / 权重） ------------------------
    kind: str = ""
    scope_type: str = ""
    scope_id: str = ""
    visibility: str = ""
    importance: float = 0.0
    tenant_id: str = ""
    workspace_id: str | None = None
    source_run_id: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class MemoryQuery:
    """记忆检索请求（RP-03 输入）。

    W6 裁定 B4（T2-32 开工前冻）**加性**扩展：新增可选隔离维度字段（``tenant_id`` /
    ``workspace_id`` / ``agent_id`` / ``user_id`` / ``trigger`` / ``kinds``）——召回据此
    在能力包内**强制 ``tenant_id`` 过滤**并按作用域 / 可见性收窄（R-19 / I-2 / I-3）。
    """

    text: str = ""
    limit: int = 10
    # -- W6 / B4 加性可选字段（隔离维度 / 类别过滤） ------------------------
    tenant_id: str = ""
    workspace_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    trigger: str = ""
    kinds: list[str] = field(default_factory=list)


# -- RP-04 · MCPExecutor -----------------------------------------------------


@dataclass(frozen=True)
class MCPCallRequest:
    """MCP 调用请求（RP-04 输入；Phase 2 才产出）。"""

    server: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPCallResult:
    """MCP 调用结果（RP-04 输出）。"""

    ok: bool = True
    output: Any = None
    error: str | None = None


# -- RP-05 · Planner ---------------------------------------------------------


@dataclass(frozen=True)
class PlanStep:
    """计划步骤（RP-05 输入 / 输出）。"""

    description: str
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    """执行计划（RP-05 输出）。"""

    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)


# -- 审批网关（W4 / T2-22，机制归 T2-26；表随 0010 建于 2a） -------------------


@runtime_checkable
class ApprovalGateway(Protocol):
    """审批网关（跨包契约；W4 裁定 §3.4 / §3.5）。

    ``HUMAN_APPROVAL`` 节点依赖**本 Protocol**，**不 import ``astra_security``**——
    真实实现（``ApprovalService``）由**组合根**注入。

    🔴 ``approval`` 表随迁移 ``0010``（2a）建立，本契约**零迁移**。
    """

    def request(
        self,
        *,
        subject_type: str,
        subject_ref: str,
        payload: dict[str, Any] | None = None,
        requested_by: str | None = None,
        expires_at: Any | None = None,
        tenant_id: str | None = None,
    ) -> Any:
        """发起一条审批请求并挂起（返回审批记录，其 ``id`` 挂到 ``workflow_node_run``）。

        Args:
            subject_type: 主体类型（``tool`` / ``mcp`` / ``workflow_node``）。
            subject_ref: 主体引用（``workflow_node`` 时为 ``workflow_run_id:node_key``）。
            payload: 审批载荷。
            requested_by: 发起人用户标识。
            expires_at: 到期时间（``None`` = 不过期）。
            tenant_id: 所属租户标识（``approval.tenant_id`` 非空；T2-26 **加性可选形参**）。

        Returns:
            审批记录（``astra_domain.approval.Approval``；T2-26 起具名）。
        """
        ...

    def find_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Any | None:
        """按 ``(subject_type, subject_ref)`` 取**最近一条**审批记录（T2-26 **加性**）。

        ``HUMAN_APPROVAL`` 节点的重入（``WorkflowEngine.resume`` 以 ``attempt + 1`` 重跑挂起的
        节点）据此**幂等收敛**：既有 ``APPROVED`` → 直接放行；``PENDING`` → 继续挂起；
        ``REJECTED`` / ``EXPIRED`` → 报错。**不再重复发起**第二条审批。

        Args:
            subject_type: 主体类型（``tool`` / ``mcp`` / ``workflow_node``）。
            subject_ref: 主体引用（``workflow_node`` 时为 ``workflow_run_id:node_key``）。

        Returns:
            最近一条审批记录（``astra_domain.approval.Approval``）；无则 ``None``。
        """
        ...
