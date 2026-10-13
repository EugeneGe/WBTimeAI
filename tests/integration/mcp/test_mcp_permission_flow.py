"""MCP 权限闭环集成测试（W2 / T2-12；裁定 R11 / R12 / R15.4）。

**验收口径**（T2-12 / R15.4）：

1. Runtime **不区分**内置 Tool 与 MCP Tool——同经 ``ToolExecutor.execute`` 路径（``I-P2-04``）；
2. 未授权调用 → ``tool_call.status=DENIED`` **且** ``tool_type="mcp"``；
3. ``MCPCallStarted`` / ``MCPCallCompleted`` 落 ``agent_event``（经注入回调），**可回放**；
4. 每次（真正执行的）调用产 ``audit_log``（经注入 ``AuditRepository``）；
5. ``adapter.execute`` 满足 ``Tool`` Protocol（``isinstance(adapter, Tool)``）；
6. ``endpoint`` 过 ``EgressPolicy``：拒段 ``endpoint`` → ``DomainError(PERMISSION_DENIED)``。

**抽象纪律**：本文件**不 import ``astra_security``**。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import SqlToolRepository
from astra_domain import (
    TOOL_CALL_STATUS_DENIED,
    AuditLog,
    MCPCallResult,
    ToolPermission,
)
from astra_mcp import (
    MCPClientInvoker,
    MCPDiscovery,
    McpExecutor,
    MCPRegistry,
    MCPServer,
    MCPToolSpec,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
    build_mcp_client,
)
from astra_runtime import RuntimePermissionChecker, ToolCallRequest, ToolExecutor
from astra_tool import (
    PermissionChecker,
    Tool,
    ToolContext,
    ToolRegistry,
)

from tests.unit.runtime_stubs import EchoTool, build_session_factory

MCP_TOOL_NAME = "mcp:mock.echo"


# -- 支撑桩件 ----------------------------------------------------------------


class _FakeMCPClient:
    """最小 ``MCPClient`` 桩（确定性；实现 R8 冻结契约）。"""

    def __init__(
        self,
        *,
        specs: Sequence[MCPToolSpec],
        output: Any = None,
        error: str | None = None,
    ) -> None:
        self._specs = list(specs)
        self._output = (
            output if output is not None else {"content": [{"type": "text", "text": "ok"}]}
        )
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0

    def initialize(self) -> Any:  # noqa: ANN401 - 返回 MCPCapabilities
        from astra_mcp import MCPCapabilities

        return MCPCapabilities(protocol_version="2024-11-05", tools=True)

    def list_tools(self) -> list[MCPToolSpec]:
        """返回预置 Tool 规格。"""
        return list(self._specs)

    def call_tool(
        self, name: str, arguments: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> MCPCallResult:
        """记录调用并返回预置结果。"""
        self.calls.append((name, dict(arguments)))
        if self._error is not None:
            return MCPCallResult(ok=False, error=self._error)
        return MCPCallResult(ok=True, output=self._output)

    def close(self) -> None:
        """关闭计数。"""
        self.closed += 1


class _RecordingAuditRepository:
    """记录审计写入的 ``AuditRepository`` 桩（实现域 Protocol）。"""

    def __init__(self) -> None:
        self.records: list[AuditLog] = []

    def add(self, record: AuditLog) -> AuditLog:
        """记录并返回。"""
        self.records.append(record)
        return record

    def exists_request_id(self, request_id: str) -> bool:
        """按 ``request_id`` 去重判定。"""
        return any(record.request_id == request_id for record in self.records)

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditLog]:
        """返回全部记录（桩：无租户过滤）。"""
        return list(self.records)[:limit]


class _EventRecorder:
    """记录 ``(event_name, payload)`` 的事件回调。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_name: str, payload: Mapping[str, Any]) -> None:
        self.events.append((event_name, dict(payload)))

    def names(self) -> list[str]:
        """返回事件名序列。"""
        return [name for name, _ in self.events]


