"""``astra_workflow`` 执行引擎单元测试（W4 / T2-21）。

以 **fake ``RuntimeBridge`` / fake 节点执行器** 驱动，**零 Runtime / 零 ORM / 零事件总线**
（验证引擎可在最小依赖下运行，``WR-6``）。

覆盖：

- 引擎按 ``workflow_edge`` 驱动节点（``I-P2-05``）；
- 节点 ``output`` 以 ``node_key`` 命名空间注入变量上下文（``${n1.text}``）；
- ``CONDITION`` 分支选取；``END`` 汇聚终态；
- 图有环 → ``DomainError(VALIDATION_ERROR)``；未发布版本 → ``VALIDATION_ERROR``；
- 超时预算 / 重试退避路径；``max_steps`` 有界；
- ``HUMAN_APPROVAL`` 挂起 → ``WAITING_APPROVAL`` → ``resume`` 续跑；
- 起步 ``Planner``（``astra_agent.planning``）结构化兼容 RP-05 Protocol。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_agent import SimplePlanner, build_simple_planner
from astra_core import DomainError, ErrorCode
from astra_domain import Plan
from astra_workflow import (
    DEFAULT_ATTEMPT,
    NODE_TYPE_AGENT,
    NODE_TYPE_CONDITION,
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    NODE_TYPE_MCP,
    NODE_TYPE_TOOL,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_FAILED,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.engine import (
    NodeScheduler,
    RuntimeBridge,
    TimeoutBudget,
    VariableContext,
    WorkflowEngine,
    WorkflowGraph,
    build_graph,
)
from astra_workflow.engine.timeout import RetryPolicy, run_with_retry
from astra_workflow.nodes import NodeRegistry, NodeResult

# -- fakes -------------------------------------------------------------------


class _RecordingSink:
    """记录事件回调的 fake sink。"""

    def __init__(self) -> None:
        self.events: list[str] = []

    def run_started(self, run: WorkflowRun) -> None:
        self.events.append("run_started")

    def node_started(self, run: WorkflowRun, node_run: Any) -> None:
        self.events.append(f"node_started:{node_run.node_key}")

    def node_completed(self, run: WorkflowRun, node_run: Any) -> None:
        self.events.append(f"node_completed:{node_run.node_key}:{node_run.status}")

    def run_completed(self, run: WorkflowRun) -> None:
        self.events.append("run_completed")

    def run_failed(self, run: WorkflowRun) -> None:
        self.events.append("run_failed")


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
    """把 ``config`` 原样回显为 output 的 fake 执行器。"""

    def __init__(self, node_type: str, outputs: dict[str, dict[str, Any]] | None = None) -> None:
        self.type = node_type
        self._outputs = outputs or {}
        self.calls: list[str] = []

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        self.calls.append(node.node_key)
        payload = self._outputs.get(node.node_key, {"echo": node.node_key})
        return NodeResult.success(payload)


class _FailingExecutor:
    """恒失败的执行器。"""

    def __init__(self, node_type: str, error: str = "boom") -> None:
        self.type = node_type
        self._error = error

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        raise DomainError(self._error, code=ErrorCode.INTERNAL_ERROR)


class _ApprovalExecutor:
    """首次挂起、二次放行的 fake 审批节点执行器。"""

    def __init__(self) -> None:
        self.type = NODE_TYPE_HUMAN_APPROVAL
        self.calls: list[str] = []

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        self.calls.append(node.node_key)
        if len(self.calls) == 1:
            return NodeResult.suspended_for_approval("approval-1")
        return NodeResult.success({"approved": True})


class _ConditionExecutor:
    """按 ``config.branch`` 选分支的 fake 条件节点。"""

    def __init__(self) -> None:
        self.type = NODE_TYPE_CONDITION

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        branch = str(node.config.get("branch") or "true")
        return NodeResult.success({"branch": branch}, next_branch=branch)


class _FakeVersionRepo:
    """内存版版本仓储（``resume`` 回读用）。"""

    def __init__(self, versions: dict[str, WorkflowVersion]) -> None:
        self._versions = versions

    def get(self, entity_id: str) -> WorkflowVersion | None:
        return self._versions.get(entity_id)

    def add(self, entity: WorkflowVersion) -> WorkflowVersion:
        self._versions[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[WorkflowVersion]:
        return list(self._versions.values())

    def update(self, entity: WorkflowVersion) -> WorkflowVersion:
        self._versions[entity.id] = entity
        return entity

    def delete(self, entity: WorkflowVersion) -> None:
        self._versions.pop(entity.id, None)

    def list_by_workflow(self, workflow_id: str) -> list[WorkflowVersion]:
        return [v for v in self._versions.values() if v.workflow_id == workflow_id]

    def get_by_version(self, workflow_id: str, version: str) -> WorkflowVersion | None:
        for item in self._versions.values():
            if item.workflow_id == workflow_id and item.version == version:
                return item
        return None


def _version(
    nodes: list[WorkflowNode], edges: list[WorkflowEdge], *, entry: str | None = None
) -> WorkflowVersion:
    """构造已发布版本（``definition`` 为完整图快照）。"""
    return WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry=entry),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )


def _node(key: str, node_type: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(
        workflow_version_id="wv-1", node_key=key, type=node_type, config=dict(config)
    )


def _edge(from_key: str, to_key: str, condition: str | None = None) -> WorkflowEdge:
    return WorkflowEdge(
        workflow_version_id="wv-1", from_node_key=from_key, to_node_key=to_key, condition=condition
    )


# -- 用例 -------------------------------------------------------------------


def test_engine_drives_nodes_by_edges() -> None:
    """引擎按 ``workflow_edge`` 顺序驱动节点（``I-P2-05``）。"""
    nodes = [_node("n1", NODE_TYPE_AGENT), _node("n2", NODE_TYPE_TOOL), _node("end", NODE_TYPE_END)]
    edges = [_edge("n1", "n2"), _edge("n2", "end")]
    version = _version(nodes, edges, entry="n1")

    first = _EchoExecutor(NODE_TYPE_AGENT)
    second = _EchoExecutor(NODE_TYPE_TOOL)
    sink = _RecordingSink()
    recorder = _MemoryRecorder()
    engine = WorkflowEngine({"AGENT": first, "TOOL": second}, recorder=recorder, sink=sink)

    run = engine.run(version, {"topic": "astra"})

    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert first.calls == ["n1"]
    assert second.calls == ["n2"]
    assert recorder.rows[0].node_key == "n1"
    assert recorder.rows[0].status == WORKFLOW_NODE_RUN_STATUS_SUCCEEDED
    assert sink.events[0] == "run_started"
    assert "run_completed" in sink.events
    assert run.workflow_version_id == "wv-1"


def test_engine_injects_output_by_node_key_namespace() -> None:
    """节点 ``output`` 以 ``node_key`` 命名空间注入（``${n1.text}``）。"""
    nodes = [
        _node("n1", NODE_TYPE_AGENT),
        _node("n2", NODE_TYPE_TOOL, input={"text": "${n1.text}"}),
    ]
    edges = [_edge("n1", "n2")]
    version = _version(nodes, edges, entry="n1")

    producer = _EchoExecutor(NODE_TYPE_AGENT, {"n1": {"text": "hello"}})

    class _Consumer:
        type = NODE_TYPE_TOOL

        def __init__(self) -> None:
            self.seen: dict[str, Any] = {}

        def execute(self, node, var_ctx, ctx=None) -> NodeResult:
            self.seen = dict(var_ctx.resolve_value(node.config.get("input") or {}))
            return NodeResult.success({"seen": self.seen})

    consumer = _Consumer()
    engine = WorkflowEngine({"AGENT": producer, "TOOL": consumer})
    run = engine.run(version, {"topic": "astra"})

    assert consumer.seen == {"text": "hello"}
    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED


def test_engine_resolves_input_namespace() -> None:
    """``${input.xxx}`` 引用运行入参。"""
    nodes = [_node("n1", NODE_TYPE_TOOL, input={"topic": "${input.topic}"})]
    version = _version(nodes, [], entry="n1")

    class _Consumer:
        type = NODE_TYPE_TOOL

        def __init__(self) -> None:
            self.seen: dict[str, Any] = {}

        def execute(self, node, var_ctx, ctx=None) -> NodeResult:
            self.seen = dict(var_ctx.resolve_value(node.config.get("input") or {}))
            return NodeResult.success()

    consumer = _Consumer()
    engine = WorkflowEngine({"TOOL": consumer})
    engine.run(version, {"topic": "astra"})
    assert consumer.seen == {"topic": "astra"}


def test_engine_condition_branch_selection() -> None:
    """``CONDITION`` 按 ``next_branch`` 选分支（非选中分支不执行）。"""
    nodes = [
        _node("c", NODE_TYPE_CONDITION, branch="false"),
        _node("yes", NODE_TYPE_TOOL),
        _node("no", NODE_TYPE_TOOL),
    ]
    edges = [_edge("c", "yes", condition="true"), _edge("c", "no", condition="false")]
    version = _version(nodes, edges, entry="c")

    tool = _EchoExecutor(NODE_TYPE_TOOL)
    engine = WorkflowEngine({"CONDITION": _ConditionExecutor(), "TOOL": tool})
    run = engine.run(version, {})

    assert tool.calls == ["no"]
    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED


def test_engine_rejects_cycle() -> None:
    """图有环 → ``DomainError(VALIDATION_ERROR)``。"""
    nodes = [_node("a", NODE_TYPE_TOOL), _node("b", NODE_TYPE_TOOL)]
    edges = [_edge("a", "b"), _edge("b", "a")]
    version = _version(nodes, edges, entry="a")

    engine = WorkflowEngine({"TOOL": _EchoExecutor(NODE_TYPE_TOOL)})
    with pytest.raises(DomainError) as excinfo:
        engine.run(version, {})
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert excinfo.value.data is not None
    assert excinfo.value.data["reason"] == "cycle"


def test_engine_rejects_unpublished_version() -> None:
    """未发布版本不可运行（``VALIDATION_ERROR``）。"""
    draft = WorkflowVersion(id="wv-d", workflow_id="wf-1", version="v1", status="DRAFT")
    engine = WorkflowEngine({"TOOL": _EchoExecutor(NODE_TYPE_TOOL)})
    with pytest.raises(DomainError) as excinfo:
        engine.run(draft, {})
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert excinfo.value.data is not None
    assert excinfo.value.data["reason"] == "version_not_published"


def test_engine_missing_executor_is_error() -> None:
    """节点类型无执行器 → 运行收敛为 ``FAILED``（不静默跳过）。"""
    nodes = [_node("n1", NODE_TYPE_MCP)]
    version = _version(nodes, [], entry="n1")
    engine = WorkflowEngine({})
    run = engine.run(version, {})
    assert run.status == WORKFLOW_RUN_STATUS_FAILED
    assert run.error == str(ErrorCode.NOT_IMPLEMENTED)


def test_engine_suspends_on_human_approval_and_resumes() -> None:
    """``HUMAN_APPROVAL`` 挂起 → ``WAITING_APPROVAL`` → ``resume`` 续跑至 ``SUCCEEDED``。"""
    nodes = [
        _node("approve", NODE_TYPE_HUMAN_APPROVAL),
        _node("after", NODE_TYPE_TOOL),
    ]
    edges = [_edge("approve", "after")]
    version = _version(nodes, edges, entry="approve")

    approval = _ApprovalExecutor()
    after = _EchoExecutor(NODE_TYPE_TOOL)
    sink = _RecordingSink()
    recorder = _MemoryRecorder()
    versions = _FakeVersionRepo({version.id: version})
    engine = WorkflowEngine(
        {"HUMAN_APPROVAL": approval, "TOOL": after},
        versions=versions,
        recorder=recorder,
        sink=sink,
    )

    run = WorkflowRun(id="run-1", workflow_version_id=version.id, input={})
    run = engine.run(version, {}, run=run)
    assert run.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL
    assert not run.is_terminal
    assert approval.calls == ["approve"]

    resumed = engine.resume(run)
    assert resumed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert after.calls == ["after"]
    assert approval.calls == ["approve", "approve"]  # 自挂起节点重入（attempt + 1）


def test_engine_resume_requires_waiting_approval() -> None:
    """非 ``WAITING_APPROVAL`` 不可续跑（``VALIDATION_ERROR``）。"""
    version = _version([_node("n1", NODE_TYPE_TOOL)], [], entry="n1")
    engine = WorkflowEngine({"TOOL": _EchoExecutor(NODE_TYPE_TOOL)})
    run = engine.run(version, {})
    assert run.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    with pytest.raises(DomainError) as excinfo:
        engine.resume(run)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_engine_max_steps_is_bounded() -> None:
    """``max_steps`` 有界：超限 → ``FAILED``（不无界循环）。"""
    nodes = [_node("n1", NODE_TYPE_TOOL), _node("n2", NODE_TYPE_TOOL)]
    edges = [_edge("n1", "n2")]
    version = _version(nodes, edges, entry="n1")
    engine = WorkflowEngine({"TOOL": _EchoExecutor(NODE_TYPE_TOOL)}, max_steps=1)
    run = engine.run(version, {})
    assert run.status == WORKFLOW_RUN_STATUS_FAILED
    assert run.error == "MAX_STEPS_EXCEEDED"


def test_engine_node_failure_converges_to_failed() -> None:
    """节点抛 ``DomainError`` → 运行 ``FAILED`` 且 ``error`` 记录错误码。"""
    nodes = [_node("n1", NODE_TYPE_TOOL)]
    version = _version(nodes, [], entry="n1")
    sink = _RecordingSink()
    engine = WorkflowEngine({"TOOL": _FailingExecutor(NODE_TYPE_TOOL)}, sink=sink)
    run = engine.run(version, {})
    assert run.status == WORKFLOW_RUN_STATUS_FAILED
    assert run.error == str(ErrorCode.INTERNAL_ERROR)
    assert "run_failed" in sink.events


def test_build_graph_prefers_explicit_entities() -> None:
    """``build_graph`` 优先使用显式节点 / 连边实体。"""
    nodes = [_node("n1", NODE_TYPE_TOOL)]
    version = _version(nodes, [], entry="n1")
    graph = build_graph(version, nodes=nodes, edges=[])
    assert graph.entry == "n1"
    assert list(graph.nodes) == ["n1"]
    assert NodeScheduler(graph).order() == ["n1"]


def test_workflow_graph_topo_order_detects_cycle() -> None:
    """``WorkflowGraph.topo_order`` 直接暴露环检测。"""
    graph = WorkflowGraph(
        version_id="wv-1",
        nodes={"a": _node("a", NODE_TYPE_TOOL), "b": _node("b", NODE_TYPE_TOOL)},
        edges=(_edge("a", "b"), _edge("b", "a")),
        entry="a",
    )
    with pytest.raises(DomainError):
        graph.topo_order()


def test_node_registry_register_and_require() -> None:
    """``NodeRegistry`` 登记 / 取用 / 缺失报错。"""
    registry = NodeRegistry()
    executor = _EchoExecutor(NODE_TYPE_TOOL)
    registry.register(executor)
    assert registry.get(NODE_TYPE_TOOL) is executor
    assert registry.types() == (NODE_TYPE_TOOL,)
    with pytest.raises(DomainError):
        registry.require(NODE_TYPE_AGENT)


def test_retry_policy_backoff_and_retry_on() -> None:
    """重试策略：指数退避受上限截断；``retry_on`` 过滤生效。"""
    policy = RetryPolicy(max_attempts=5, backoff_base_ms=100, backoff_max_ms=300)
    assert policy.delay_ms(1) == 100
    assert policy.delay_ms(2) == 200
    assert policy.delay_ms(3) == 300  # 受上限截断
    assert policy.delay_ms(4) == 300

    strict = RetryPolicy(max_attempts=3, retry_on=("TOOL_TIMEOUT",))
    assert strict.should_retry(DomainError("t", code=ErrorCode.TOOL_TIMEOUT))
    assert not strict.should_retry(DomainError("v", code=ErrorCode.VALIDATION_ERROR))


def test_run_with_retry_exhausts_and_reraises() -> None:
    """重试耗尽后原样抛出末次异常；注入 ``sleep`` 可断言退避次数。"""
    sleeps: list[float] = []
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        raise DomainError("always", code=ErrorCode.TOOL_TIMEOUT)

    policy = RetryPolicy(max_attempts=3, backoff_base_ms=10)
    with pytest.raises(DomainError):
        run_with_retry(operation, policy=policy, sleep=sleeps.append)
    assert calls["n"] == 3
    assert len(sleeps) == 2  # 末次失败不再退避


def test_run_with_retry_succeeds_after_retry() -> None:
    """第二次尝试成功即返回。"""
    calls = {"n": 0}

    def operation() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise DomainError("flaky", code=ErrorCode.TOOL_TIMEOUT)
        return "ok"

    policy = RetryPolicy(max_attempts=3, backoff_base_ms=1)
    assert run_with_retry(operation, policy=policy, sleep=lambda _s: None) == "ok"


def test_timeout_budget_expiry() -> None:
    """时间预算：不限时返回 ``None``；耗尽 → ``assert_not_expired`` 抛错。"""
    unlimited = TimeoutBudget(None)
    assert unlimited.remaining_ms() is None
    assert not unlimited.expired()
    unlimited.assert_not_expired()

    exhausted = TimeoutBudget(total_ms=0)
    assert exhausted.expired()
    with pytest.raises(DomainError) as excinfo:
        exhausted.assert_not_expired()
    assert excinfo.value.code == ErrorCode.TOOL_TIMEOUT


def test_variable_context_snapshot_roundtrip() -> None:
    """变量上下文快照可往返（挂起 / 续跑 / 重放依赖此）。"""
    ctx = VariableContext(inputs={"topic": "astra"}, outputs={"n1": {"text": "hello"}})
    restored = VariableContext.from_snapshot(ctx.snapshot())
    assert restored.resolve("${n1.text}") == "hello"
    assert restored.resolve("${input.topic}") == "astra"
    assert restored.resolve("missing") == "missing"
    assert restored.resolve("${nope.x}") is None


def test_null_runtime_bridge_refuses_silently_passing() -> None:
    """``NullRuntimeBridge`` 未装配时**显式报错**（不静默放行）。"""
    from astra_workflow.engine import NullRuntimeBridge

    bridge = NullRuntimeBridge()
    assert isinstance(bridge, RuntimeBridge)
    with pytest.raises(DomainError) as excinfo:
        bridge.execute_tool(_node("n1", NODE_TYPE_TOOL), VariableContext())
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


def test_startup_planner_is_structurally_compatible() -> None:
    """起步 ``Planner`` 结构化兼容 RP-05 Protocol 且**有界**。"""
    planner = build_simple_planner(max_steps=2)
    assert isinstance(planner, SimplePlanner)

    plan: Plan = planner.plan("先查资料。再写摘要。最后润色。", {"tools": ["web_search"]})
    assert plan.goal.startswith("先查资料")
    assert len(plan.steps) == 2  # 有界
    assert isinstance(plan, Plan)

    empty = planner.plan("")
    assert empty.steps == []
    assert empty.goal == ""


def test_startup_planner_matches_tool_literally() -> None:
    """``context["tools"]`` 命中时挂 ``tool_name``，**不猜测参数**。"""
    planner = SimplePlanner()
    plan = planner.plan("用 web_search 查一下 Astra AI", {"tools": ["web_search", "shell_exec"]})
    assert plan.steps[0].tool_name == "web_search"
    assert plan.steps[0].arguments == {}


def test_node_run_default_attempt() -> None:
    """节点记录默认 ``attempt`` 为 ``DEFAULT_ATTEMPT``。"""
    row = WorkflowNodeRun(workflow_run_id="run-1", node_key="n1")
    assert row.attempt == DEFAULT_ATTEMPT


def test_workflow_entity_defaults() -> None:
    """Workflow 聚合根默认值（``DRAFT``）。"""
    workflow = Workflow(name="demo")
    assert workflow.status == "DRAFT"
    assert workflow.current_version_id is None
