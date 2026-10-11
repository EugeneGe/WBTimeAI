"""Phase 2a 子链路端到端（T2-19 产出物；W3 裁定 §9.3 / §20.5）。

**2a 子链路**（stub 驱动、确定性）：``Skill 解析 → Agent 运行（含 Skill 指令上下文）``
与 ``Agent → MCP 工具调用（经权限单一判定链）``。

驱动方式：**脚本化**模型 Provider（{class}`ScriptedModelProvider`）+ 伪 MCP Client
（仅实现 :class:`MCPClient` 契约），但全程走**真实**组件：

- 真实 ``AgentRuntime`` / ``ExecutionManager``（含真实 ``SkillResolver`` 绑定驱动）；
- 真实 ``resource_permission`` 单一判定链（``astra_security.ResourcePermissionChecker``）；
- 真实 MCP 适配器注册（``MCPRegistry.sync_to_tool_registry``）+ 真实 ``ToolExecutor``。

断言：
1. 绑定命中的 Skill 指令**进入**投递模型的 system 上下文（golden）；未绑定**不注入**；
2. MCP 工具经**真实** ``resource_permission`` 判定链：授权 → ``SUCCESS`` + ``tool_type=mcp``；
   未授权 → ``DENIED`` + ``tool_type=mcp`` 且**不执行**（deny-by-default）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_database import SqlResourcePermissionRepository, SqlToolRepository
from astra_domain import (
    TOOL_CALL_STATUS_DENIED,
    MCPCallResult,
    ResourcePermission,
    ToolPermission,
)
from astra_event import LocalEventBus
from astra_mcp import (
    MCPClientInvoker,
    MCPDiscovery,
    McpExecutor,
    MCPRegistry,
    MCPServer,
    MCPToolSpec,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
)
from astra_runtime import (
    AgentRuntime,
    RunContext,
    RuntimePermissionChecker,
    ToolCallRequest,
    ToolExecutor,
)
from astra_security import ResourcePermissionChecker
from astra_skill import LoadedSkill, SkillManifest, SkillRegistry, SkillResolver
from astra_tool import PermissionChecker, ToolContext, ToolRegistry

from tests.e2e.fixtures.stub_provider_script import ScriptedModelProvider
from tests.unit.runtime_stubs import build_model_router, build_session_factory, make_agent_version

# -- 常量 --------------------------------------------------------------------

SKILL_MARKER = "SKILL-INSTRUCTIONS-MARKER"
MCP_TOOL_NAME = "mcp:mock.echo"
TENANT_ID = "tenant-phase2a"
AGENT_ID = "agent-phase2a"


# -- 通用支撑 ----------------------------------------------------------------


def _loaded_skill(
    name: str, version: str, instructions: str, *, description: str = ""
) -> LoadedSkill:
    """构造一个内存 :class:`LoadedSkill`（供注册 / 绑定）。"""
    manifest = SkillManifest(name=name, version=version, description=description)
    return LoadedSkill(manifest=manifest, instructions=instructions, source="builtin")


def _registry(*skills: LoadedSkill) -> SkillRegistry:
    """把若干 Skill 注册进一个 :class:`SkillRegistry`。"""
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill.name, skill.version, skill)
    return registry


def _system_content(provider: ScriptedModelProvider) -> str:
    """取模型首次收到的首条 system 消息内容。"""
    assert provider.seen_messages, "模型未被调用（无录制 messages）"
    first = provider.seen_messages[0][0]
    assert first.role == "system"
    return first.content


# -- 子链路 ①：Skill 解析 → Agent 运行（Skill 指令进入上下文） -----------------


def _build_skill_runtime(
    factory: Any,  # noqa: ANN401
    *,
    responses: Sequence[str],
    bindings: Sequence[LoadedSkill],
) -> tuple[AgentRuntime, ScriptedModelProvider]:
    """装配一个注入**绑定驱动** ``SkillResolver`` 的真实 ``AgentRuntime``。"""
    provider = ScriptedModelProvider(responses, model="scripted-1", name="scripted")
    skill = bindings[0] if bindings else None
    resolver = (
        SkillResolver(registry=_registry(*bindings), bindings_provider=lambda _vid: list(bindings))
        if skill is not None
        else SkillResolver(registry=_registry(), bindings_provider=lambda _vid: [])
    )
    runtime = AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_repository=SqlAgentEventRepository(factory),
        event_bus=LocalEventBus(),
        model_router=build_model_router(provider, name="scripted"),
        tool_registry=ToolRegistry(),
        skill_resolver=resolver,
    )
    return runtime, provider


def _run_agent(runtime: AgentRuntime, version: Any, *, message: str):  # noqa: ANN401, ANN202
    """执行一次 Run（返回结果）。"""
    return runtime.run(
        RunContext(
            conversation_id=f"conv-{message}",
            agent_id=AGENT_ID,
            agent_version=version,
            tenant_id=TENANT_ID,
            user_message=message,
        )
    )


def test_phase2a_skill_to_agent_context(tmp_path: Path) -> None:
    """① Skill 解析 → Agent：命中绑定的 Skill 指令进入 system 上下文（golden）。"""
    factory, engine = build_session_factory(tmp_path / "phase2a_skill.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", SKILL_MARKER, description="pdf workflows")
        version = make_agent_version(system_prompt="AGENT-PROMPT", provider="scripted")
        runtime, provider = _build_skill_runtime(factory, responses=["done"], bindings=[skill])

        result = _run_agent(runtime, version, message="pdf")

        assert result.success is True
        system_content = _system_content(provider)
        assert "AGENT-PROMPT" in system_content
        assert SKILL_MARKER in system_content
        assert system_content == f"AGENT-PROMPT\n\n{SKILL_MARKER}"
    finally:
        engine.dispose()


def test_phase2a_unbound_agent_stays_phase1_behavior(tmp_path: Path) -> None:
    """② 绑定门：未绑定 Skill 的 Agent 行为与 Phase 1 一致（不注入）。"""
    factory, engine = build_session_factory(tmp_path / "phase2a_unbound.db")
    try:
        version = make_agent_version(system_prompt="AGENT-PROMPT", provider="scripted")
        runtime, provider = _build_skill_runtime(factory, responses=["done"], bindings=[])

        result = _run_agent(runtime, version, message="pdf")

        assert result.success is True
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()


# -- 子链路 ②：Agent → MCP 调用（经真实 resource_permission 判定链） ----------


class _FakeMCPClient:
    """最小 MCP Client 桩（确定性；实现 :class:`MCPClient` 契约）。"""

    def __init__(self, *, specs: Sequence[MCPToolSpec], output: Any = None) -> None:
        self._specs = list(specs)
        self._output = (
            output if output is not None else {"content": [{"type": "text", "text": "ok"}]}
        )
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
        return MCPCallResult(ok=True, output=self._output)

    def close(self) -> None:
        """关闭计数。"""
        self.closed += 1


def _specs() -> list[MCPToolSpec]:
    """两个可发现的 MCP Tool（``echo`` / ``add``）。"""
    return [
        MCPToolSpec(name="echo", description="回显", input_schema={"type": "object"}),
        MCPToolSpec(name="add", description="求和", input_schema={"type": "object"}),
    ]


def _build_mcp_stack(factory: Any) -> dict[str, Any]:  # noqa: ANN401
    """装配 MCP Server → 发现 → 同步 → 真实 ``resource_permission`` 判定链的 ``ToolExecutor``。"""
    server_repository = SqlMCPServerRepository(factory)
    mcp_tool_repository = SqlMCPToolRepository(factory)
    tool_repository = SqlToolRepository(factory)
    tool_registry = ToolRegistry()

    server = server_repository.add(
        MCPServer(name="mock", transport="stdio", command="python", status="ACTIVE")
    )
    client = _FakeMCPClient(specs=_specs())
    discovered = MCPDiscovery(tool_repository=mcp_tool_repository).discover(server, client)

    # McpExecutor 侧的默认策略模板放行（真正门闸在 ToolExecutor 的 resource_permission 判定链）。
    executor = McpExecutor(
        client=client,
        permission_checker=PermissionChecker(
            permissions=[ToolPermission(tool_id=MCP_TOOL_NAME, action="EXECUTE", effect="ALLOW")]
        ),
    )
    registered = MCPRegistry().sync_to_tool_registry(
        tool_registry,
        server,
        tools=discovered,
        invoker_factory=lambda srv, tool: MCPClientInvoker(server=srv.name, executor=executor),
        tool_repository=tool_repository,
    )
    adapter = tool_registry.get(MCP_TOOL_NAME)
    checker = ResourcePermissionChecker(repository=SqlResourcePermissionRepository(factory))
    tool_executor = ToolExecutor(
        tool_registry=tool_registry,
        permission_checker=RuntimePermissionChecker(checker),
    )
    return {
        "client": client,
        "registered": registered,
        "adapter": adapter,
        "tool_executor": tool_executor,
        "permission_repository": SqlResourcePermissionRepository(factory),
    }


def _grant_mcp_tool(
    permission_repository: Any, *, resource_id: str, agent_id: str
) -> None:  # noqa: ANN401
    """经 ``resource_permission`` 授予 ``(agent_id, TOOL, resource_id, EXECUTE, ALLOW)``。"""
    permission_repository.upsert(
        ResourcePermission(
            tenant_id=TENANT_ID,
            subject_type="agent",
            subject_id=agent_id,
            resource_type="TOOL",
            resource_id=resource_id,
            action="EXECUTE",
            effect="ALLOW",
        )
    )


def test_phase2a_authorized_mcp_call_succeeds(tmp_path: Path) -> None:
    """③ 授权 MCP 调用 → 经真实判定链放行：``SUCCESS`` + ``tool_type=mcp`` + 实际执行。"""
    factory, engine = build_session_factory(tmp_path / "phase2a_mcp_allow.db")
    try:
        stack = _build_mcp_stack(factory)
        adapter = stack["adapter"]
        assert adapter.spec.tool_type == "mcp"
        # 授权锚 = 适配器 ``tool_id``（= ``tool`` 表行 id，判定链同源）。
        _grant_mcp_tool(
            stack["permission_repository"], resource_id=adapter.tool_id, agent_id=AGENT_ID
        )

        result = stack["tool_executor"].execute(
            ToolCallRequest(name=MCP_TOOL_NAME, arguments={"text": "hi"}),
            ctx=ToolContext(tenant_id=TENANT_ID, run_id="run-1", agent_id=AGENT_ID),
        )
        assert result.ok is True
        assert result.tool_type == "mcp"
        assert stack["client"].calls == [("echo", {"text": "hi"})]
    finally:
        engine.dispose()


def test_phase2a_unauthorized_mcp_call_is_denied(tmp_path: Path) -> None:
    """④ 未授权 MCP 调用 → deny-by-default：``DENIED`` + ``tool_type=mcp`` 且不执行。"""
    factory, engine = build_session_factory(tmp_path / "phase2a_mcp_deny.db")
    try:
        stack = _build_mcp_stack(factory)

        result = stack["tool_executor"].execute(
            ToolCallRequest(name=MCP_TOOL_NAME, arguments={"text": "hi"}),
            ctx=ToolContext(tenant_id=TENANT_ID, run_id="run-2", agent_id="agent-unknown"),
        )
        assert result.status == TOOL_CALL_STATUS_DENIED
        assert result.ok is False
        assert result.tool_type == "mcp"
        assert stack["client"].calls == []
    finally:
        engine.dispose()