class _DenyEgress:
    """拒绝全部出网的 ``EgressPolicy`` 桩。"""

    def authorize(self, url: str, **_: Any) -> Any:  # noqa: ANN401
        return None

    def authorize_redirect(self, *, from_url: str, location: str, **_: Any) -> Any:  # noqa: ANN401
        return None

    def enforce(self, url: str, **_: Any) -> str:
        raise DomainError("出网被拒", code=ErrorCode.PERMISSION_DENIED, data={"url": url})


class _Stack:
    """一套已装配的 MCP 执行栈（供断言）。"""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


# -- 装配辅助 ----------------------------------------------------------------


def _build_stack(
    factory: Any,  # noqa: ANN401
    *,
    permissions: Sequence[ToolPermission] | None,
    client: _FakeMCPClient,
    record_events: bool = True,
) -> _Stack:
    """装配 MCP Server → 发现 → 同步 → ``ToolExecutor``（含权限 + 事件 + 审计）。"""
    server_repository = SqlMCPServerRepository(factory)
    mcp_tool_repository = SqlMCPToolRepository(factory)
    tool_repository = SqlToolRepository(factory)
    tool_registry = ToolRegistry()

    server = server_repository.add(
        MCPServer(name="mock", transport="stdio", command="python", status="ACTIVE")
    )
    discovered = MCPDiscovery(tool_repository=mcp_tool_repository).discover(server, client)

    checker = PermissionChecker(permissions=list(permissions or ()))
    events = _EventRecorder() if record_events else None
    audit = _RecordingAuditRepository()
    executor = McpExecutor(
        client=client,
        permission_checker=checker,
        on_event=events,
        audit=audit,
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="ws-1",
        agent_id="agent-1",
    )
    registry = MCPRegistry()
    registered = registry.sync_to_tool_registry(
        tool_registry,
        server,
        tools=discovered,
        invoker_factory=lambda srv, tool: MCPClientInvoker(server=srv.name, executor=executor),
        tool_repository=tool_repository,
    )
    tool_executor = ToolExecutor(
        tool_registry=tool_registry,
        permission_checker=RuntimePermissionChecker(checker),
    )
    return _Stack(
        server=server,
        discovered=discovered,
        tool_registry=tool_registry,
        tool_repository=tool_repository,
        registered=registered,
        executor=executor,
        audit=audit,
        events=events,
        tool_executor=tool_executor,
    )


def _allow(name: str = MCP_TOOL_NAME, *, action: str = "EXECUTE") -> ToolPermission:
    """构造一条放行规则。"""
    return ToolPermission(tool_id=name, action=action, effect="ALLOW")


def _specs() -> list[MCPToolSpec]:
    """两个可发现的 MCP Tool（``echo`` / ``add``）。"""
    return [
        MCPToolSpec(name="echo", description="回显", input_schema={"type": "object"}),
        MCPToolSpec(name="add", description="求和", input_schema={"type": "object"}),
    ]


# -- ① Runtime 不区分内置 / MCP（同一 ToolExecutor 路径） ----------------------


def test_runtime_treats_mcp_like_builtin(tmp_path: Path) -> None:
    """① MCP 适配器与内置 Tool 同经 ``ToolExecutor.execute``（同一路径）。"""
    factory, engine = build_session_factory(tmp_path / "mcp_unified.db")
    try:
        client = _FakeMCPClient(specs=_specs())
        stack = _build_stack(factory, permissions=[_allow()], client=client)
        stack.tool_registry.register("echo-builtin", EchoTool(name="echo-builtin"))

        ctx = ToolContext(tenant_id="tenant-1", run_id="run-1", agent_id="agent-1")
        # MCP Tool：经适配器（tool_type=mcp）执行。
        mcp_result = stack.tool_executor.execute(
            ToolCallRequest(name=MCP_TOOL_NAME, arguments={"text": "hi"}), ctx=ctx
        )
        assert mcp_result.ok is True
        assert mcp_result.tool_type == "mcp"
        assert client.calls == [("echo", {"text": "hi"})]

        # 内置 Tool：同经 ``ToolExecutor.execute``（无 MCP 分支）；deny-by-default → 被拒。
        builtin_result = stack.tool_executor.execute(
            ToolCallRequest(name="echo-builtin", arguments={}), ctx=ctx
        )
        assert builtin_result.status == TOOL_CALL_STATUS_DENIED
        assert builtin_result.tool_type == "builtin"
    finally:
        engine.dispose()


