"""MCP 注册表（Server ↔ Tool / Resource / Prompt 目录；设计 §2.4；W2 / T2-11 / T2-12；R11/R14）。

- :class:`MCPRegistry`：内存目录（按 ``server.name`` 注册 Server，缓存能力协商结果与已发现
  Tools）；与 ``SkillRegistry`` / ``ToolRegistry`` 同构的冲突语义
  （``override=False`` → ``CONFLICT``）；
- :meth:`MCPRegistry.sync_to_tool_registry`（**T2-12**）：把「发现目录」（``mcp_tool``）同步进
  「执行注册表」（``tool`` 表 + ``ToolRegistry``）——在 ``tool`` 表登记一条（``source=mcp``、
  ``name=mcp:<server>.<tool>``、``tool_ref=JSON``，R9.2），并构造
  :class:`~astra_tool.adapters.mcp.MCPToolAdapter` 注册进 ``ToolRegistry``（``override=False``，
  内置优先并告警，R10）；
- :func:`build_mcp_registry`：``astra_config.providers._build_optional`` 的工厂入口（R14）。

🔴 本模块**零 Web**（仅标准库 + ``astra_core`` / ``astra_domain`` / ``astra_tool`` +
   本包 ``domain`` / ``protocol``）；**不 import** ``astra_security``（R2）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import TOOL_ACTION_EXECUTE, TOOL_TYPE_MCP, Tool
from astra_tool import (
    ToolMetadata,
    ToolPermissionRequirement,
    ToolRegistry,
    ToolSpec,
)
from astra_tool.adapters.mcp import MCPToolAdapter, MCPToolInvoker

from .domain import MCPServer, MCPTool
from .protocol import MCPCapabilities, MCPToolSpec

__all__ = ["MCPRegistry", "build_mcp_registry"]

_LOGGER = logging.getLogger(__name__)

#: 执行注册表中 MCP Tool 的条目状态。
_TOOL_ROW_STATUS_ACTIVE = "ACTIVE"

#: MCP Tool 的目录分类。
_MCP_TOOL_CATEGORY = "mcp"


class MCPRegistry:
    """MCP Server / Tool 内存目录（已发现工具 + 能力协商缓存）。"""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, list[MCPToolSpec]] = {}
        self._capabilities: dict[str, MCPCapabilities] = {}

    # -- Server -------------------------------------------------------------

    def register_server(self, server: MCPServer, *, override: bool = True) -> None:
        """注册一个 MCP Server（同名冲突见 ``override``）。

        Raises:
            DomainError: ``override=False`` 且同名已注册（``CONFLICT``）。
        """
        if not override and server.name in self._servers:
            raise DomainError(
                f"MCP Server 已注册：{server.name}",
                code=ErrorCode.CONFLICT,
                data={"name": server.name},
            )
        self._servers[server.name] = server

    def unregister_server(self, name: str) -> None:
        """注销 Server 及其工具 / 能力缓存（幂等）。"""
        self._servers.pop(name, None)
        self._tools.pop(name, None)
        self._capabilities.pop(name, None)

    def get_server(self, name: str) -> MCPServer | None:
        """按名取 Server，不存在返回 ``None``。"""
        return self._servers.get(name)

    def servers(self) -> list[MCPServer]:
        """返回全部已注册 Server（按名排序）。"""
        return [self._servers[name] for name in sorted(self._servers)]

    # -- 能力协商缓存 -------------------------------------------------------

    def register_capabilities(self, server_name: str, capabilities: MCPCapabilities) -> None:
        """缓存某 Server 的能力协商结果。"""
        self._capabilities[server_name] = capabilities

    def capabilities(self, server_name: str) -> MCPCapabilities | None:
        """取某 Server 的能力协商结果（未协商返回 ``None``）。"""
        return self._capabilities.get(server_name)

    # -- Tools（发现目录缓存） ---------------------------------------------

    def register_tools(self, server_name: str, tools: list[MCPToolSpec]) -> None:
        """登记某 Server 已发现的 Tools（覆盖旧值）。"""
        self._tools[server_name] = list(tools)

    def tools(self, server_name: str) -> list[MCPToolSpec]:
        """取某 Server 已发现的 Tools（未登记返回空列表）。"""
        return list(self._tools.get(server_name, []))

    def all_tools(self) -> dict[str, list[MCPToolSpec]]:
        """返回全部 Server 的已发现 Tools（按名排序的浅拷贝）。"""
        return {name: list(self._tools[name]) for name in sorted(self._tools)}

    def names(self) -> list[str]:
        """返回全部已注册 Server 名（排序）。"""
        return sorted(self._servers)

    # -- 执行注册表同步（T2-12；R9.2 / R10 / R11 §11.2） -------------------

    def sync_to_tool_registry(
        self,
        tool_registry: ToolRegistry,
        server: MCPServer,
        *,
        tools: Sequence[MCPTool],
        invoker_factory: Callable[[MCPServer, MCPTool], MCPToolInvoker],
        tool_repository: Any = None,
        override: bool = False,
    ) -> list[str]:
        """把已发现（``mcp_tool`` 目录）工具同步进**执行注册表**（``tool`` 表 + ``ToolRegistry``）。

        对每个 :class:`~astra_mcp.domain.MCPTool`：

        1. 命名 ``mcp:<server>.<tool>``（R10）；
        2. 与内置 Tool 同名 → **内置优先**：跳过 + 结构化 ``WARNING``
           （``event=mcp.tool.name_conflict``）；
        3. 在 ``tool`` 表 upsert 一条（``source=mcp``、``tool_ref=JSON``，R9.2；``tool_repository``
           为 ``None`` 时跳过 DB，仅内存注册，``tool_id`` 回退为工具名）；
        4. 构造 :class:`~astra_tool.adapters.mcp.MCPToolAdapter`（``invoker=invoker_factory(...)``）
           并 ``ToolRegistry.register(name, adapter, override=override)``。

        Args:
            tool_registry: Phase 1 ``ToolRegistry``（**零改动**，R11）。
            server: 目标 MCP Server。
            tools: 已发现工具（``MCPDiscovery.discover(...)`` 返回值，含 ``mcp_tool.id`` 溯源）。
            invoker_factory: 构造适配器调用协作者（真实实现落 ``astra_mcp``）。
            tool_repository: 领域 ``ToolRepository``（注入；``None`` = 不落 ``tool`` 表）。
            override: 重名是否覆盖（默认 ``False`` = 内置优先）。

        Returns:
            成功注册进 ``ToolRegistry`` 的工具名列表（``mcp:<server>.<tool>``）。
        """
        registered: list[str] = []
        for tool in tools:
            name = f"mcp:{server.name}.{tool.name}"
            if name in tool_registry.names():
                _log_name_conflict(name=name, tool=tool, server=server)
                continue
            tool_id = name
            if tool_repository is not None:
                tool_id = _upsert_tool_row(tool_repository, server, tool, name)
            adapter = MCPToolAdapter(
                invoker=invoker_factory(server, tool),
                tool_id=tool_id,
                server=server.name,
                tool_name=tool.name,
                spec=_tool_spec_for(server, tool),
            )
            try:
                tool_registry.register(name, adapter, override=override)
            except DomainError as exc:
                if exc.code is ErrorCode.CONFLICT:
                    _log_name_conflict(name=name, tool=tool, server=server)
                    continue
                raise
            registered.append(name)
        return registered

    def __contains__(self, name: object) -> bool:  # noqa: D105
        return isinstance(name, str) and name in self._servers

    def __len__(self) -> int:  # noqa: D105
        return len(self._servers)


def _tool_spec_for(server: MCPServer, tool: MCPTool) -> ToolSpec:
    """由 ``MCPTool`` 构造 ``ToolSpec``（``tool_type=mcp``，``requires_sandbox=False``）。"""
    return ToolSpec(
        metadata=ToolMetadata(
            name=f"mcp:{server.name}.{tool.name}",
            display_name=tool.name,
            description=tool.description or "",
            category=_MCP_TOOL_CATEGORY,
        ),
        input_schema=dict(tool.input_schema),
        output_schema=dict(tool.output_schema),
        permission=ToolPermissionRequirement(action=TOOL_ACTION_EXECUTE),
        requires_sandbox=False,
        tool_type=TOOL_TYPE_MCP,
    )


def _tool_ref_for(server: MCPServer, tool: MCPTool, name: str) -> dict[str, Any]:
    """构造 ``tool.tool_ref``（R9.2）：``{kind,id,server_id,name,version}``。"""
    return {
        "kind": TOOL_TYPE_MCP,
        "id": tool.id,
        "server_id": server.id or tool.mcp_server_id,
        "name": name,
        "version": None,
    }


def _upsert_tool_row(tool_repository: Any, server: MCPServer, tool: MCPTool, name: str) -> str:
    """在 ``tool`` 表 upsert 一条 MCP 工具（``source=mcp`` + ``tool_ref``），返回行 id。"""
    tool_ref = _tool_ref_for(server, tool, name)
    existing = tool_repository.get_by_name(name, tenant_id=server.tenant_id or None)
    if existing is not None:
        existing.display_name = tool.name
        existing.description = tool.description
        existing.category = _MCP_TOOL_CATEGORY
        existing.source = TOOL_TYPE_MCP
        existing.input_schema = dict(tool.input_schema)
        existing.output_schema = dict(tool.output_schema)
        existing.requires_sandbox = False
        existing.status = _TOOL_ROW_STATUS_ACTIVE
        existing.tool_ref = dict(tool_ref)
        updated = tool_repository.update(existing)
        return str(updated.id)
    created = tool_repository.add(
        Tool(
            tenant_id=server.tenant_id or None,
            name=name,
            display_name=tool.name,
            description=tool.description,
            category=_MCP_TOOL_CATEGORY,
            source=TOOL_TYPE_MCP,
            input_schema=dict(tool.input_schema),
            output_schema=dict(tool.output_schema),
            requires_sandbox=False,
            status=_TOOL_ROW_STATUS_ACTIVE,
            tool_ref=dict(tool_ref),
        )
    )
    return str(created.id)


def _log_name_conflict(*, name: str, tool: MCPTool, server: MCPServer) -> None:
    """结构化告警：MCP Tool 与既有（内置）同名 → **内置优先**（R10）。"""
    _LOGGER.warning(
        "mcp.tool.name_conflict builtin_name=%s mcp_tool=%s server=%s",
        name,
        tool.name,
        server.name,
        extra={
            "event": "mcp.tool.name_conflict",
            "builtin_name": name,
            "mcp_tool": tool.name,
            "server": server.name,
        },
    )


def build_mcp_registry(settings: Any) -> MCPRegistry:
    """装配并返回 :class:`MCPRegistry`（``_build_optional`` 工厂入口；R14）。

    目录在**启动 / 发现期**由组合根填充；此处返回**空**注册表（结构就位、装配位可空）。
    """
    return MCPRegistry()
