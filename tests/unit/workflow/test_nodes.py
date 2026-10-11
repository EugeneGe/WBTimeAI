"""``astra_workflow`` 8 类节点单元测试（W4 / T2-22）。

以 fake ``RuntimeBridge`` / fake ``ApprovalGateway`` / fake 分派器驱动，**零 Runtime**。

覆盖（W4 裁定 §5 T2-22 验收）：

- 8 类节点均可执行；
- ``CONDITION`` 受**白名单**限制（禁任意代码：``eval`` / 属性访问 / 算术均被拒）；
- ``PARALLEL ≤ max_parallel``，**超限 ``RESOURCE_LIMIT_EXCEEDED``（写死断言）**；
- ``LOOP`` 有界（``max_iterations`` 强制 + 绝对上限 + ``until`` 提前退出）；
- ``HUMAN_APPROVAL`` 挂起→决议→续跑（节点级）；
- 接口补齐：``ErrorCode.RESOURCE_LIMIT_EXCEEDED`` + ``ConcurrencyConfig.max_parallel``。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import ApprovalGateway, ConcurrencyConfig
from astra_domain.constants import DEFAULT_MAX_PARALLEL
from astra_workflow import (
    NODE_TYPE_AGENT,
    NODE_TYPE_CONDITION,
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    NODE_TYPE_LOOP,
    NODE_TYPE_MCP,
    NODE_TYPE_PARALLEL,
    NODE_TYPE_TOOL,
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
    WorkflowNode,
)
from astra_workflow.engine import VariableContext
from astra_workflow.nodes import (
    ABSOLUTE_MAX_ITERATIONS,
    APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE,
    AgentNode,
    ConditionNode,
    EndNode,
    HumanApprovalNode,
    LoopNode,
    McpNode,
    NodeContext,
    ParallelNode,
    ToolNode,
    build_default_node_registry,
    evaluate_expression,
)
from astra_workflow.nodes.condition import DEFAULT_TRUE_BRANCH

# -- fakes -------------------------------------------------------------------


class _FakeBridge:
    """按 ``config`` 回显的 fake ``RuntimeBridge``。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run_agent(self, node, var_ctx, ctx=None) -> dict[str, Any]:
        self.calls.append(("agent", node.node_key))
        return {"text": f"agent:{node.node_key}", "agent_run_id": "ar-1"}

    def execute_tool(self, node, var_ctx, ctx=None) -> dict[str, Any]:
        self.calls.append(("tool", node.node_key))
        return {"ok": True, "tool_call_id": "tc-1"}

    def execute_mcp(self, node, var_ctx, ctx=None) -> dict[str, Any]:
        self.calls.append(("mcp", node.node_key))
        return {"ok": True, "tool_call_id": "tc-mcp-1"}

    def resolve_checker(self, agent_id: str) -> Any:
        return {"agent_id": agent_id}


class _FakeApproval:
    def __init__(self, approval_id: str) -> None:
        self.id = approval_id