# -- ② 未授权 → DENIED 且 tool_type=mcp --------------------------------------


def test_unauthorized_mcp_call_is_denied(tmp_path: Path) -> None:
    """② deny-by-default：未授权 MCP 调用 → ``status=DENIED`` + ``tool_type=mcp``，且不执行。"""
    factory, engine = build_session_factory(tmp_path / "mcp_deny.db")
    try:
        client = _FakeMCPClient(specs=_specs())
        stack = _build_stack(factory, permissions=[], client=client)

        result = stack.tool_executor.execute(
            ToolCallRequest(name=MCP_TOOL_NAME, arguments={"text": "hi"}),
            ctx=ToolContext(tenant_id="tenant-1", run_id="run-1"),
        )
        assert result.status == TOOL_CALL_STATUS_DENIED
        assert result.ok is False
        assert result.tool_type == "mcp"
        assert client.calls == []  # 未执行（禁止 Agent → MCP Tool → Execute）
        assert stack.audit.records == []  # 未触达 McpExecutor → 无 MCP 审计
    finally:
        engine.dispose()


# -- ③ / ④ 授权执行 → 事件 + 审计 --------------------------------------------


def test_authorized_call_executes_with_events_and_audit(tmp_path: Path) -> None:
    """③④ 授权 → 执行 + ``mcp_call.started/completed`` 事件 + ``audit_log``。"""
    factory, engine = build_session_factory(tmp_path / "mcp_allow.db")
    try:
        client = _FakeMCPClient(
            specs=_specs(), output={"content": [{"type": "text", "text": "PONG"}]}
        )
        stack = _build_stack(factory, permissions=[_allow()], client=client)

        result = stack.tool_executor.execute(
            ToolCallRequest(name=MCP_TOOL_NAME, arguments={"text": "hi"}),
            ctx=ToolContext(tenant_id="tenant-1", run_id="run-1"),
        )
        assert result.ok is True
        assert result.output == {"content": [{"type": "text", "text": "PONG"}]}
        assert client.calls == [("echo", {"text": "hi"})]

        # ③ 事件回放：started 在前、completed 在后，且 completed.status=SUCCESS。
        assert stack.events is not None
        assert stack.events.names() == ["mcp_call.started", "mcp_call.completed"]
        started_payload = stack.events.events[0][1]
        completed_payload = stack.events.events[1][1]
        assert started_payload["server"] == "mock"
        assert started_payload["tool_name"] == "echo"
        assert started_payload["mcp_call_id"] == completed_payload["mcp_call_id"]
        assert completed_payload["status"] == "SUCCESS"

        # ④ 审计：一条 ``mcp.call``，明文不入审计（仅 server/tool/error）。
        assert len(stack.audit.records) == 1
        record = stack.audit.records[0]
        assert record.action == "mcp.call"
        assert record.resource_id == MCP_TOOL_NAME
        assert record.outcome == "SUCCESS"
        assert record.run_id == "run-1"
        assert set(record.metadata) <= {"server", "tool", "error"}
    finally:
        engine.dispose()


# -- ⑤ 适配器满足 Tool Protocol ----------------------------------------------


