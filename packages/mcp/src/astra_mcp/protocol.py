"""MCP JSON-RPC 2.0 编解码 + 冻结 DTO（设计 §2.4；W2 / T2-11；裁定 R7 / R8）。

- :data:`JSONRPC_VERSION` / MCP 方法名常量（``initialize`` / ``tools/list`` / ``tools/call``）；
- :func:`latest_protocol_version`：**函数级延迟导入**官方 ``mcp`` SDK 的
  ``LATEST_PROTOCOL_VERSION``（R7：``mcp`` 为可选 extra，模块级不 import，保
  ``astra_mcp`` 无 SDK 可导入）；SDK 缺失时回落 :data:`PROTOCOL_VERSION_FALLBACK`；
- 冻结 DTO：:class:`MCPCapabilities` / :class:`MCPToolSpec`（R8）；
- 编解码原语：:func:`build_request` / :func:`build_notification` / :func:`dumps` /
  :func:`loads` / :func:`result_of`；错误层级 :class:`MCPError` 家族。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core``）。MCP 方法语义遵循**官方 MCP 规范**
   的 JSON-RPC 消息形状（**不自造协议**）；重依赖（SDK）委交可选 extra。
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

__all__ = [
    "JSONRPC_VERSION",
    "METHOD_INITIALIZE",
    "METHOD_INITIALIZED",
    "METHOD_TOOLS_LIST",
    "METHOD_TOOLS_CALL",
    "PROTOCOL_VERSION_FALLBACK",
    "CLIENT_NAME",
    "latest_protocol_version",
    "MCPError",
    "MCPProtocolError",
    "MCPTransportError",
    "MCPTimeoutError",
    "MCPCapabilities",
    "MCPToolSpec",
    "build_request",
    "build_notification",
    "dumps",
    "loads",
    "result_of",
]

#: JSON-RPC 版本。
JSONRPC_VERSION = "2.0"

#: MCP 方法名（现行规范）。
METHOD_INITIALIZE = "initialize"
METHOD_INITIALIZED = "notifications/initialized"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"

#: SDK 缺失时的协议版本回落（与 SDK 1.x 一致的稳定版本）。
PROTOCOL_VERSION_FALLBACK = "2024-11-05"

#: 客户端标识（``initialize.clientInfo.name``）。
CLIENT_NAME = "astra-ai"


def latest_protocol_version() -> str:
    """返回 MCP 协议版本（优先官方 SDK，**函数级延迟导入**；缺失时回落常量）。"""
    try:
        module = importlib.import_module("mcp.types")
    except ImportError:
        return PROTOCOL_VERSION_FALLBACK
    return str(getattr(module, "LATEST_PROTOCOL_VERSION", PROTOCOL_VERSION_FALLBACK))


# -- 错误层级 ---------------------------------------------------------------


class MCPError(DomainError):
    """MCP 错误基类（默认 ``INTERNAL_ERROR``）。"""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR


class MCPProtocolError(MCPError):
    """MCP 协议错误（编解码 / 远端 ``error`` 字段）。"""

    code: ErrorCode = ErrorCode.VALIDATION_ERROR


class MCPTransportError(MCPError):
    """MCP 传输错误（连接断开 / 子进程异常 / HTTP 失败）。"""

    code: ErrorCode = ErrorCode.CONFIGURATION_ERROR


class MCPTimeoutError(MCPTransportError):
    """MCP 超时错误（**不重试**，快速失败，防 hang）。"""

    code: ErrorCode = ErrorCode.TOOL_TIMEOUT


# -- 冻结 DTO（R8） ---------------------------------------------------------


@dataclass(frozen=True)
class MCPCapabilities:
    """MCP 握手 / 能力协商结果（``initialize`` 结果）。

    Attributes:
        protocol_version: 协商后的协议版本（非空）。
        tools: 是否提供 Tools 能力。
        resources: 是否提供 Resources 能力。
        prompts: 是否提供 Prompts 能力。
        server_info: Server 标识（``{name, version}``）。
    """

    protocol_version: str = PROTOCOL_VERSION_FALLBACK
    tools: bool = False
    resources: bool = False
    prompts: bool = False
    server_info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> MCPCapabilities:
        """由 ``initialize`` 结果构造（缺省字段取保守值）。"""
        capabilities = dict(result.get("capabilities") or {})
        return cls(
            protocol_version=str(result.get("protocolVersion") or PROTOCOL_VERSION_FALLBACK),
            tools="tools" in capabilities,
            resources="resources" in capabilities,
            prompts="prompts" in capabilities,
            server_info=dict(result.get("serverInfo") or {}),
        )


@dataclass(frozen=True)
class MCPToolSpec:
    """MCP Tool 规格（``tools/list`` 条目；R8）。

    Attributes:
        name: Tool 名（Server 内唯一）。
        description: 描述。
        input_schema: 输入 JSON Schema。
        output_schema: 输出 JSON Schema（MCP 无标准字段时为 ``{}``）。
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> MCPToolSpec:
        """由 ``tools/list`` 条目构造。"""
        return cls(
            name=str(raw.get("name", "")),
            description=str(raw.get("description") or ""),
            input_schema=dict(raw.get("inputSchema") or {}),
            output_schema=dict(raw.get("outputSchema") or {}),
        )


# -- 编解码原语 -------------------------------------------------------------


def build_request(
    request_id: int | str, method: str, params: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """构造 JSON-RPC 请求对象。"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
        "params": dict(params or {}),
    }


def build_notification(method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """构造 JSON-RPC 通知对象（无 ``id``）。"""
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": dict(params or {})}


def dumps(message: Mapping[str, Any]) -> str:
    """序列化为单行 JSON（ASCII 安全）。"""
    return json.dumps(dict(message), ensure_ascii=False, separators=(",", ":"))


def loads(raw: str | bytes) -> dict[str, Any]:
    """反序列化 JSON 文本。

    Raises:
        MCPProtocolError: 非法 JSON / 非对象。
    """
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MCPProtocolError("MCP 消息非法 JSON", data={"raw": str(raw)[:200]}) from exc
    if not isinstance(message, dict):
        raise MCPProtocolError("MCP 消息须为 JSON 对象", data={"type": type(message).__name__})
    return message


def result_of(message: Mapping[str, Any]) -> Any:
    """从 JSON-RPC 响应中提取 ``result``；含 ``error`` 时抛 :class:`MCPProtocolError`。"""
    error = message.get("error")
    if error is not None:
        detail = dict(error) if isinstance(error, Mapping) else {"message": str(error)}
        raise MCPProtocolError("MCP 远端返回错误", data=detail)
    return message.get("result")