class _FakeGateway:
    """记录审批请求的 fake 网关。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> _FakeApproval:
        self.requests.append(dict(kwargs))
        return _FakeApproval(f"approval-{len(self.requests)}")

    def find_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Any | None:
        """无既有审批（单次执行场景）——满足 ``ApprovalGateway``（T2-26 加性）。"""
        return None


class _RecordingGuard:
    """记录 acquire / release 的 fake 并发守卫。"""

    def __init__(self) -> None:
        self.acquired: list[int] = []
        self.released: list[int] = []

    def acquire(self, slots: int = 1) -> None:
        self.acquired.append(slots)

    def release(self, slots: int = 1) -> None:
        self.released.append(slots)


class _ExhaustedGuard:
    """恒超限的守卫（模拟真实配额耗尽）。"""

    def acquire(self, slots: int = 1) -> None:
        raise DomainError("并发配额耗尽", code=ErrorCode.RESOURCE_LIMIT_EXCEEDED)

    def release(self, slots: int = 1) -> None:
        """无操作。"""


def _node(key: str, node_type: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(
        workflow_version_id="wv-1", node_key=key, type=node_type, config=dict(config)
    )


def _ctx(**kwargs: Any) -> NodeContext:
    ctx = NodeContext(run_id="run-1", tenant_id="tenant-1", requested_by="u-1")
    for key, value in kwargs.items():
        setattr(ctx, key, value)
    return ctx


def _dispatcher(record: list[str]) -> Any:
    class _Dispatcher:
        def dispatch(self, node_key: str, var_ctx: Any, ctx: Any = None) -> Any:
            from astra_workflow.nodes import NodeResult

            record.append(node_key)
            return NodeResult.success({"ran": node_key})

    return _Dispatcher()


# -- AGENT / TOOL / MCP ------------------------------------------------------


def test_agent_node_executes_via_bridge() -> None:
    """``AGENT`` 节点经 ``RuntimeBridge.run_agent`` 执行并摘出 ``agent_run_id``。"""
    bridge = _FakeBridge()
    result = AgentNode(bridge).execute(
        _node("n1", NODE_TYPE_AGENT, agent_id="agent-1", message="hello"), VariableContext()
    )
    assert result.agent_run_id == "ar-1"
    assert result.output == {"text": "agent:n1"}
    assert bridge.calls == [("agent", "n1")]


def test_agent_node_requires_agent_id() -> None:
    """``AGENT`` 节点缺 ``agent_id`` → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError) as excinfo:
        AgentNode(_FakeBridge()).execute(_node("n1", NODE_TYPE_AGENT), VariableContext())
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_tool_node_executes_via_bridge() -> None:
    """``TOOL`` 节点经 ``RuntimeBridge.execute_tool`` 执行（**唯一判定链**入口）。"""
    bridge = _FakeBridge()
    result = ToolNode(bridge).execute(
        _node("n1", NODE_TYPE_TOOL, tool="fs.read", arguments={"path": "${input.path}"}),
        VariableContext(inputs={"path": "/tmp/a.txt"}),
    )
    assert result.tool_call_id == "tc-1"
    assert result.output == {"ok": True}
    assert bridge.calls == [("tool", "n1")]


def test_tool_node_requires_tool() -> None:
    """``TOOL`` 节点缺 ``tool`` → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError):
        ToolNode(_FakeBridge()).execute(_node("n1", NODE_TYPE_TOOL), VariableContext())


def test_mcp_node_executes_via_bridge() -> None:
    """``MCP`` 节点经 ``RuntimeBridge.execute_mcp`` 执行。"""
    bridge = _FakeBridge()
    result = McpNode(bridge).execute(
        _node("n1", NODE_TYPE_MCP, server="fs", tool="read_file"), VariableContext()
    )
    assert result.tool_call_id == "tc-mcp-1"
    assert bridge.calls == [("mcp", "n1")]


def test_mcp_node_requires_server_and_tool() -> None:
    """``MCP`` 节点缺 ``server`` / ``tool`` → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError):
        McpNode(_FakeBridge()).execute(_node("n1", NODE_TYPE_MCP, server="fs"), VariableContext())


# -- CONDITION ---------------------------------------------------------------


def test_condition_node_selects_true_branch() -> None:
    """``CONDITION`` 为真 → ``true`` 分支。"""
    var_ctx = VariableContext(outputs={"n1": {"score": 0.9}})
    result = ConditionNode().execute(
        _node("c", NODE_TYPE_CONDITION, expression="n1.score > 0.5"), var_ctx
    )
    assert result.next_branch == DEFAULT_TRUE_BRANCH
    assert result.output["value"] is True


def test_condition_node_selects_false_branch() -> None:
    """``CONDITION`` 为假 → ``false`` 分支（可自定义分支名）。"""
    var_ctx = VariableContext(outputs={"n1": {"score": 0.1}})
    result = ConditionNode().execute(
        _node(
            "c",
            NODE_TYPE_CONDITION,
            expression="n1.score > 0.5",
            true_branch="yes",
            false_branch="no",
        ),
        var_ctx,
    )
    assert result.next_branch == "no"


