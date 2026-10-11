"""MCP 运行时执行器（``McpExecutor``，承载体 RP-04；W2 / T2-12；裁定 R11 / R12）。

- :class:`McpExecutor`：**结构化契合** runtime ``reserved/mcp_executor.py`` 的
  ``MCPExecutor`` Protocol（``call(request: MCPCallRequest) -> MCPCallResult``，签名**冻结**）；
  编排 ``[权限闸] → MCPClient.call_tool →（出网）Egress.enforce → 事件 + 审计``；
- :class:`MCPClientInvoker`：``astra_tool.adapters.mcp.MCPToolInvoker`` 的**真实实现**，
  把「适配器调用」桥接到 :class:`McpExecutor`（组合根注入）。

**调用链（冻结，R12 §12.2）**：

```
Agent → MCP Tool(适配器) → PermissionChecker.check(ctx, tool, EXECUTE)  # Phase 1，deny-by-default
                          → [Policy 位：PEP/PDP 空实现，占位不改接口]
                          → [Approval 位：预留，本波次不启用]
                          → McpExecutor.call(MCPCallRequest(server, tool_name, arguments))
                              → MCPClient.call_tool(...) →（http/sse）EgressPolicy.enforce(endpoint)
                          → 产出 tool_call + MCPCallStarted/Completed + audit_log
```

🔴 **禁止** ``Agent → MCP Tool → Execute``（设计 §2.4）：执行前必经 ``PermissionChecker``。
   本执行器在组合根注入 ``permission_checker`` 时对**直接**经 RP-04 调用的路径做**防御纵深**兜底
   （runtime 侧 ``ToolExecutor`` 已逐次校验；二者口径一致，deny-by-default）。
🔴 事件经注入 ``on_event`` 回调落 ``agent_event``（``mcp_call.started`` / ``mcp_call.completed``）；
   审计经注入域 Protocol ``AuditRepository``（**明文不入审计**，C-07）。
🔴 本模块**零 Web**；**不 import** ``astra_security``（凭证明文经注入 ``CredentialDecoder``，R2）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from astra_core import DomainError, generate_id
from astra_domain import (
    AUDIT_OUTCOME_DENIED,
    AUDIT_OUTCOME_FAILED,
    AUDIT_OUTCOME_SUCCESS,
    TOOL_ACTION_EXECUTE,
    AuditLog,
    AuditRepository,
    EgressPolicy,
    MCPCallRequest,
    MCPCallResult,
    ToolEffect,
)
from astra_tool import (
    ToolContext,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolSpec,
)
from astra_tool.adapters.mcp import MCPInvokeResult

from .client import MCPClient

__all__ = ["McpExecutor", "MCPClientInvoker"]

_MCP_CALL_ACTION = "mcp.call"


def _elapsed_ms(start: float) -> int:
    """返回自 ``start``（``perf_counter``）以来的毫秒数。"""
    return int((time.perf_counter() - start) * 1000)


class _MCPToolProxy:
    """最小 ``Tool`` 桩（仅供 ``PermissionChecker`` 按名判定；零副作用）。"""

    def __init__(self, name: str) -> None:
        self.spec = ToolSpec(
            metadata=ToolMetadata(name=name),
            permission=ToolPermissionRequirement(action=TOOL_ACTION_EXECUTE),
        )

    def execute(self, args: Mapping[str, Any], ctx: Any) -> Any:  # pragma: no cover - 占位
        """占位实现（权限判定不触达 ``execute``）。"""
        raise NotImplementedError("_MCPToolProxy 仅用于权限判定")


class McpExecutor:
    """MCP 执行器（RP-04 承载体；编排权限 / 执行 / 事件 / 审计）。

    Args:
        client: MCP 协议客户端（``MCPClient``；http/sse 建连前已过 ``EgressPolicy``，R8）。
        permission_checker: 运行期权限校验器（缺省 ``None`` = 不做本层兜底，仅依赖 runtime 侧
            ``ToolExecutor`` 的逐次校验）。注入后对**直接**经 RP-04 的调用做 deny-by-default 兜底。
        egress: 出网策略（**装配保真形参**，R12）。实际 ``endpoint`` 校验在 ``MCPClient`` 建连前
            完成（``_build_transport`` → ``EgressPolicy.enforce``）；此处保留以供组合根装配与断言。
        on_event: 事件回调 ``(event_name, payload)``（把 ``mcp_call.*`` 落 ``agent_event``）。
        audit: 审计仓储（域 Protocol ``AuditRepository``）；**明文不入审计**（C-07）。
        run_id / tenant_id / workspace_id / agent_id: 事件 / 审计归属（缺省空）。
    """

    def __init__(
        self,
        *,
        client: MCPClient,
        permission_checker: Any = None,
        egress: EgressPolicy | None = None,
        on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
        audit: AuditRepository | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self._client = client
        self._checker = permission_checker
        self._egress = egress
        self._on_event = on_event
        self._audit_repo = audit
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._agent_id = agent_id

    # -- 契约方法（RP-04；签名冻结） ----------------------------------------

    def call(self, request: MCPCallRequest) -> MCPCallResult:
        """执行一次 MCP 调用（权限闸 → 调用 → 事件 + 审计）。

        Args:
            request: MCP 调用请求（``server`` / ``tool_name`` / ``arguments``）。

        Returns:
            :class:`~astra_domain.MCPCallResult`（失败转 ``ok=False``，不抛）。
        """
        tool_ref = f"mcp:{request.server}.{request.tool_name}"
        call_id = generate_id()
        started = time.perf_counter()
        self._emit(
            "mcp_call.started",
            {
                "run_id": self._run_id,
                "mcp_call_id": call_id,
                "server": request.server,
                "tool_name": request.tool_name,
            },
        )

        # 权限闸（防御纵深，deny-by-default）：对直接经 RP-04 的调用兜底。
        if self._checker is not None:
            effect = self._checker.check(
                self._tool_context(), _MCPToolProxy(tool_ref), TOOL_ACTION_EXECUTE
            )
            if effect is not ToolEffect.ALLOW:
                duration_ms = _elapsed_ms(started)
                self._emit_completed(
                    call_id, request, status="DENIED", duration_ms=duration_ms, error="权限拒绝"
                )
                self._record_audit(
                    call_id,
                    request,
                    outcome=AUDIT_OUTCOME_DENIED,
                    duration_ms=duration_ms,
                    error="权限拒绝",
                )
                return MCPCallResult(ok=False, error="权限拒绝")

        try:
            result = self._client.call_tool(request.tool_name, request.arguments)
        except DomainError as exc:
            duration_ms = _elapsed_ms(started)
            self._emit_completed(
                call_id, request, status="FAILED", duration_ms=duration_ms, error=exc.message
            )
            self._record_audit(
                call_id,
                request,
                outcome=AUDIT_OUTCOME_FAILED,
                duration_ms=duration_ms,
                error=exc.message,
            )
            return MCPCallResult(ok=False, error=exc.message)

        duration_ms = _elapsed_ms(started)
        self._emit_completed(
            call_id,
            request,
            status="SUCCESS" if result.ok else "FAILED",
            duration_ms=duration_ms,
            error=result.error,
        )
        self._record_audit(
            call_id,
            request,
            outcome=AUDIT_OUTCOME_SUCCESS if result.ok else AUDIT_OUTCOME_FAILED,
            duration_ms=duration_ms,
            error=result.error,
        )
        return result

    # -- 内部 ---------------------------------------------------------------

    def _tool_context(self) -> ToolContext:
        """构造权限判定用 ``ToolContext``（deny-by-default 判定仅依赖 ``(tool_name, action)``）。"""
        return ToolContext(
            tenant_id=self._tenant_id or "",
            workspace_id=self._workspace_id,
            run_id=self._run_id,
            agent_id=self._agent_id,
        )

    def _emit(self, event_name: str, payload: Mapping[str, Any]) -> None:
        """经注入回调发事件（未注入则静默）。"""
        if self._on_event is not None:
            self._on_event(event_name, payload)

    def _emit_completed(
        self,
        call_id: str,
        request: MCPCallRequest,
        *,
        status: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        """发 ``mcp_call.completed`` 事件。"""
        self._emit(
            "mcp_call.completed",
            {
                "run_id": self._run_id,
                "mcp_call_id": call_id,
                "server": request.server,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
            },
        )

    def _record_audit(
        self,
        call_id: str,
        request: MCPCallRequest,
        *,
        outcome: str,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        """经注入 ``AuditRepository`` 落一条 ``mcp.call`` 审计（**明文不入审计**，C-07）。"""
        if self._audit_repo is None:
            return
        record = AuditLog(
            workspace_id=self._workspace_id,
            agent_id=self._agent_id,
            run_id=self._run_id,
            action=_MCP_CALL_ACTION,
            resource_type="mcp_tool",
            resource_id=f"mcp:{request.server}.{request.tool_name}",
            outcome=outcome,
            duration_ms=duration_ms,
            request_id=call_id,
            metadata={
                "server": request.server,
                "tool": request.tool_name,
                "error": error,
            },
        )
        self._audit_repo.add(record)


class MCPClientInvoker:
    """``MCPToolInvoker`` 的真实实现（桥接适配器调用 → :class:`McpExecutor`）。

    Args:
        server: MCP Server 名（该 invoker 归属的 Server）。
        executor: RP-04 执行器（``McpExecutor``）。
    """

    def __init__(self, *, server: str, executor: McpExecutor) -> None:
        self._server = server
        self._executor = executor

    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> MCPInvokeResult:
        """调用一个 MCP Tool（构造 ``MCPCallRequest`` 后经执行器编排）。"""
        result = self._executor.call(
            MCPCallRequest(
                server=self._server,
                tool_name=tool_name,
                arguments=dict(arguments),
            )
        )
        return MCPInvokeResult(ok=result.ok, output=result.output, error=result.error)
