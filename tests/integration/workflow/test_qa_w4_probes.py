"""QA 独立负向 / 边界探针（W4 · T2-20 ~ T2-26 波次级独立验证；**非**重复工程师自测）。

本文件由 QA 工程师**独立编写**（纪律：**不改源码**），对 W4 关键不变式做**负向**与
**边界**复现，作为工程师自测的**交叉验证**。立场＝「证明代码真的按预期工作」，故：

- 主动构造 **DENY / 无 ALLOW / 未放行 endpoint** 等**拒绝路径**，断言**不执行**；
- 静态扫描 **`astra_workflow` 是否自建判定源**（唯一判定链零放宽）；
- 断言 **`runtime` 抽象包耦合面**（仅 `engine/runtime_bridge.py`）；
- 边界：引擎按 `workflow_edge` 驱动 + `node_key` 命名空间；并发**无超卖**；
- **默认不自动生成审批**（engine 级 spy，证明无 `HUMAN_APPROVAL` 时网关零调用）。

🔴 本文件如实地**不作为**源码缺陷判定依据——若断言失败，按 §智能路由判定（本仓自检）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import ConcurrencyConfig
from astra_runtime import RuntimePermissionChecker, ToolCallRequest, ToolExecutor
from astra_security.egress import EGRESS_WIRING_POINTS, SecurityEgressPolicy
from astra_tool import (
    PermissionChecker,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from astra_workflow import (
    NODE_TYPE_AGENT,
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    NODE_TYPE_TOOL,
    WORKFLOW_RUN_STATUS_FAILED,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.engine import VariableContext, WorkflowEngine
from astra_workflow.engine.concurrency import ActiveRunGuard, ConcurrencyGuardImpl
from astra_workflow.engine.runtime_bridge import RuntimeBridgeImpl
from astra_workflow.nodes import NodeContext, NodeResult, ToolNode

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_SRC = REPO_ROOT / "packages" / "workflow" / "src" / "astra_workflow"


# -- fakes -------------------------------------------------------------------


class _SpyTool:
    """记录是否被执行的工具（用**真实** ``ToolSpec`` / ``ToolResult``，避免桩件漂移）。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []
        self.tool_id: str | None = None
        self.version: str | None = None
        self.spec = ToolSpec(
            metadata=ToolMetadata(name=name, display_name=name),
            input_schema={},
            permission=ToolPermissionRequirement(action="EXECUTE"),
            requires_sandbox=False,
        )

    def execute(self, arguments: dict[str, Any], ctx: Any) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult.success({"echoed": True})


class _MemoryRecorder:
    """内存版 ``NodeRunRecorder``。"""

    def __init__(self) -> None:
        self.rows: list[WorkflowNodeRun] = []

    def add(self, node_run: WorkflowNodeRun) -> WorkflowNodeRun:
        self.rows.append(node_run)
        return node_run

    def update(self, node_run: WorkflowNodeRun) -> WorkflowNodeRun:
        return node_run

    def list_by_run(self, workflow_run_id: str) -> list[WorkflowNodeRun]:
        return [row for row in self.rows if row.workflow_run_id == workflow_run_id]


class _EchoExecutor:
    """回显 ``node_key`` 的 fake 执行器。"""

    def __init__(self, node_type: str) -> None:
        self.type = node_type
        self.calls: list[str] = []

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        self.calls.append(node.node_key)
        return NodeResult.success({node.node_key: "ok"})