def test_condition_whitelist_supports_len_contains_in_and_logic() -> None:
    """白名单运算符：``len`` / ``contains`` / ``in`` / ``and`` / ``or`` / ``not``。"""
    data = {"n1": {"items": ["a", "b", "c"], "kind": "report"}}
    assert evaluate_expression("len(n1.items) >= 2", data) is True
    assert evaluate_expression("contains(n1.items, 'a')", data) is True
    assert evaluate_expression("n1.kind == 'report' and not (len(n1.items) > 5)", data) is True
    assert evaluate_expression("'report' in ['report', 'log']", data) is True
    assert evaluate_expression("n1.kind == 'draft' or len(n1.items) == 3", data) is True
    assert evaluate_expression("n1.kind != 'report'", data) is False


def test_condition_rejects_arbitrary_code() -> None:
    """**禁任意代码**：属性访问 / 下标 / Lambda / 算术 / 危险调用均被拒。"""
    data = {"n1": {"a": 1}}
    denied = [
        "__import__('os').system('ls')",  # 危险调用（Attribute + 非白名单函数）
        "n1.__class__",  # 属性访问
        "n1['a']",  # 下标
        "(lambda: 1)()",  # Lambda
        "1 + 1",  # 算术（白名单外）
        "-1",  # 一元负号（白名单外）
        "[x for x in n1]",  # 推导式
        "eval('1')",  # 非白名单函数
    ]
    for expression in denied:
        with pytest.raises(DomainError) as excinfo:
            evaluate_expression(expression, data)
        assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_condition_whitelist_narrows_only() -> None:
    """``config.whitelist`` 与内置白名单**取交集**（**只收窄**）。"""
    data = {"n1": {"score": 3}}
    # 收窄到仅 ``>`` → ``<`` 被拒。
    with pytest.raises(DomainError):
        evaluate_expression("n1.score < 5", data, whitelist=[">"])
    assert evaluate_expression("n1.score > 1", data, whitelist=[">"]) is True


