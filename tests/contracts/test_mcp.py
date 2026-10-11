"""MCP 契约套件（``C-P2-03`` / ``C-P2-24`` / DoD D12；W2 / T2-11；裁定 R8 / R15.3）。

对**自研 mock MCP Server**（:mod:`tests.contracts.mock_mcp_server`，零第三方依赖）跑
**stdio 与 sse 同一套断言**（参数化）：握手 / 能力协商、``tools/list`` 发现、
``tools/call`` 调用、超时（不 hang）、重连（重试 / 干净失败）、``endpoint`` 过
``EgressPolicy``、``MCPDiscovery`` 落 ``mcp_tool``。

**抽象纪律**（R15.3 #9）：本文件**不 import ``astra_security``**；由
:func:`test_astra_mcp_does_not_import_security` 静态兜底。
"""

from __future__ import annotations

import ast
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import MCPCallResult, ToolPermission
from astra_mcp import (
    DefaultMCPClient,
    MCPCapabilities,
    MCPDiscovery,
    MCPServer,
    MCPToolSpec,
    MCPTransportError,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
    build_mcp_client,
    latest_protocol_version,
)
from astra_sandbox import SubprocessProcessSpawner
from astra_tool import (
    PermissionChecker,
    ToolContext,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolSpec,
)

from .mock_mcp_server import start_sse_server

pytestmark = pytest.mark.contracts

MOCK_MODULE = Path(__file__).resolve().parent / "mock_mcp_server.py"
MCP_PKG_ROOT = Path(__file__).resolve().parents[2] / "packages" / "mcp" / "src" / "astra_mcp"


# -- 测试支撑 ----------------------------------------------------------------


class _AllowLoopbackEgress:
    """放行出网（返回钉定 IP ``127.0.0.1``）并记录被校验的 URL。"""

    def __init__(self, pinned_ip: str = "127.0.0.1") -> None:
        self.pinned_ip = pinned_ip
        self.seen: list[str] = []

    def authorize(self, url: str, **_: Any) -> Any:
        from astra_domain import EgressDecision

        return EgressDecision(True, ErrorCode.UNKNOWN, "allow", url, resolved_ip=self.pinned_ip)

    def authorize_redirect(self, *, from_url: str, location: str, **_: Any) -> Any:
        return self.authorize(location)

    def enforce(self, url: str, **_: Any) -> str:
        self.seen.append(url)
        return self.pinned_ip


