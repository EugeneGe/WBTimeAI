"""RP-04 · ``MCPExecutor``（MCP 执行预留位；总纲 §12.2 / §5 #14）。

Phase 1 仅提供**完整 Protocol 签名 + 可装配空实现**；``mcp_call.*`` 事件**定义但不产出**；
Phase 2 填充实现时**不得改签名**。

W2 / T2-12 **接线口径**（Erratum-6 / R12）：

- 本文件**保留** :class:`MCPExecutor` Protocol 与 :class:`NullMCPExecutor`（签名**不变**）；
- **真实实现**落 ``astra_mcp.runtime.McpExecutor``（**结构化契合**本 Protocol，**不落
  runtime**），由**组合根**经 ``AgentRuntime.build(...)`` ``mcp_executor=`` 注入（默认
  :class:`NullMCPExecutor`，向后兼容）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import MCPCallRequest, MCPCallResult

__all__ = ["MCPExecutor", "NullMCPExecutor"]


@runtime_checkable
class MCPExecutor(Protocol):
    """MCP 执行器（RP-04）。"""

    def call(self, request: MCPCallRequest) -> MCPCallResult:
        """执行一次 MCP 调用。

        Raises:
            DomainError: 调用失败（``INTERNAL_ERROR``）。
        """
        ...


class NullMCPExecutor:
    """空实现（Phase 1）：返回**失败**结果（安全降级，不抛错）。"""

    def call(self, request: MCPCallRequest) -> MCPCallResult:
        """返回 ``ok=False`` 的失败结果（MCP 未启用）。"""
        return MCPCallResult(ok=False, error="MCP 执行器未启用（Phase 2）")