def test_adapter_satisfies_tool_protocol(tmp_path: Path) -> None:
    """⑤ MCP 适配器满足 ``Tool`` Protocol；``tool_id`` 指向 ``tool`` 表行。"""
    factory, engine = build_session_factory(tmp_path / "mcp_protocol.db")
    try:
        client = _FakeMCPClient(specs=_specs())
        stack = _build_stack(factory, permissions=[_allow()], client=client)

        adapter = stack.tool_registry.get(MCP_TOOL_NAME)
        assert isinstance(adapter, Tool)
        assert adapter.spec.tool_type == "mcp"
        assert adapter.spec.requires_sandbox is False
        assert adapter.spec.metadata.name == MCP_TOOL_NAME
        # ``tool_id`` 指向 ``tool`` 表行（R9/R-22）。
        row = stack.tool_repository.get(adapter.tool_id)
        assert row is not None
        assert row.name == MCP_TOOL_NAME
        assert row.source == "mcp"
        assert row.tool_ref["kind"] == "mcp"
        assert row.tool_ref["id"] == stack.discovered[0].id
    finally:
        engine.dispose()


# -- 同步：tool 表登记 + 内置同名冲突（内置优先 + 告警） ----------------------


def test_sync_registers_tool_rows(tmp_path: Path) -> None:
    """``sync_to_tool_registry`` 在 ``tool`` 表登记 ``source=mcp`` + ``tool_ref`` 行。"""
    factory, engine = build_session_factory(tmp_path / "mcp_sync.db")
    try:
        client = _FakeMCPClient(specs=_specs())
        stack = _build_stack(factory, permissions=[_allow()], client=client)

        assert stack.registered == ["mcp:mock.echo", "mcp:mock.add"]
        assert set(stack.tool_registry.names()) == {"mcp:mock.add", "mcp:mock.echo"}
        rows = {row.name: row for row in stack.tool_repository.list(source="mcp")}
        assert set(rows) == {"mcp:mock.add", "mcp:mock.echo"}
        assert all(row.tool_ref["server_id"] == stack.server.id for row in rows.values())
    finally:
        engine.dispose()


def test_sync_skips_builtin_name_conflict(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内置已占用同名 → **跳过注册** MCP 同名项 + 结构化 ``WARNING``（R10）。"""
    # P2.7-B：显式隔离 logger——in-process ``alembic fileConfig`` 会把既有 logger 置
    # ``disabled=True``（跨用例顺序依赖污染），monkeypatch 自动还原；**不削弱断言强度**。
    _logger = logging.getLogger("astra_mcp.registry")
    monkeypatch.setattr(_logger, "disabled", False)
    monkeypatch.setattr(_logger, "propagate", True)
    factory, engine = build_session_factory(tmp_path / "mcp_conflict.db")
    try:
        client = _FakeMCPClient(specs=_specs())
        tool_registry = ToolRegistry()
        tool_registry.register(MCP_TOOL_NAME, EchoTool(name=MCP_TOOL_NAME))  # 伪内置同名占用

        server_repository = SqlMCPServerRepository(factory)
        mcp_tool_repository = SqlMCPToolRepository(factory)
        server = server_repository.add(MCPServer(name="mock", transport="stdio", command="python"))
        discovered = MCPDiscovery(tool_repository=mcp_tool_repository).discover(server, client)

        registry = MCPRegistry()
        with caplog.at_level(logging.WARNING, logger="astra_mcp.registry"):
            registered = registry.sync_to_tool_registry(
                tool_registry,
                server,
                tools=discovered,
                invoker_factory=lambda srv, tool: MCPClientInvoker(
                    server=srv.name, executor=McpExecutor(client=client)
                ),
            )
        assert MCP_TOOL_NAME not in registered  # 内置优先
        assert "mcp.tool.name_conflict" in caplog.text
    finally:
        engine.dispose()


# -- ⑥ endpoint 过 EgressPolicy（拒段 → PERMISSION_DENIED） -------------------


def test_denied_endpoint_raises_permission_denied() -> None:
    """⑥ ``http`` / ``sse`` 传输 ``endpoint`` 建连前过 ``EgressPolicy``，拒绝即抛。"""
    server = MCPServer(name="blocked", transport="sse", endpoint="http://169.254.169.254/mcp")
    with pytest.raises(DomainError) as excinfo:
        build_mcp_client(server, egress=_DenyEgress())
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