class _SpyGateway:
    """记录 ``request`` 调用的 fake 审批网关（默认不自动生成审批的判据）。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        raise AssertionError("无 HUMAN_APPROVAL 时不应发起审批")

    def find_by_subject_ref(self, **kwargs: Any) -> Any:
        return None


def _node(key: str, node_type: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(
        workflow_version_id="wv-1", node_key=key, type=node_type, config=dict(config)
    )


def _edge(from_key: str, to_key: str, condition: str | None = None) -> WorkflowEdge:
    return WorkflowEdge(
        workflow_version_id="wv-1", from_node_key=from_key, to_node_key=to_key, condition=condition
    )


def _published_version(
    nodes: list[WorkflowNode], edges: list[WorkflowEdge], *, entry: str | None = None
) -> WorkflowVersion:
    return WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry=entry),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )


def _node_ctx() -> NodeContext:
    return NodeContext(run_id="run-1", tenant_id="tenant-1", requested_by="u-1")


def _deny_all() -> RuntimePermissionChecker:
    """无规则校验器（deny-by-default）。"""
    return RuntimePermissionChecker(PermissionChecker())


def _allow(name: str) -> RuntimePermissionChecker:
    """显式 ALLOW 指定工具（复用既有 ``allow_tool`` 工厂，避免桩件漂移）。"""
    from tests.unit.runtime_stubs import allow_tool

    return RuntimePermissionChecker(allow_tool(name))


# -- §1 Egress 唯一出网入口（负向：默认拒绝 / 逐跳 / deny 不可被 allow 覆盖） ------


def test_egress_default_denies_unallowlisted_endpoint() -> None:
    """未放行 endpoint（空 allow）→ **默认拒绝**（``PERMISSION_DENIED``，不触网）。"""
    policy = SecurityEgressPolicy()  # 空 allow ⇒ 默认拒绝全部（F/T2-03 口径）
    with pytest.raises(DomainError) as excinfo:
        policy.enforce("http://evil.example.com/steal")
    assert excinfo.value.code == ErrorCode.PERMISSION_DENIED
    assert "默认拒绝" in str(excinfo.value.message)


def test_egress_deny_private_not_overridable_by_allow() -> None:
    """``deny_private`` 拒段**不可被 allow 覆盖**（元数据 IP 被拒）。"""
    policy = SecurityEgressPolicy(allow=["169.254.169.254"], deny_private=True)
    decision = policy.authorize("http://169.254.169.254/latest/meta-data/")
    assert decision.allowed is False
    assert decision.code == ErrorCode.PERMISSION_DENIED


def test_egress_redirect_is_checked_hop_by_hop() -> None:
    """重定向**逐跳**重检（未放行的跳 → 拒）。"""
    policy = SecurityEgressPolicy(allow=["allowed.example.com"])
    decision = policy.authorize_redirect(
        from_url="http://allowed.example.com/a",
        location="http://evil.example.com/b",
    )
    assert decision.allowed is False
    assert decision.code == ErrorCode.PERMISSION_DENIED


def test_egress_wiring_points_include_workflow_relevant_faces() -> None:
    """四出网面接线点存在（``I-P2-32`` / DoD ``D14``）。"""
    assert len(EGRESS_WIRING_POINTS) >= 4


def test_http_tool_with_deny_all_egress_never_reaches_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 唯一出网入口：deny-all egress 下 ``http`` 工具**不触网**（无旁路出网）。

    以 monkeypatch 把 ``urllib.request.urlopen`` 换成「一旦被调用即失败」的哨兵，
    证明拒绝发生在**建连之前**。
    """
    import urllib.request

    from astra_tool.tools.http import HttpTool

    def _boom(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - 不应被调用
        raise AssertionError("出网被拒后仍尝试建连——存在旁路出网！")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    registry = ToolRegistry()
    registry.register("http", HttpTool())
    executor = ToolExecutor(tool_registry=registry, permission_checker=_allow("http"))
    bridge = RuntimeBridgeImpl(
        tool_executor=executor,
        checker_resolver=lambda agent_id: _allow("http"),
        egress_policy=SecurityEgressPolicy(),  # 空 allow ⇒ 默认拒绝
    )
    node = _node("n1", NODE_TYPE_TOOL, tool="http", arguments={"url": "http://evil.example.com/x"})
    # 无论表层错误码如何收敛，**绝不能触网**（哨兵未被调用即证明无旁路）。
    with pytest.raises(DomainError):
        ToolNode(bridge).execute(node, VariableContext(), _node_ctx())


# -- §2 权限单一判定链零放宽（负向：DENY / 无 ALLOW → 不执行 + run FAILED） --------


def test_tool_node_deny_does_not_execute_and_run_fails() -> None:
    """``DENY`` → 工具**不执行**，且引擎把 run 收敛为 ``FAILED``（判定链零放宽）。"""
    spy = _SpyTool("fs.read")
    registry = ToolRegistry()
    registry.register("fs.read", spy)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_deny_all())
    bridge = RuntimeBridgeImpl(tool_executor=executor, checker_resolver=lambda a: _deny_all())

    nodes = [_node("n1", NODE_TYPE_TOOL, tool="fs.read", arguments={"path": "/x"})]
    version = _published_version(nodes, [], entry="n1")
    engine = WorkflowEngine({NODE_TYPE_TOOL: ToolNode(bridge)}, recorder=_MemoryRecorder())

    run = engine.run(version, {})
    assert spy.calls == [], "权限拒绝时工具**不得**被执行"
    assert run.status == WORKFLOW_RUN_STATUS_FAILED
    assert run.error == str(ErrorCode.PERMISSION_DENIED)


