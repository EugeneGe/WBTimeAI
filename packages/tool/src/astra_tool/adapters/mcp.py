"""MCP Tool 适配器：把 MCP Tool 呈现为同一 ``Tool`` 接口（W2 / T2-12；裁定 R11）。

设计要点（W2 裁定 R11 / 设计 §2.16「同一 Tool 接口」）：

- :class:`MCPToolInvoker`：**注入**的调用协作者 Protocol（**零** ``astra_mcp`` 依赖）；
  真实实现由 ``astra_mcp`` 侧提供（``astra_mcp.runtime.MCPClientInvoker``），由组合根注入——
  以此**避免** ``tool → mcp`` 反向依赖击穿抽象包（W2 裁定 C2/R2）。
- :class:`MCPInvokeResult`：一次 MCP Tool 调用的结果 DTO。
- :class:`MCPToolAdapter`：实现 Phase 1 :class:`~astra_tool.base.Tool` Protocol
  （``spec`` 属性 + ``execute(args, ctx)``），**不改 ``Tool`` 接口签名**（F4）；
  ``ToolSpec.tool_type = "mcp"``、``requires_sandbox = False``（执行在 MCP Server 侧，
  沙箱语义不适用）。为使 ``ToolExecutor`` 经 ``getattr(tool, "tool_id")`` 读取到溯源标识
  （F6），适配器额外暴露 ``tool_id`` / ``version``。

🔴 本模块属**抽象包**（``astra_tool``）产物：**不得** import ``astra_mcp`` /
   ``astra_security`` / ``astra_database`` / ``sqlalchemy`` / ``alembic`` /
   ``fastapi`` / ``starlette``（受
   ``tests/integration/test_layering.py::test_mcp_adapter_stays_abstraction`` 保护）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError
from astra_domain import TOOL_ACTION_EXECUTE

from ..base import ToolResult, ToolSpec

__all__ = ["MCPInvokeResult", "MCPToolInvoker", "MCPToolAdapter"]


@dataclass(frozen=True)
class MCPInvokeResult:
    """一次 MCP Tool 调用的结果（``MCPToolInvoker`` 的返回值）。

    Attributes:
        ok: 是否成功。
        output: 结构化输出（成功时）。
        error: 错误信息（失败时）。
        error_code: 错误码（``ErrorCode`` 字面值，失败时）。
    """

    ok: bool = True
    output: Any = None
    error: str | None = None
    error_code: str | None = None


@runtime_checkable
class MCPToolInvoker(Protocol):
    """MCP Tool 调用协作者（**注入**；零 ``astra_mcp`` 依赖）。

    真实实现由 ``astra_mcp`` 侧提供（``astra_mcp.runtime.MCPClientInvoker``），组合根注入。
    """

    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> MCPInvokeResult:
        """调用一个 MCP Tool（``tool_name`` 为 Server 内局部名，非 ``mcp:<s>.<t>``）。"""
        ...


class MCPToolAdapter:
    """把**单个** MCP Tool 适配为 Phase 1 ``Tool``（对 Runtime 呈现为同一接口）。

    Args:
        invoker: 调用协作者（真实实现落 ``astra_mcp``，组合根注入）。
        tool_id: ``tool`` 表（执行注册表）中的行标识（供 ``tool_call.tool_id`` 溯源，R9/R-22）。
        server: MCP Server 名（``ToolMetadata.name`` 命名空间部分）。
        tool_name: MCP Tool 在 Server 内的局部名。
        spec: 工具静态描述（``tool_type = "mcp"``，由 ``MCPRegistry`` 构造）。
        version: 溯源版本（可空；供 ``tool_ref.version``）。
    """

    def __init__(
        self,
        *,
        invoker: MCPToolInvoker,
        tool_id: str,
        server: str,
        tool_name: str,
        spec: ToolSpec,
        version: str | None = None,
    ) -> None:
        self._invoker = invoker
        self.tool_id = tool_id
        self.server = server
        self.tool_name = tool_name
        self._spec = spec
        self.version = version

    @property
    def spec(self) -> ToolSpec:
        """工具静态描述（``tool_type = "mcp"``；满足 ``Tool`` Protocol）。"""
        return self._spec

    @property
    def action(self) -> str:
        """默认权限动作（恒 ``EXECUTE``；R11 §11.1）。"""
        return TOOL_ACTION_EXECUTE

    def execute(self, args: Mapping[str, Any], ctx: Any) -> ToolResult:
        """执行一次 MCP Tool 调用（委交注入的 :class:`MCPToolInvoker`）。

        Args:
            args: 入参（透传 MCP Server）。
            ctx: 执行上下文（本适配器**不**使用；权限校验由 Runtime ``ToolExecutor`` 与本
                适配器下游的 ``McpExecutor`` 完成）。

        Returns:
            :class:`~astra_tool.base.ToolResult`（``invoker`` 结果映射）。
        """
        try:
            result = self._invoker.call(self.tool_name, dict(args))
        except DomainError as exc:
            return ToolResult.failure(exc.message, code=str(exc.code))
        if result.ok:
            return ToolResult.success(result.output)
        return ToolResult.failure(
            result.error or "MCP 调用失败",
            code=result.error_code,
        )