class _DenyEgress:
    """拒绝全部出网（``enforce`` → ``DomainError(PERMISSION_DENIED)``）。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def authorize(self, url: str, **_: Any) -> Any:
        return None

    def authorize_redirect(self, *, from_url: str, location: str, **_: Any) -> Any:
        return None

    def enforce(self, url: str, **_: Any) -> str:
        self.seen.append(url)
        raise DomainError("出网被拒", code=ErrorCode.PERMISSION_DENIED, data={"url": url})


class _McpNs:
    """``settings.mcp`` 命名空间桩。"""

    def __init__(self, *, connect: float = 10.0, read: float = 30.0, retries: int = 2) -> None:
        self.connect_timeout_seconds = connect
        self.read_timeout_seconds = read
        self.max_retries = retries


class _Settings:
    """``Settings`` 桩（仅 ``mcp`` 段）。"""

    def __init__(self, *, read: float = 30.0, retries: int = 2) -> None:
        self.mcp = _McpNs(read=read, retries=retries)


def _stdio_server() -> MCPServer:
    return MCPServer(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=[str(MOCK_MODULE), "--stdio"],
    )


@pytest.fixture(params=["stdio", "sse"])
def mcp_client(request: pytest.FixtureRequest):  # noqa: ANN201
    """参数化（stdio / sse）装配一个已连接的 MCPClient。"""
    if request.param == "stdio":
        server = _stdio_server()
        client = build_mcp_client(server, spawner=SubprocessProcessSpawner())
        try:
            yield server, client, None
        finally:
            client.close()
    else:
        mock, url = start_sse_server()
        server = MCPServer(name="mock", transport="sse", endpoint=url)
        egress = _AllowLoopbackEgress()
        client = build_mcp_client(server, egress=egress)
        try:
            yield server, client, egress
        finally:
            client.close()
            mock.shutdown()
            mock.server_close()


# -- ① 握手 / 能力协商 -------------------------------------------------------


def test_initialize_handshake(mcp_client) -> None:  # noqa: ANN001
    """``initialize()`` 返回 :class:`MCPCapabilities`，``protocol_version`` 非空。"""
    _server, client, _egress = mcp_client
    capabilities = client.initialize()
    assert isinstance(capabilities, MCPCapabilities)
    assert capabilities.protocol_version
    assert capabilities.tools is True


# -- ② 发现（tools/list） ----------------------------------------------------


def test_list_tools_returns_specs(mcp_client) -> None:  # noqa: ANN001
    """``tools/list()`` 返回 :class:`MCPToolSpec` 列表（含 ``echo`` / ``add``）。"""
    _server, client, _egress = mcp_client
    client.initialize()
    tools = client.list_tools()
    assert all(isinstance(tool, MCPToolSpec) for tool in tools)
    names = {tool.name for tool in tools}
    assert {"echo", "add"} <= names
    echo = next(tool for tool in tools if tool.name == "echo")
    assert echo.input_schema.get("type") == "object"


# -- ③ 调用（tools/call） ----------------------------------------------------


def test_call_tool_ok(mcp_client) -> None:  # noqa: ANN001
    """``call_tool()`` 返回 ``MCPCallResult(ok=True)`` 且输出含回显标记。"""
    _server, client, _egress = mcp_client
    client.initialize()
    result = client.call_tool("echo", {"text": "hi"})
    assert isinstance(result, MCPCallResult)
    assert result.ok is True
    assert "echo:echo" in json.dumps(result.output, ensure_ascii=False)


# -- ④ 权限拒绝（deny-by-default；复用 Phase 1 PermissionChecker） ------------


class _StubMCPTool:
    """最小 MCP Tool 桩（仅 ``spec``；供权限判定用）。"""

    def __init__(self) -> None:
        self.spec = ToolSpec(
            metadata=ToolMetadata(name="mcp:mock.echo", display_name="echo"),
            permission=ToolPermissionRequirement(action="EXECUTE"),
        )

    def execute(self, args: Mapping[str, Any], ctx: Any) -> Any:  # noqa: ANN401
        raise NotImplementedError


def test_permission_denied_by_default() -> None:
    """未授权 → ``PermissionChecker.check`` 返 ``DENY``；显式 ``ALLOW`` → 放行。"""
    tool = _StubMCPTool()
    deny = PermissionChecker()
    assert deny.check(ToolContext(), tool, "EXECUTE").value != "ALLOW"

    allow = PermissionChecker(
        permissions=[ToolPermission(tool_id="mcp:mock.echo", action="EXECUTE", effect="ALLOW")]
    )
    assert allow.check(ToolContext(), tool, "EXECUTE").value == "ALLOW"


# -- ⑤ 超时（不 hang） -------------------------------------------------------


def test_call_tool_timeout_does_not_hang() -> None:
    """mock server 延迟 > ``read_timeout`` → 快速失败（不 hang）。"""
    mock, url = start_sse_server(delay_s=1.0)
    server = MCPServer(name="slow", transport="sse", endpoint=url)
    client = build_mcp_client(
        server, egress=_AllowLoopbackEgress(), settings=_Settings(read=0.2, retries=0)
    )
    try:
        started = time.monotonic()
        result = client.call_tool("echo", {"text": "hi"}, timeout_s=0.2)
        elapsed = time.monotonic() - started
        assert result.ok is False
        assert elapsed < 1.0
    finally:
        client.close()
        mock.shutdown()
        mock.server_close()


# -- ⑥ 重连（重试 / 干净失败） -----------------------------------------------


class _FlakyTransport:
    """前 ``failures`` 次 ``request`` 抛传输错误，之后成功。"""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.opened = 0
        self.closed = 0

    def open(self, *, timeout_s: float | None = None) -> None:
        self.opened += 1

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        if self.failures > 0:
            self.failures -= 1
            raise MCPTransportError("connection dropped")
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "echo", "inputSchema": {}, "outputSchema": {}}]},
        }

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        return None

    def close(self) -> None:
        self.closed += 1


def test_retry_on_transport_error_reopens() -> None:
    """连接错误 → 按 ``max_retries`` 重开传输并重试（最终成功）。"""
    transport = _FlakyTransport(failures=2)
    client = DefaultMCPClient(transport=transport, max_retries=3, backoff_s=0.0)
    tools = client.list_tools()
    assert [tool.name for tool in tools] == ["echo"]
    assert transport.opened >= 2
    assert transport.closed >= 1


def test_clean_fail_without_retry_budget() -> None:
    """``max_retries=0`` + 恒失败 → 干净失败（抛传输错误，不泄漏）。"""
    transport = _FlakyTransport(failures=99)
    client = DefaultMCPClient(transport=transport, max_retries=0, backoff_s=0.0)
    with pytest.raises(MCPTransportError):
        client.list_tools()
    assert transport.closed >= 1


# -- ⑦ EgressPolicy（endpoint 建连前过 enforce） -----------------------------


def test_endpoint_passes_egress_for_network_transport() -> None:
    """``sse``/``http`` 传输：``endpoint`` 建连前过 ``EgressPolicy.enforce``（记录即证）。"""
    mock, url = start_sse_server()
    egress = _AllowLoopbackEgress()
    server = MCPServer(name="mock", transport="sse", endpoint=url)
    client = build_mcp_client(server, egress=egress)
    try:
        client.initialize()
        assert egress.seen == [url]
    finally:
        client.close()
        mock.shutdown()
        mock.server_close()


def test_denied_endpoint_raises_permission_denied() -> None:
    """被拒 ``endpoint`` → ``DomainError(PERMISSION_DENIED)``。"""
    server = MCPServer(name="blocked", transport="sse", endpoint="http://169.254.169.254/mcp")
    with pytest.raises(DomainError) as excinfo:
        build_mcp_client(server, egress=_DenyEgress())
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_network_transport_requires_egress() -> None:
    """出网传输缺 ``EgressPolicy`` → ``DomainError(CONFIGURATION_ERROR)``。"""
    server = MCPServer(name="no-egress", transport="http", endpoint="https://mcp.example.com")
    with pytest.raises(DomainError) as excinfo:
        build_mcp_client(server, egress=None)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


# -- ⑧ MCPDiscovery 落 mcp_tool ---------------------------------------------


def test_discovery_persists_to_mcp_tool(tmp_path: Path) -> None:
    """``MCPDiscovery.discover`` → ``tools/list`` 结果落 ``mcp_tool``（发现目录）。"""
    from tests.unit.runtime_stubs import build_session_factory

    factory, engine = build_session_factory(tmp_path / "mcp_discovery.db")
    try:
        servers = SqlMCPServerRepository(factory)
        tools = SqlMCPToolRepository(factory)
        server = servers.add(_stdio_server())
        client = build_mcp_client(server, spawner=SubprocessProcessSpawner())
        try:
            client.initialize()
            discovered = MCPDiscovery(tool_repository=tools).discover(server, client)
            assert {"echo", "add"} <= {tool.name for tool in discovered}
            persisted = tools.list_by_server(server.id)
            assert {row.name for row in persisted} == {tool.name for tool in discovered}
        finally:
            client.close()
    finally:
        engine.dispose()


# -- ⑨ 抽象纪律 / 零第三方依赖 / SDK 可选 ------------------------------------


def _module_imports(path: Path) -> set[str]:
    """收集某 Python 文件的顶层导入模块名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_astra_mcp_does_not_import_security() -> None:
    """``astra_mcp`` **不** import ``astra_security``（R2：明文经注入 ``CredentialDecoder``）。

    以**实际导入解析**（``ast``）为准——文中提及 ``astra_security`` 的**文档注释**不算导入。
    """
    offenders: list[str] = []
    for path in MCP_PKG_ROOT.rglob("*.py"):
        if "astra_security" in _module_imports(path):
            offenders.append(str(path.relative_to(MCP_PKG_ROOT)))
    assert not offenders, offenders


def test_mock_server_has_no_third_party_deps() -> None:
    """``mock_mcp_server.py`` **零第三方依赖**（仅标准库）。"""
    modules = _module_imports(MOCK_MODULE)
    third_party = {name for name in modules if name not in sys.stdlib_module_names}
    assert not third_party, third_party


def test_protocol_version_available_without_sdk() -> None:
    """无 SDK 时 :func:`latest_protocol_version` 回落非空常量（保 ``astra_mcp`` 可导入）。"""
    assert latest_protocol_version()


def test_protocol_version_from_sdk_when_available() -> None:
    """SDK 可用时取官方 ``LATEST_PROTOCOL_VERSION``（缺失则 skip，R7 兜底）。"""
    mcp_types = pytest.importorskip("mcp.types")
    assert latest_protocol_version() == str(mcp_types.LATEST_PROTOCOL_VERSION)