def test_condition_rejects_syntax_error() -> None:
    """语法错误 → ``VALIDATION_ERROR``（不抛裸 ``SyntaxError``）。"""
    with pytest.raises(DomainError) as excinfo:
        evaluate_expression("n1.score >", {"n1": {"score": 1}})
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_condition_node_requires_expression() -> None:
    """``CONDITION`` 缺 ``expression`` → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError):
        ConditionNode().execute(_node("c", NODE_TYPE_CONDITION), VariableContext())


# -- PARALLEL ----------------------------------------------------------------


def test_parallel_node_runs_branches() -> None:
    """``PARALLEL`` 并发执行分支并聚合输出（各分支独立执行）。"""
    record: list[str] = []
    ctx = _ctx(dispatcher=_dispatcher(record))
    guard = _RecordingGuard()
    node = ParallelNode(concurrency=guard, max_parallel=4, use_threads=False)
    result = node.execute(
        _node("p", NODE_TYPE_PARALLEL, branches=["b1", "b2"]), VariableContext(), ctx
    )
    assert sorted(record) == ["b1", "b2"]
    assert result.output["branches"] == {"b1": {"ran": "b1"}, "b2": {"ran": "b2"}}
    assert guard.acquired == [2]
    assert guard.released == [2]


def test_parallel_node_exceeding_limit_raises_resource_limit_exceeded() -> None:
    """**写死断言**：分支数超 ``max_parallel`` → ``RESOURCE_LIMIT_EXCEEDED``（不静默排队）。"""
    record: list[str] = []
    ctx = _ctx(dispatcher=_dispatcher(record))
    guard = _RecordingGuard()
    node = ParallelNode(concurrency=guard, max_parallel=2, use_threads=False)
    with pytest.raises(DomainError) as excinfo:
        node.execute(
            _node("p", NODE_TYPE_PARALLEL, branches=["b1", "b2", "b3"]),
            VariableContext(),
            ctx,
        )
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED
    assert record == []  # 超限**不执行**任何分支
    assert guard.acquired == []  # 超限**不占**配额


def test_parallel_node_config_max_parallel_only_narrows() -> None:
    """``config.max_parallel`` 与引擎默认取**较小值**（只收窄）。"""
    ctx = _ctx(dispatcher=_dispatcher([]))
    node = ParallelNode(max_parallel=8, use_threads=False)
    # config 声明 1 → 生效上限 1 → 2 分支超限。
    with pytest.raises(DomainError) as excinfo:
        node.execute(
            _node("p", NODE_TYPE_PARALLEL, branches=["b1", "b2"], max_parallel=1),
            VariableContext(),
            ctx,
        )
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED
    # config 声明 100 → 仍受引擎默认 8 约束，不放大。
    result = node.execute(
        _node("p", NODE_TYPE_PARALLEL, branches=["b1"], max_parallel=100), VariableContext(), ctx
    )
    assert "b1" in result.output["branches"]


def test_parallel_node_guard_exhaustion_propagates() -> None:
    """守卫配额耗尽 → ``RESOURCE_LIMIT_EXCEEDED`` 上抛。"""
    ctx = _ctx(dispatcher=_dispatcher([]))
    node = ParallelNode(concurrency=_ExhaustedGuard(), max_parallel=4, use_threads=False)
    with pytest.raises(DomainError) as excinfo:
        node.execute(_node("p", NODE_TYPE_PARALLEL, branches=["b1"]), VariableContext(), ctx)
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED


def test_parallel_node_requires_dispatcher() -> None:
    """``PARALLEL`` 无分派器 → ``CONFIGURATION_ERROR``。"""
    node = ParallelNode(use_threads=False)
    with pytest.raises(DomainError) as excinfo:
        node.execute(_node("p", NODE_TYPE_PARALLEL, branches=["b1"]), VariableContext(), None)
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


# -- LOOP --------------------------------------------------------------------


def test_loop_node_is_bounded_by_max_iterations() -> None:
    """``LOOP`` 有界：``max_iterations`` 强制（默认 10）。"""
    record: list[str] = []
    ctx = _ctx(dispatcher=_dispatcher(record))
    result = LoopNode().execute(
        _node("l", NODE_TYPE_LOOP, body="b1", max_iterations=3), VariableContext(), ctx
    )
    assert record == ["b1", "b1", "b1"]
    assert result.output["iterations"] == 3


def test_loop_node_until_stops_early() -> None:
    """``until`` 为真时**提前退出**（白名单表达式，禁 ``eval``）。"""
    record: list[str] = []

    class _CountingDispatcher:
        def __init__(self) -> None:
            self.n = 0

        def dispatch(self, node_key: str, var_ctx: Any, ctx: Any = None) -> Any:
            from astra_workflow.nodes import NodeResult

            self.n += 1
            var_ctx.set_output("b1", {"count": self.n})
            record.append(node_key)
            return NodeResult.success({"count": self.n})

    ctx = _ctx(dispatcher=_CountingDispatcher())
    result = LoopNode().execute(
        _node("l", NODE_TYPE_LOOP, body="b1", max_iterations=10, until="b1.count >= 2"),
        VariableContext(),
        ctx,
    )
    assert result.output["iterations"] == 2


def test_loop_node_rejects_invalid_max_iterations() -> None:
    """``max_iterations`` 非法 / 超绝对上限 → ``VALIDATION_ERROR``。"""
    ctx = _ctx(dispatcher=_dispatcher([]))
    loop = LoopNode()
    for bad in [0, -1, "abc"]:
        with pytest.raises(DomainError) as excinfo:
            loop.execute(
                _node("l", NODE_TYPE_LOOP, body="b1", max_iterations=bad), VariableContext(), ctx
            )
        assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError) as excinfo:
        loop.execute(
            _node("l", NODE_TYPE_LOOP, body="b1", max_iterations=ABSOLUTE_MAX_ITERATIONS + 1),
            VariableContext(),
            ctx,
        )
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_loop_node_requires_body() -> None:
    """``LOOP`` 缺 ``body`` → ``VALIDATION_ERROR``。"""
    ctx = _ctx(dispatcher=_dispatcher([]))
    with pytest.raises(DomainError):
        LoopNode().execute(_node("l", NODE_TYPE_LOOP), VariableContext(), ctx)


# -- HUMAN_APPROVAL / END ----------------------------------------------------


def test_human_approval_node_suspends() -> None:
    """``HUMAN_APPROVAL`` 发起审批并挂起（``WAITING_APPROVAL``，非终态）。"""
    gateway = _FakeGateway()
    result = HumanApprovalNode(gateway).execute(
        _node("approve", NODE_TYPE_HUMAN_APPROVAL, payload={"amount": 100}),
        VariableContext(),
        _ctx(),
    )
    assert result.status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL
    assert result.suspended
    assert result.approval_id == "approval-1"
    assert gateway.requests[0]["subject_type"] == APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE
    # subject_ref 缺省 = {workflow_run_id}:{node_key}
    assert gateway.requests[0]["subject_ref"] == "run-1:approve"


def test_human_approval_node_uses_explicit_subject_ref() -> None:
    """``subject_ref`` 可由 ``config`` 显式指定。"""
    gateway = _FakeGateway()
    HumanApprovalNode(gateway).execute(
        _node("approve", NODE_TYPE_HUMAN_APPROVAL, subject_ref="wf-1:n1"),
        VariableContext(),
        _ctx(),
    )
    assert gateway.requests[0]["subject_ref"] == "wf-1:n1"


def test_human_approval_gateway_is_protocol() -> None:
    """``HumanApprovalNode`` 依赖 **Protocol**（``ApprovalGateway``），非具体安全包。"""
    gateway = _FakeGateway()
    assert isinstance(gateway, ApprovalGateway)


def test_end_node_is_noop_success() -> None:
    """``END`` 为终态汇聚，无副作用。"""
    result = EndNode().execute(_node("end", NODE_TYPE_END), VariableContext())
    assert result.output == {}
    assert not result.failed


# -- 注册表与接口补齐 ---------------------------------------------------------


def test_default_node_registry_covers_eight_types() -> None:
    """默认注册表覆盖 8 类节点。"""
    registry = build_default_node_registry(
        bridge=_FakeBridge(), gateway=_FakeGateway(), max_parallel=4
    )
    expected = {
        NODE_TYPE_AGENT,
        NODE_TYPE_TOOL,
        NODE_TYPE_MCP,
        NODE_TYPE_CONDITION,
        NODE_TYPE_PARALLEL,
        NODE_TYPE_LOOP,
        NODE_TYPE_HUMAN_APPROVAL,
        NODE_TYPE_END,
    }
    assert set(registry.types()) == expected


def test_error_code_resource_limit_exceeded_exists() -> None:
    """接口补齐：``ErrorCode.RESOURCE_LIMIT_EXCEEDED`` 存在且字面值稳定。"""
    assert ErrorCode.RESOURCE_LIMIT_EXCEEDED == "RESOURCE_LIMIT_EXCEEDED"


def test_concurrency_config_max_parallel_additive() -> None:
    """接口补齐：``ConcurrencyConfig.max_parallel``（默认 4）+ 序列化往返。"""
    config = ConcurrencyConfig()
    assert config.max_parallel == DEFAULT_MAX_PARALLEL == 4
    assert config.to_dict()["max_parallel"] == 4

    restored = ConcurrencyConfig.from_dict(config.to_dict())
    assert restored.max_parallel == 4
    # 向后兼容：旧字典（无 max_parallel 键）回退默认 4。
    assert ConcurrencyConfig.from_dict({}).max_parallel == DEFAULT_MAX_PARALLEL
    # 与 max_parallel_tools **互不等价**（独立字段）。
    assert ConcurrencyConfig(max_parallel_tools=99).max_parallel == 4
