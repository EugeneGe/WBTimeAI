"""Workflow ↔ Runtime / 权限链 / 并发 集成测试（W4 / T2-23）。

覆盖（W4 裁定 §5 T2-23 验收 + §7.1 风险）：

- 节点内执行**不绕过** Runtime 与**权限单一判定链**（``I-P2-05``）：
  ``DENY`` → 工具**不被执行**且上抛 ``PERMISSION_DENIED``；``ALLOW`` → 正常执行；
- MCP 节点按 R10 命名 ``mcp:<server>.<tool>`` 走**同一** ``ToolExecutor`` / 判定链；
- ``PARALLEL ≤ max_parallel``（``N-P2-02``）：超限即 ``RESOURCE_LIMIT_EXCEEDED``；
- 活跃 Run 上限生效、**无超卖**；
- ``sandbox_session`` **跨 Run 不共享**；
- **WR-6 分层**：``astra_workflow`` 中仅 ``engine/runtime_bridge.py`` 可 import
  ``astra_runtime`` / ``astra_tool``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import ConcurrencyConfig, ToolEffect, ToolPermission
from astra_runtime import RuntimePermissionChecker, ToolCallRequest, ToolExecutor
from astra_security.egress import SecurityEgressPolicy
from astra_tool import (
    PermissionChecker,
    ToolContext,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from astra_workflow import (
    NODE_TYPE_MCP,
    NODE_TYPE_TOOL,
    WORKFLOW_RUN_STATUS_FAILED,
    WorkflowNode,
)
from astra_workflow.engine import VariableContext
from astra_workflow.engine.concurrency import ActiveRunGuard, ConcurrencyGuardImpl
from astra_workflow.engine.runtime_bridge import (
    MCP_TOOL_NAME_TEMPLATE,
    RuntimeBridgeImpl,
    mcp_tool_name,
)
from astra_workflow.nodes import NodeContext, ToolNode

from tests.unit.runtime_stubs import EchoTool, allow_tool

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_SRC = REPO_ROOT / "packages" / "workflow" / "src" / "astra_workflow"


# -- fakes -------------------------------------------------------------------


class _SpyTool:
    """记录是否被调用的工具（用于判定「DENIED → 不执行」）。

    使用**真实** ``ToolSpec`` / ``ToolResult``（``ToolExecutor`` 读
    ``spec.metadata.name`` / ``spec.permission.action`` / ``result.ok``），
    避免桩件与契约漂移导致假绿。
    """

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
        """记录入参并返回成功结果。"""
        self.calls.append(dict(arguments))
        return ToolResult.success({"echoed": True, "arguments": dict(arguments)})


def _ctx() -> NodeContext:
    return NodeContext(run_id="run-1", tenant_id="tenant-1", requested_by="u-1")


def _deny_all() -> RuntimePermissionChecker:
    """无规则校验器（deny-by-default）。"""
    return RuntimePermissionChecker(PermissionChecker())


def _allow(name: str) -> RuntimePermissionChecker:
    """显式 ALLOW 指定工具。"""
    return RuntimePermissionChecker(allow_tool(name))


# -- 权限单一判定链 ----------------------------------------------------------


def test_tool_node_denied_does_not_execute() -> None:
    """``DENY`` → 工具**不被执行** + 上抛 ``PERMISSION_DENIED``（**唯一判定链**）。"""
    spy = _SpyTool("fs.read")
    registry = ToolRegistry()
    registry.register("fs.read", spy)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_deny_all())
    bridge = RuntimeBridgeImpl(
        tool_executor=executor,
        checker_resolver=lambda agent_id: _deny_all(),
    )

    node = WorkflowNode(
        workflow_version_id="wv-1",
        node_key="n1",
        type=NODE_TYPE_TOOL,
        config={"tool": "fs.read", "arguments": {"path": "/tmp/a"}},
    )
    with pytest.raises(DomainError) as excinfo:
        ToolNode(bridge).execute(node, VariableContext(), _ctx())

    assert excinfo.value.code == ErrorCode.PERMISSION_DENIED
    assert spy.calls == [], "权限拒绝时工具**不得**被执行"


def test_tool_node_allowed_executes_via_tool_executor() -> None:
    """``ALLOW`` → 经 ``ToolExecutor`` 正常执行，产出回传。"""
    spy = _SpyTool("fs.read")
    registry = ToolRegistry()
    registry.register("fs.read", spy)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_allow("fs.read"))
    bridge = RuntimeBridgeImpl(
        tool_executor=executor,
        checker_resolver=lambda agent_id: _allow("fs.read"),
    )

    node = WorkflowNode(
        workflow_version_id="wv-1",
        node_key="n1",
        type=NODE_TYPE_TOOL,
        config={"tool": "fs.read", "arguments": {"path": "/tmp/a"}},
    )
    result = ToolNode(bridge).execute(node, VariableContext(), _ctx())
    assert spy.calls == [{"path": "/tmp/a"}]
    assert result.output["echoed"] is True


def test_mcp_node_uses_r10_naming_and_same_chain() -> None:
    """MCP 节点按 R10 ``mcp:<server>.<tool>`` 命名，走**同一** ``ToolExecutor`` / 判定链。"""
    name = mcp_tool_name("fs", "read_file")
    expected = MCP_TOOL_NAME_TEMPLATE.format(server="fs", tool="read_file")
    assert name == "mcp:fs.read_file" == expected

    spy = _SpyTool(name)
    registry = ToolRegistry()
    registry.register(name, spy)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_allow(name))
    bridge = RuntimeBridgeImpl(
        tool_executor=executor, checker_resolver=lambda agent_id: _allow(name)
    )

    node = WorkflowNode(
        workflow_version_id="wv-1",
        node_key="n1",
        type=NODE_TYPE_MCP,
        config={"server": "fs", "tool": "read_file", "arguments": {}},
    )
    from astra_workflow.nodes import McpNode

    result = McpNode(bridge).execute(node, VariableContext(), _ctx())
    assert spy.calls == [{}]
    assert result.output["echoed"] is True

    # 同一命名下改为 DENY → 同样被拒（未绕过判定链）。
    deny_bridge = RuntimeBridgeImpl(
        tool_executor=ToolExecutor(tool_registry=registry, permission_checker=_deny_all()),
        checker_resolver=lambda agent_id: _deny_all(),
    )
    spy.calls.clear()
    with pytest.raises(DomainError) as excinfo:
        McpNode(deny_bridge).execute(node, VariableContext(), _ctx())
    assert excinfo.value.code == ErrorCode.PERMISSION_DENIED
    assert spy.calls == []


def test_unregistered_tool_fails_without_bypassing_executor() -> None:
    """未注册工具：由 ``ToolExecutor`` 返回失败，**不**在节点内自行放行。"""
    executor = ToolExecutor(tool_registry=ToolRegistry(), permission_checker=_allow("nope"))
    bridge = RuntimeBridgeImpl(tool_executor=executor, checker_resolver=lambda a: _allow("nope"))
    node = WorkflowNode(
        workflow_version_id="wv-1", node_key="n1", type=NODE_TYPE_TOOL, config={"tool": "nope"}
    )
    with pytest.raises(DomainError) as excinfo:
        ToolNode(bridge).execute(node, VariableContext(), _ctx())
    assert excinfo.value.code == ErrorCode.NOT_FOUND


def test_bridge_requires_tool_executor() -> None:
    """未装配 ``ToolExecutor`` → ``CONFIGURATION_ERROR``（不静默放行）。"""
    bridge = RuntimeBridgeImpl()
    node = WorkflowNode(
        workflow_version_id="wv-1", node_key="n1", type=NODE_TYPE_TOOL, config={"tool": "x"}
    )
    with pytest.raises(DomainError) as excinfo:
        ToolNode(bridge).execute(node, VariableContext(), _ctx())
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


def test_tool_context_carries_egress_policy_and_no_shared_sandbox() -> None:
    """``ToolContext`` 携带出网策略；``sandbox_session`` **跨 Run 不共享**（恒 ``None``）。

    出网策略取**唯一入口**实现 ``SecurityEgressPolicy``（``EgressPolicy`` 为
    Protocol，不可实例化）。
    """
    bridge = RuntimeBridgeImpl(egress_policy=SecurityEgressPolicy())
    node = WorkflowNode(workflow_version_id="wv-1", node_key="n1", type=NODE_TYPE_TOOL)
    tool_ctx = bridge._tool_context(node, _ctx(), agent_id="agent-1")
    assert isinstance(tool_ctx, ToolContext)
    assert tool_ctx.egress_policy is not None
    assert tool_ctx.sandbox_session is None
    assert tool_ctx.tenant_id == "tenant-1"
    assert tool_ctx.run_id == "run-1"


# -- 并发控制 ----------------------------------------------------------------


def test_concurrency_guard_limit_is_max_parallel() -> None:
    """守卫上限 = ``ConcurrencyConfig.max_parallel``（新增独立字段，默认 4）。"""
    guard = ConcurrencyGuardImpl(ConcurrencyConfig())
    assert guard.max_parallel == 4
    guard.acquire(4)
    guard.release(4)
    assert guard.available == 4


def test_concurrency_guard_exceeds_limit_raises() -> None:
    """**超限即抛** ``RESOURCE_LIMIT_EXCEEDED``（**不静默排队**）。"""
    guard = ConcurrencyGuardImpl(ConcurrencyConfig(max_parallel=2))
    guard.acquire(2)
    with pytest.raises(DomainError) as excinfo:
        guard.acquire(1)
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED
    guard.release(2)
    guard.acquire(1)  # 归还后可用
    guard.release(1)


def test_concurrency_guard_does_not_queue() -> None:
    """一次性申请超限数量 → 立即抛错，且**不残留**已获配额（全有或全无）。"""
    guard = ConcurrencyGuardImpl(ConcurrencyConfig(max_parallel=2))
    with pytest.raises(DomainError):
        guard.acquire(3)
    assert guard.available == 2, "部分获取必须回滚（全有或全无）"


def test_active_run_guard_has_no_oversell() -> None:
    """活跃 Run 上限生效、**无超卖**。"""
    guard = ActiveRunGuard(lambda key: 1, max_active=1)
    with pytest.raises(DomainError) as excinfo:
        guard.check("tenant-1")
    assert excinfo.value.code == ErrorCode.RESOURCE_LIMIT_EXCEEDED

    assert ActiveRunGuard(lambda key: 0, max_active=1).check("tenant-1") is None
    # 0 / 负上限 = 不限。
    assert ActiveRunGuard(lambda key: 99, max_active=0).check("tenant-1") is None
    # 缺省读 max_runs_per_conversation（=1）。
    assert ActiveRunGuard(lambda key: 0).max_active == 1


def test_workflow_run_status_failed_constant() -> None:
    """状态常量对齐（防拼写漂移）。"""
    assert WORKFLOW_RUN_STATUS_FAILED == "FAILED"


# -- 分层（WR-6） ------------------------------------------------------------


def test_only_runtime_bridge_imports_runtime_or_tool() -> None:
    """🔴 ``astra_workflow`` 中**仅** ``engine/runtime_bridge.py`` 可 import runtime / tool。"""
    forbidden = {"astra_runtime", "astra_tool"}
    offenders: list[str] = []
    for path in sorted(WORKFLOW_SRC.rglob("*.py")):
        if path.name == "runtime_bridge.py":
            continue
        text = path.read_text(encoding="utf-8")
        for module in forbidden:
            if f"import {module}" in text or f"from {module}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} -> {module}")
    assert not offenders, f"Runtime 耦合扩散：{offenders}"


def test_echo_tool_stub_is_reusable() -> None:
    """复用既有 ``EchoTool`` stub 走通 ``ToolExecutor``（回归闸：判定链未破坏）。"""
    tool = EchoTool(name="echo", output={"ok": True})
    registry = ToolRegistry()
    registry.register("echo", tool)
    executor = ToolExecutor(tool_registry=registry, permission_checker=_allow("echo"))
    result = executor.execute(
        ToolCallRequest(name="echo", arguments={"x": 1}),
        ctx=ToolContext(tenant_id="t1", agent_id="a1"),
    )
    assert result.ok is True
    assert result.output == {"ok": True}
    assert ToolEffect.ALLOW == "ALLOW"
    assert ToolPermission is not None
