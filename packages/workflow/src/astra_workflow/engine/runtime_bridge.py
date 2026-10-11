"""``RuntimeBridge`` 真实实现（W4 / T2-23）——🔴 **唯一** import ``astra_runtime`` /
``astra_tool`` 的模块（W4 裁定 §3.1 / WR-6）。

职责：把 Workflow 节点调用**转发**给既有执行内核，**不自建**任何判定源：

- ``TOOL`` / ``MCP`` → :class:`~astra_runtime.ToolExecutor`（**内建**
  ``ResourcePermissionChecker``，权限**单一判定链** F10/F11；``DENIED`` → **不执行**）；
  MCP 工具按 R10 命名 ``mcp:<server>.<tool>`` 经**同一** ``ToolExecutor`` 执行；
- 出网由 ``ToolContext.egress_policy`` 兜底（``EgressPolicy`` 为**唯一**出网入口，§6.4 #4）；
- ``AGENT`` → 组合根注入的 ``agent_runner``（``AgentRuntime.run`` 范式，产出独立
  ``agent_run``）；
- 权限判定器经 ``checker_resolver(agent_id)`` 解析（组合根 ``_resolve_permission_checker``
  同口径，F21）。

🔴 **不**在 runtime 落工作流级持久化（W4 裁定 §5 T2-23 / P2-46）：``ExecutionManager`` /
``execution_manager.py`` **零改**；工作流级记录由 ``astra_workflow`` 持久化。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import TOOL_CALL_STATUS_DENIED, ToolEffect
from astra_domain.ports import EgressPolicy
from astra_runtime import ToolCallRequest, ToolExecutor
from astra_tool import ToolContext

from ..domain import WorkflowNode
from ..engine.variables import VariableContext
from .ports import BRIDGE_KEY_AGENT_RUN_ID, BRIDGE_KEY_TOOL_CALL_ID

__all__ = [
    "MCP_TOOL_NAME_TEMPLATE",
    "RuntimeBridgeImpl",
    "build_runtime_bridge",
]


#: MCP 工具在**执行注册表**中的命名模板（R10；与 ``astra_mcp.registry.sync_to_tool_registry``
#: **同口径**，保证节点内 MCP 调用与 Agent 内 MCP 调用走**同一**判定链）。
MCP_TOOL_NAME_TEMPLATE = "mcp:{server}.{tool}"


def mcp_tool_name(server: str, tool: str) -> str:
    """按 R10 生成 MCP 工具在 ``ToolRegistry`` 中的名字。"""
    return MCP_TOOL_NAME_TEMPLATE.format(server=server, tool=tool)


class RuntimeBridgeImpl:
    """``RuntimeBridge`` 实现（**唯一** Runtime / Tool 耦合点）。"""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor | None = None,
        agent_runner: Callable[[str, str, dict[str, Any]], Any] | None = None,
        checker_resolver: Callable[[str], Any] | None = None,
        egress_policy: EgressPolicy | None = None,
        workspace_root: str | None = None,
        tool_call_recorder: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        """装配桥接（全部依赖由**组合根**注入）。

        Args:
            tool_executor: ``ToolExecutor``（内建权限单一判定链）。
            agent_runner: ``(agent_id, message, meta) -> RunResult``（``AgentRuntime.run``
                范式，由组合根提供；产出**独立** ``agent_run``）。
            checker_resolver: ``(agent_id) -> RuntimePermissionChecker``（F21 同口径）。
            egress_policy: 出网策略（``ToolContext.egress_policy``；``None`` 时 HTTP 工具
                退回**默认拒绝全部**语义）。
            workspace_root: 工作区根目录（filesystem 工具路径限定基准）。
            tool_call_recorder: 可选 ``(payload) -> tool_call_id``（落 ``tool_call`` 行，
                供 ``workflow_node_run.tool_call_id`` 关联；``None`` 时该列留空）。
        """
        self._tool_executor = tool_executor
        self._agent_runner = agent_runner
        self._checker_resolver = checker_resolver
        self._egress_policy = egress_policy
        self._workspace_root = workspace_root
        self._tool_call_recorder = tool_call_recorder

    # -- RuntimeBridge ------------------------------------------------------

    def run_agent(
        self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None
    ) -> dict[str, Any]:
        """执行 ``AGENT`` 节点（复用 ``AgentRuntime``，产出独立 ``agent_run``）。

        Raises:
            DomainError: 未装配 ``agent_runner``（``CONFIGURATION_ERROR``）。
        """
        if self._agent_runner is None:
            raise DomainError(
                "AGENT 节点未装配 agent_runner（AgentRuntime 未接线）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "agent_runner_missing", "node_key": node.node_key},
            )
        config = dict(node.config or {})
        agent_id = str(config.get("agent_id") or "")
        message = str(config.get("message") or "")
        result = self._agent_runner(
            agent_id,
            message,
            {
                "node_key": node.node_key,
                "run_id": getattr(ctx, "run_id", ""),
                "tenant_id": getattr(ctx, "tenant_id", None),
                "workflow_run_id": getattr(ctx, "run_id", ""),
            },
        )
        run_id = getattr(result, "run_id", None)
        content = getattr(result, "final_content", None)
        payload: dict[str, Any] = {
            "status": getattr(result, "status", None),
            "content": content if content is not None else "",
        }
        if run_id is not None:
            payload[BRIDGE_KEY_AGENT_RUN_ID] = str(run_id)
        return payload

    def execute_tool(
        self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None
    ) -> dict[str, Any]:
        """执行 ``TOOL`` 节点（**必过** ``ToolExecutor`` + 权限单一判定链）。"""
        config = dict(node.config or {})
        return self._execute_registered_tool(
            node,
            ctx,
            tool_name=str(config.get("tool") or ""),
            arguments=config.get("arguments") or {},
        )

    def execute_mcp(
        self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None
    ) -> dict[str, Any]:
        """执行 ``MCP`` 节点（按 R10 命名，经**同一** ``ToolExecutor`` + 判定链）。"""
        config = dict(node.config or {})
        server = str(config.get("server") or "")
        tool = str(config.get("tool") or "")
        return self._execute_registered_tool(
            node,
            ctx,
            tool_name=mcp_tool_name(server, tool),
            arguments=config.get("arguments") or {},
        )

    def resolve_checker(self, agent_id: str) -> Any:
        """解析某 Agent 的权限判定器（组合根同口径，F21）。

        Raises:
            DomainError: 未装配 ``checker_resolver``（``CONFIGURATION_ERROR``）。
        """
        if self._checker_resolver is None:
            raise DomainError(
                "未装配 permission_checker_resolver",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "checker_resolver_missing", "agent_id": agent_id},
            )
        return self._checker_resolver(agent_id)

    # -- 内部 ---------------------------------------------------------------

    def _execute_registered_tool(
        self,
        node: WorkflowNode,
        ctx: Any,
        *,
        tool_name: str,
        arguments: Any,
    ) -> dict[str, Any]:
        """经 ``ToolExecutor`` 执行注册表内工具（权限判定**唯一**入口）。

        Raises:
            DomainError: 未装配 ``tool_executor``（``CONFIGURATION_ERROR``）；
                权限拒绝（``PERMISSION_DENIED``）；工具执行失败（沿用工具错误码）。
        """
        if self._tool_executor is None:
            raise DomainError(
                "节点未装配 ToolExecutor（Tool 执行未接线）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "tool_executor_missing", "node_key": node.node_key},
            )
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}

        agent_id = str(node.config.get("agent_id") or "") or None
        checker = self.resolve_checker(agent_id) if agent_id else None
        tool_ctx = self._tool_context(node, ctx, agent_id=agent_id)

        executed = self._tool_executor.execute(
            ToolCallRequest(name=tool_name, arguments=dict(arguments)),
            ctx=tool_ctx,
            permission_checker=checker,
        )

        if executed.status == TOOL_CALL_STATUS_DENIED:
            raise DomainError(
                f"工具调用被权限链拒绝：{tool_name}",
                code=ErrorCode.PERMISSION_DENIED,
                data={
                    "reason": "permission_denied",
                    "node_key": node.node_key,
                    "tool": tool_name,
                },
            )
        if not executed.ok:
            raise DomainError(
                executed.error or f"工具执行失败：{tool_name}",
                code=_as_error_code(executed.error_code),
                data={"node_key": node.node_key, "tool": tool_name},
            )

        payload = (
            dict(executed.output)
            if isinstance(executed.output, dict)
            else {"value": executed.output}
        )
        if self._tool_call_recorder is not None:
            payload[BRIDGE_KEY_TOOL_CALL_ID] = self._tool_call_recorder(
                {
                    "tool_name": executed.tool_name or tool_name,
                    "arguments": dict(arguments),
                    "output": executed.output,
                    "status": executed.status,
                    "duration_ms": executed.duration_ms,
                    "run_id": getattr(ctx, "run_id", ""),
                    "node_key": node.node_key,
                }
            )
        return payload

    def _tool_context(self, node: WorkflowNode, ctx: Any, *, agent_id: str | None) -> ToolContext:
        """构造**per-node** ``ToolContext``（🔴 ``sandbox_session`` **跨 Run 不共享**）。"""
        return ToolContext(
            tenant_id=str(getattr(ctx, "tenant_id", "") or ""),
            workspace_id=getattr(ctx, "workspace_id", None),
            run_id=str(getattr(ctx, "run_id", "") or "") or None,
            agent_id=agent_id,
            workspace_root=self._workspace_root,
            egress_policy=self._egress_policy,
            permission_scope=None,
            # 不携带跨 Run 的 sandbox_session：隔离由 ToolExecutor / SandboxProvider 按需创建。
            sandbox_session=None,
        )


def build_runtime_bridge(**kwargs: Any) -> RuntimeBridgeImpl:
    """构造 :class:`RuntimeBridgeImpl`（组合根入口，参数同其 ``__init__``）。"""
    return RuntimeBridgeImpl(**kwargs)


def _as_error_code(raw: str | None) -> ErrorCode:
    """把工具错误码字面值映射为 :class:`ErrorCode`（未知 → ``INTERNAL_ERROR``）。"""
    if not raw:
        return ErrorCode.INTERNAL_ERROR
    try:
        return ErrorCode(str(raw))
    except ValueError:
        return ErrorCode.INTERNAL_ERROR


#: 显式导出 ``ToolEffect`` 供调用方断言（避免误建判定源时静默放行）。
ALLOW_EFFECT = ToolEffect.ALLOW
