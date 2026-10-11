"""``astra_tool.adapters``：把外部能力（如 MCP）适配为 Phase 1 ``Tool`` 的适配器包。

🔴 适配器**必须**保持「抽象包」不变量：**不得** import ``astra_mcp`` / ``astra_security`` /
   ``astra_database`` / ``sqlalchemy`` / ``alembic`` / ``fastapi`` / ``starlette``
   （受 ``tests/integration/test_layering.py::test_mcp_adapter_stays_abstraction`` 保护，
   W2 裁定 R1 / R11）。
"""

from __future__ import annotations

from .mcp import MCPInvokeResult, MCPToolAdapter, MCPToolInvoker

__all__ = ["MCPInvokeResult", "MCPToolAdapter", "MCPToolInvoker"]