def test_no_allow_means_default_deny() -> None:
    """无任何 ALLOW 规则 ⇒ **默认拒绝**（不因缺规则而放行）。"""
    spy = _SpyTool("fs.read")
    registry = ToolRegistry()
    registry.register("fs.read", spy)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_deny_all())
    bridge = RuntimeBridgeImpl(tool_executor=executor, checker_resolver=lambda a: _deny_all())
    node = _node("n1", NODE_TYPE_TOOL, tool="fs.read", arguments={})
    with pytest.raises(DomainError) as excinfo:
        ToolNode(bridge).execute(node, VariableContext(), _node_ctx())
    assert excinfo.value.code == ErrorCode.PERMISSION_DENIED
    assert spy.calls == []


def test_workflow_package_does_not_build_its_own_decision_source() -> None:
    """🔴 AST 扫描：``astra_workflow`` **不 import / 使用**权限 / 出网判定源（唯一判定链）。

    仅扫**真实代码**（AST 导入 / 标识符），**不**误伤文档字符串与注释。
    """
    import ast

    banned_identifiers = {
        "ResourcePermissionChecker",
        "SecurityEgressPolicy",
        "check_egress",
    }
    offenders: list[str] = []
    for path in sorted(WORKFLOW_SRC.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        is_bridge = path.name == "runtime_bridge.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    if module.startswith("astra_security"):
                        offenders.append(f"{rel} -> import {module}")
                    if module.startswith("astra_tool") and not is_bridge:
                        offenders.append(f"{rel} -> import {module}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("astra_security"):
                    offenders.append(f"{rel} -> from {module}")
                if module.startswith("astra_tool") and not is_bridge:
                    offenders.append(f"{rel} -> from {module}")
            elif isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
        hit = identifiers & banned_identifiers
        for token in sorted(hit):
            offenders.append(f"{rel} -> uses {token}")
    assert not offenders, f"astra_workflow 自建/引入判定源：{offenders}"


def test_only_runtime_bridge_couples_runtime_and_tool() -> None:
    """WR-6：``astra_workflow`` 中**仅** ``engine/runtime_bridge.py`` import runtime/tool。"""
    forbidden = {"astra_runtime", "astra_tool"}
    offenders: list[str] = []
    for path in sorted(WORKFLOW_SRC.rglob("*.py")):
        if path.name == "runtime_bridge.py":
            continue
        text = path.read_text(encoding="utf-8")
        for module in forbidden:
            if re.search(rf"^\s*(from|import)\s+{re.escape(module)}\b", text, re.MULTILINE):
                offenders.append(f"{path.relative_to(REPO_ROOT)} -> {module}")
    assert not offenders, f"Runtime/Tool 耦合扩散：{offenders}"


# -- §3 引擎按 workflow_edge 驱动 + node_key 命名空间（I-P2-05 边界） --------------


def test_engine_follows_edges_and_namespaces_outputs() -> None:
    """引擎按 ``workflow_edge`` 驱动；节点 output 以 ``node_key`` 命名空间注入（``I-P2-05``）。"""
    nodes = [
        _node("producer", NODE_TYPE_AGENT),
        _node("consumer", NODE_TYPE_TOOL, input={"seen": "${producer.producer}"}),
        _node("end", NODE_TYPE_END),
    ]
    edges = [_edge("producer", "consumer"), _edge("consumer", "end")]
    version = _published_version(nodes, edges, entry="producer")

    producer = _EchoExecutor(NODE_TYPE_AGENT)
    seen: dict[str, Any] = {}

    class _Consumer:
        type = NODE_TYPE_TOOL

        def execute(
            self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None
        ) -> NodeResult:
            seen.update(dict(var_ctx.resolve_value(node.config.get("input") or {})))
            return NodeResult.success({"done": True})

    engine = WorkflowEngine({NODE_TYPE_AGENT: producer, NODE_TYPE_TOOL: _Consumer()})
    run = engine.run(version, {})
    assert producer.calls == ["producer"]
    assert seen == {"seen": "ok"}  # 命名空间 ${producer.producer}
    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert set(run.output["outputs"]) == {"producer", "consumer"}


# -- §4 并发无超卖（N-P2-02 边界） ---------------------------------------------


def test_parallel_limit_exceeded_is_resource_limit_not_queue() -> None:
    """``PARALLEL`` 超限 → ``RESOURCE_LIMIT_EXCEEDED``（**不静默排队**）且无配额残留。"""
    guard = ConcurrencyGuardImpl(ConcurrencyConfig(max_parallel=3))
    guard.acquire(3)
    with pytest.raises(DomainError) as excinfo:
        guard.acquire(1)
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED
    # 申请 4（> 3）一次性失败 → 未残留部分配额（全有或全无）。
    guard.release(3)
    with pytest.raises(DomainError):
        guard.acquire(4)
    assert guard.available == 3, "部分获取必须回滚（无超卖 / 无泄漏）"


def test_active_run_guard_no_oversell_boundaries() -> None:
    """活跃 Run 上限边界：未达放行、达上限拒、0/负 = 不限。"""
    # 未达上限（2 < 3）→ 放行（不抛）。
    assert ActiveRunGuard(lambda k: 2, max_active=3).check("t") is None
    # 达上限（3 >= 3）→ 拒（无超卖）。
    with pytest.raises(DomainError) as excinfo:
        ActiveRunGuard(lambda k: 3, max_active=3).check("t")
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED
    # 0 上限 = 不限。
    assert ActiveRunGuard(lambda k: 99, max_active=0).check("t") is None


# -- §5 默认不自动生成审批（engine 级 spy） ------------------------------------


def test_no_approval_without_human_node_engine_level() -> None:
    """无 ``HUMAN_APPROVAL`` 节点时，审批网关**零调用**（默认不自动生成审批）。"""
    from astra_workflow.nodes.human_approval import HumanApprovalNode

    spy = _SpyGateway()
    # 网关注入到 HUMAN_APPROVAL 节点，但图中**无**该类型节点 → 不应被调用。
    engine = WorkflowEngine(
        {
            NODE_TYPE_AGENT: _EchoExecutor(NODE_TYPE_AGENT),
            NODE_TYPE_TOOL: _EchoExecutor(NODE_TYPE_TOOL),
            NODE_TYPE_HUMAN_APPROVAL: HumanApprovalNode(spy),  # type: ignore[arg-type]
            NODE_TYPE_END: _EchoExecutor(NODE_TYPE_END),
        }
    )
    nodes = [_node("a", NODE_TYPE_AGENT), _node("end", NODE_TYPE_END)]
    edges = [_edge("a", "end")]
    version = _published_version(nodes, edges, entry="a")
    run = engine.run(version, {})
    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert spy.requests == [], "无 HUMAN_APPROVAL 时不得自动生成审批"


# -- §6 不变量常量对齐（防拼写漂移） -------------------------------------------


def test_tool_execution_result_denied_constant() -> None:
    """拒绝状态常量对齐（判定链产出 ``DENIED`` 字面值稳定）。"""
    from astra_domain import TOOL_CALL_STATUS_DENIED

    assert TOOL_CALL_STATUS_DENIED == "DENIED"
    assert ToolCallRequest(name="x").name == "x"
