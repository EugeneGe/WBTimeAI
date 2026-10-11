"""Phase 2 完成标准全链路端到端（W10 / T2-51；设计 §2.17 / §3-#1 ``E-P2-01``）。

覆盖完成标准全链路（**stub 驱动、确定性、零网络 / 零 Docker**）：

    创建 Skill → 绑定 Agent → 配置 MCP → 编排 Workflow → 上传文档建知识库 →
    检索生效 → 运行 Agent/Workflow 自主调用 Tool 与 MCP → Memory 沉淀并在后续会话被召回 →
    Studio 可视化（数据面）

驱动方式（照抄 ``tests/e2e/test_phase2b_flow.py`` + ``tests/e2e/fixtures/``）：

- **主体链路**（:func:`test_phase2_full_chain_end_to_end`）：全程走**真实**组件 + **真实** SQLite
  （真实 ``AgentRuntime`` / Skill 解析链 / MCP 适配器（经真实 ``resource_permission`` 判定链）/
  Workflow 引擎 / Knowledge 检索器 / MemoryManager），仅以 **脚本化 Provider** 替换模型侧；
- **确定性**（:func:`test_phase2_full_chain_is_deterministic`）：同脚本两次运行 → 合成 system
  prompt、工具调用结果完全一致（非 flaky 证据）；
- **HTTP 数据面**（:func:`test_phase2_studio_data_plane_via_http`）：真实 ``create_app`` +
  ``TestClient`` 走**真实 HTTP / 响应壳 / DB 路径**，断言 Studio 可视化所需数据可经 API 拉取。

🔴 与既有的分工（**不重复造**，D10）：Knowledge 检索质量 golden 断言（SQLite FTS5 路 /
PG 语义路各一组）已由 ``tests/integration/knowledge/**`` 与
``tests/e2e/test_phase2b_flow.py`` 承接；本文补**全链路视角**。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from astra_agent.bindings import load_skill_bindings
from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_database import SqlToolRepository
from astra_domain import (
    TOOL_CALL_STATUS_SUCCESS,
    AgentSkill,
    KnowledgeQuery,
    MCPCallResult,
    MemoryQuery,
    MemoryRecord,
    ToolPermission,
)
from astra_event import LocalEventBus
from astra_knowledge import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    KnowledgeBase,
    build_knowledge_repositories,
    build_knowledge_retriever,
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
)
from astra_memory import (
    MEMORY_KIND_LONG_TERM,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_WORKSPACE,
    MemoryManager,
    SqlMemoryStore,
    build_memory_repositories,
)
from astra_model import ModelRegistry, ModelRouter
from astra_model.stub import StubModelProvider
from astra_runtime import (
    AgentRuntime,
    RunContext,
    RuntimePermissionChecker,
    ToolExecutor,
)
from astra_skill import (
    SKILL_STATUS_ACTIVE,
    SKILL_VERSION_STATUS_PUBLISHED,
    LoadedSkill,
    Skill,
    SkillManifest,
    SkillRegistry,
    SkillVersion,
    SqlAgentSkillRepository,
    SqlSkillRepository,
    SqlSkillVersionRepository,
    build_skill_resolver,
)
from astra_tool import (
    PermissionChecker,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from astra_workflow import (
    NODE_TYPE_END,
    NODE_TYPE_TOOL,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.engine import WorkflowEngine
from astra_workflow.engine.runtime_bridge import RuntimeBridgeImpl
from astra_workflow.nodes import EndNode, NodeRegistry, ToolNode
from astra_workflow.repositories import (
    SqlWorkflowNodeRunRepository,
    SqlWorkflowRunRepository,
    SqlWorkflowVersionRepository,
)
from astra_workflow.run import InlineRunner

from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider
from tests.e2e.fixtures.stub_provider_script import ScriptedModelProvider, tool_call_content
from tests.unit.runtime_stubs import (
    allow_tool,
    build_model_router,
    build_session_factory,
    make_agent_version,
)

# -- 常量 --------------------------------------------------------------------

TENANT_ID = "tenant-phase2"
WORKSPACE_ID = "ws-phase2"
USER_ID = "user-phase2"

#: Skill（绑定驱动解析；W3 / T2-09.1）。
SKILL_NAME = "astraai-knowledge"
SKILL_MARKER = "SKILL-INSTRUCTION-MARKER"

#: 工具（本地 + MCP，各一，证明「自主调用 Tool 与 MCP」）。
TOOL_NAME = "echo"
MCP_SERVER_NAME = "mock"
MCP_TOOL_NAME = "mcp:mock.echo"

#: 知识语料 / 查询（确定性；查询同时命中 Skill 分词与 Memory 召回）。
CORPUS_TEXT = "AstraAi 知识检索支持工作流编排与关键字召回 KNOWLEDGE-CORPUS-MARKER"
QUERY_TEXT = "AstraAi 知识检索"

#: 跨会话沉淀记忆（内容含查询串 → 二次会话可召回）。
MEMORY_CONTENT = "跨会话记忆：AstraAi 知识检索 结果已沉淀 MEMORY-MARKER"

_EMBED_DIMENSION = 8


# -- 通用支撑 ----------------------------------------------------------------


def _router() -> ModelRouter:
    """构造 stub ``ModelRouter``（供检索器嵌入路由占位；关键字路不触嵌入）。"""
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=_EMBED_DIMENSION))
    return ModelRouter(registry)


def _ensure_sqlite_fts(engine: Any) -> None:  # noqa: ANN401 - sa.Engine
    """建 external-content FTS5 虚表 + 触发器（仿迁移 ``0013``；测试基础设施）。

    ``Base.metadata.create_all`` 不含迁移专属 FTS5 虚表，故此处按同口径补齐以驱动关键字路。
    """
    import sqlalchemy as sa

    ddl = [
        "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunk_fts USING fts5("
        "content, content='document_chunk', content_rowid='rowid')",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ai AFTER INSERT ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ad AFTER DELETE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_au AFTER UPDATE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
    ]
    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(sa.text(statement))


def _seed_skill_with_binding(
    factory: Any, *, agent_version_id: str
) -> tuple[str, SkillRegistry]:  # noqa: ANN401
    """植一个已发布 Skill + 绑定到 ``agent_version_id``，返回 ``(skill_id, registry)``。

    走**真实** SQL 仓储（``skill`` / ``skill_version`` / ``agent_skill``），与组合根
    ``build_skill_bindings_provider`` 的解析口径一致。
    """
    skills = SqlSkillRepository(factory)
    versions = SqlSkillVersionRepository(factory)
    bindings = SqlAgentSkillRepository(factory)

    skill = skills.add(
        Skill(
            tenant_id=TENANT_ID,
            name=SKILL_NAME,
            display_name="AstraAi 知识检索",
            description="知识检索与工作流编排",
            category="knowledge",
            status=SKILL_STATUS_ACTIVE,
            created_by=USER_ID,
        )
    )
    versions.add(
        SkillVersion(
            skill_id=skill.id,
            version="1.0.0",
            instructions=SKILL_MARKER,
            status=SKILL_VERSION_STATUS_PUBLISHED,
            created_by=USER_ID,
        )
    )
    bindings.add(AgentSkill(agent_version_id=agent_version_id, skill_id=skill.id, enabled=True))

    registry = SkillRegistry()
    registry.register(
        SKILL_NAME,
        "1.0.0",
        LoadedSkill(
            manifest=SkillManifest(
                name=SKILL_NAME, version="1.0.0", description="knowledge retrieval"
            ),
            instructions=SKILL_MARKER,
            source="builtin",
        ),
    )
    return skill.id, registry


def _seed_knowledge(
    factory: Any,  # noqa: ANN401
    *,
    content: str = CORPUS_TEXT,
    agent_version_id: str | None = None,
) -> str:
    """植一个 workspace 归属的 KB + 1 文档 + 1 分块，返回 ``kb_id``。

    ``agent_version_id`` 非空时同时落一条 ``agent_knowledge`` 绑定——使运行期
    ``KnowledgeRetriever``（组合根口径：已注入绑定仓储）按 ``agent_version`` 命中该 KB。
    """
    repositories = build_knowledge_repositories(factory)
    base = repositories.knowledge_bases.add(
        KnowledgeBase(
            id="kb-phase2",
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            name="phase2-kb",
            status="ACTIVE",
            created_by=USER_ID,
        )
    )
    document = repositories.documents.add(
        Document(
            id="doc-phase2",
            tenant_id=TENANT_ID,
            knowledge_base_id=base.id,
            title="phase2",
            source_type="text",
            status="READY",
        )
    )
    repositories.chunks.add(
        DocumentChunk(
            id="chunk-phase2",
            document_id=document.id,
            ordinal=0,
            content=content,
            meta={"format": "text"},
        )
    )
    if agent_version_id is not None:
        repositories.agent_knowledge.add(
            AgentKnowledge(
                agent_version_id=agent_version_id,
                knowledge_base_id=base.id,
                enabled=True,
            )
        )
    return base.id


class _EchoArgsTool:
    """回显入参的工具（真实 ``ToolSpec`` / ``ToolResult``；确定性）。

    使上游节点 output 成为下游节点引用的确定输入，用于证明 ``node_key`` 命名空间注入。
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.tool_id: str | None = None
        self.version: str | None = None
        self.spec = ToolSpec(
            metadata=ToolMetadata(name=name, display_name=name),
            input_schema={},
            permission=ToolPermissionRequirement(action="EXECUTE"),
            requires_sandbox=False,
        )

    def execute(self, arguments: dict[str, Any], ctx: Any) -> ToolResult:  # noqa: ANN401
        """回显入参（返回入参本身作为节点 output）。"""
        return ToolResult.success(dict(arguments))


class _FakeMCPClient:
    """最小 MCP Client 桩（确定性；实现 :class:`MCPClient` 契约）。"""

    def __init__(self, *, specs: Sequence[MCPToolSpec], output: Any = None) -> None:
        self._specs = list(specs)
        self._output = (
            output if output is not None else {"content": [{"type": "text", "text": "mcp-ok"}]}
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


def _mcp_specs() -> list[MCPToolSpec]:
    """MCP Server 可发现的工具（``echo``）。"""
    return [MCPToolSpec(name="echo", description="回显", input_schema={"type": "object"})]


def _sync_mcp_to_registry(
    factory: Any, tool_registry: ToolRegistry  # noqa: ANN401
) -> _FakeMCPClient:
    """注册 MCP Server → 发现 → 同步进 ``tool_registry``（落 ``mcp_tool`` / ``tool``）。

    复用 W2 ``MCPDiscovery`` + ``MCPRegistry.sync_to_tool_registry``（与组合根同口径）。
    """
    server_repository = SqlMCPServerRepository(factory)
    mcp_tool_repository = SqlMCPToolRepository(factory)
    tool_repository = SqlToolRepository(factory)

    server = server_repository.add(
        MCPServer(
            tenant_id=TENANT_ID,
            name=MCP_SERVER_NAME,
            transport="stdio",
            command="python",
            status="ACTIVE",
        )
    )
    client = _FakeMCPClient(specs=_mcp_specs())
    discovered = MCPDiscovery(tool_repository=mcp_tool_repository).discover(server, client)

    # McpExecutor 侧默认模板放行；真正门闸在运行期 ToolExecutor 的判定链。
    executor = McpExecutor(
        client=client,
        permission_checker=PermissionChecker(
            permissions=[ToolPermission(tool_id=MCP_TOOL_NAME, action="EXECUTE", effect="ALLOW")]
        ),
    )
    MCPRegistry().sync_to_tool_registry(
        tool_registry,
        server,
        tools=discovered,
        invoker_factory=lambda srv, tool: MCPClientInvoker(server=srv.name, executor=executor),
        tool_repository=tool_repository,
    )
    return client


def _published_fetch_transform_version() -> WorkflowVersion:
    """构造已发布的「fetch → transform → end」最小图版本。"""
    nodes = [
        WorkflowNode(
            workflow_version_id="wv-phase2",
            node_key="fetch",
            type=NODE_TYPE_TOOL,
            config={"tool": TOOL_NAME, "arguments": {"query": QUERY_TEXT}},
        ),
        WorkflowNode(
            workflow_version_id="wv-phase2",
            node_key="transform",
            type=NODE_TYPE_TOOL,
            config={"tool": TOOL_NAME, "arguments": {"from_fetch": "${fetch.query}"}},
        ),
        WorkflowNode(workflow_version_id="wv-phase2", node_key="end", type=NODE_TYPE_END),
    ]
    edges = [
        WorkflowEdge(
            workflow_version_id="wv-phase2", from_node_key="fetch", to_node_key="transform"
        ),
        WorkflowEdge(workflow_version_id="wv-phase2", from_node_key="transform", to_node_key="end"),
    ]
    return WorkflowVersion(
        id="wv-phase2",
        workflow_id="wf-phase2",
        version="v1",
        definition=build_definition(nodes, edges, entry="fetch"),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by=USER_ID,
    )


def _build_workflow_stack(factory: Any) -> dict[str, Any]:  # noqa: ANN401
    """装配「真实引擎 + 真实 ToolNode（过权限判定链）+ SQL 仓储」的内联运行栈。"""
    versions = SqlWorkflowVersionRepository(factory)
    runs = SqlWorkflowRunRepository(factory)
    node_runs = SqlWorkflowNodeRunRepository(factory)

    tool_registry = ToolRegistry()
    tool_registry.register(TOOL_NAME, _EchoArgsTool(TOOL_NAME))
    tool_executor = ToolExecutor(
        tool_registry=tool_registry,
        permission_checker=RuntimePermissionChecker(allow_tool(TOOL_NAME)),
    )
    bridge = RuntimeBridgeImpl(
        tool_executor=tool_executor,
        checker_resolver=lambda _agent_id: RuntimePermissionChecker(allow_tool(TOOL_NAME)),
    )
    node_registry = NodeRegistry()
    node_registry.register(ToolNode(bridge))
    node_registry.register(EndNode())
    engine = WorkflowEngine(node_registry.as_mapping())
    runner = InlineRunner(engine, runs, node_runs=node_runs, versions=versions)
    return {
        "engine": engine,
        "versions": versions,
        "runs": runs,
        "node_runs": node_runs,
        "runner": runner,
    }


def _build_agent_runtime(
    factory: Any,  # noqa: ANN401
    *,
    provider: ScriptedModelProvider,
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry,
    sandbox: FakeSandboxProvider,
) -> tuple[AgentRuntime, MemoryManager]:
    """装配「真实 AgentRuntime（Skill 解析链 + 知识检索器 + 记忆管理器）+ SQL 仓储」。

    与组合根（``build_app_services``）同口径构造 ``skill_resolver`` / ``knowledge_retriever`` /
    ``memory_manager`` 并注入 runtime——**仅**模型路由指向脚本化 Provider（确定性）。
    """
    from astra_api.dependencies.services import build_skill_bindings_provider

    skill_repository = SqlSkillRepository(factory)
    agent_skill_repository = SqlAgentSkillRepository(factory)
    skill_resolver = build_skill_resolver(
        skill_registry,
        bindings_provider=build_skill_bindings_provider(
            skill_repository=skill_repository,
            agent_skill_repository=agent_skill_repository,
            skill_registry=skill_registry,
        ),
    )
    knowledge_retriever = build_knowledge_retriever(
        session_factory=factory, model_router=_router(), vector_search=False
    )
    memory_repositories = build_memory_repositories(factory)
    memory_manager = MemoryManager(
        store=SqlMemoryStore(repository=memory_repositories.memories),
        relation_repository=memory_repositories.relations,
    )

    checker = RuntimePermissionChecker(
        PermissionChecker(
            permissions=[
                ToolPermission(tool_id=TOOL_NAME, action="EXECUTE", effect="ALLOW"),
                ToolPermission(tool_id=MCP_TOOL_NAME, action="EXECUTE", effect="ALLOW"),
            ]
        )
    )
    runtime = AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_repository=SqlAgentEventRepository(factory),
        event_bus=LocalEventBus(),
        model_router=build_model_router(provider, name="scripted"),
        tool_registry=tool_registry,
        permission_checker=checker,
        sandbox_provider=sandbox,
        skill_resolver=skill_resolver,
        knowledge_retriever=knowledge_retriever,
        memory_manager=memory_manager,
    )
    return runtime, memory_manager


def _run_agent(
    runtime: AgentRuntime,
    version: Any,  # noqa: ANN401 - AgentVersion
    *,
    conversation_id: str,
    message: str = QUERY_TEXT,
) -> Any:  # noqa: ANN401 - RunResult
    """执行一次 Run（真实 Runtime + 真实 SQLite）。"""
    return runtime.run(
        RunContext(
            conversation_id=conversation_id,
            agent_id="agent-phase2",
            agent_version=version,
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            user_message=message,
        )
    )


def _system_content(provider: ScriptedModelProvider) -> str:
    """取模型首次收到的首条 system 消息内容。"""
    assert provider.seen_messages, "模型未被调用（无录制 messages）"
    first = provider.seen_messages[0][0]
    assert first.role == "system"
    return first.content


# -- 用例 1：全链路（Skill → Agent → MCP → Workflow → Knowledge → Run → Memory）


def test_phase2_full_chain_end_to_end(tmp_path: Path) -> None:
    """Phase 2 完成标准全链路（stub 驱动、确定性、零网络）。

    覆盖：创建 Skill → 绑定 Agent → 配置 MCP → 编排 Workflow → 上传文档建知识库 →
    检索生效 → 运行 Agent 自主调用 Tool 与 MCP → Memory 沉淀并跨会话召回 → Studio 数据面。
    """
    factory, engine = build_session_factory(tmp_path / "phase2_flow.db")
    try:
        _ensure_sqlite_fts(engine)

        # 1) Skill：创建 + 绑定 Agent 版本（真实 SQL 仓储 + 真实绑定解析链）。
        agent_version = make_agent_version(system_prompt="AGENT-PROMPT", provider="scripted")
        skill_id, skill_registry = _seed_skill_with_binding(
            factory, agent_version_id=agent_version.id
        )
        bindings = load_skill_bindings(SqlAgentSkillRepository(factory), agent_version.id)
        assert [b.skill_id for b in bindings] == [skill_id], "Skill 应绑定到该 AgentVersion"

        # 2) MCP：注册 Server → 发现 → 同步进 tool 注册表（落 mcp_tool / tool）。
        tool_registry = ToolRegistry()
        tool_registry.register(TOOL_NAME, _EchoArgsTool(TOOL_NAME))
        mcp_client = _sync_mcp_to_registry(factory, tool_registry)
        mcp_adapter = tool_registry.get(MCP_TOOL_NAME)
        assert mcp_adapter is not None and mcp_adapter.spec.tool_type == "mcp"

        # 3) Workflow：编排最小图 → 真实引擎运行至 SUCCEEDED + node_key 命名空间注入。
        workflow_stack = _build_workflow_stack(factory)
        workflow_stack["versions"].add(_published_fetch_transform_version())
        workflow_stack["runs"].add(
            WorkflowRun(
                id="run-wf",
                workflow_version_id="wv-phase2",
                tenant_id=TENANT_ID,
                input={},
            )
        )
        executed_wf = workflow_stack["runner"].execute("run-wf")
        assert executed_wf.status == WORKFLOW_RUN_STATUS_SUCCEEDED
        recorded = workflow_stack["node_runs"].list_by_run("run-wf")
        assert [row.node_key for row in recorded] == ["fetch", "transform"]
        assert all(row.status == WORKFLOW_NODE_RUN_STATUS_SUCCEEDED for row in recorded)
        assert executed_wf.output["outputs"]["transform"] == {"from_fetch": QUERY_TEXT}

        # 4) Knowledge：上传文档建知识库（绑定 Agent 版本）→ 检索生效（SQLite FTS5 关键字路）。
        kb_id = _seed_knowledge(factory, agent_version_id=agent_version.id)
        retriever = build_knowledge_retriever(
            session_factory=factory, model_router=_router(), vector_search=False
        )
        assert retriever.resolve_kb_ids(
            KnowledgeQuery(text=QUERY_TEXT, workspace_id=WORKSPACE_ID)
        ) == [kb_id]
        hits = retriever.search(QUERY_TEXT, kb_ids=[kb_id], top_k=1)
        assert hits and hits[0].metadata.get("mode") == "keyword"
        assert "KNOWLEDGE-CORPUS-MARKER" in hits[0].content

        # 5) 运行 Agent（脚本：先调 MCP 工具，再给最终答复）→ 自主调用 Tool 与 MCP。
        provider = ScriptedModelProvider(
            [tool_call_content(MCP_TOOL_NAME, {"text": "hi"}), "完成：已调用 MCP 工具"]
        )
        sandbox = FakeSandboxProvider()
        runtime, memory_manager = _build_agent_runtime(
            factory,
            provider=provider,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            sandbox=sandbox,
        )

        first = _run_agent(runtime, agent_version, conversation_id="conv-1")
        assert first.success is True, first
        assert provider.calls == 2, "应恰好两次模型调用（工具调用 + 最终答复）"
        # MCP 工具经真实路径执行（真实适配器 → 伪 MCP Client）。
        assert mcp_client.calls == [("echo", {"text": "hi"})]
        tool_calls = SqlToolCallRepository(factory).list_by_run(first.run_id)
        assert [tc.status for tc in tool_calls] == [TOOL_CALL_STATUS_SUCCESS]
        assert tool_calls[0].tool_type == "mcp"

        # 6) 上下文合成：Skill 指令段 + 知识段均进入投递模型的 system prompt。
        system_prompt = _system_content(provider)
        assert "AGENT-PROMPT" in system_prompt
        assert SKILL_MARKER in system_prompt, "绑定 Skill 的指令应进入 system 上下文"
        assert "KNOWLEDGE-CORPUS-MARKER" in system_prompt, "知识检索命中应进入 system 上下文"

        # 7) Memory 沉淀 → 后续会话召回（跨会话 LONG_TERM）。
        memory_manager.remember(
            MemoryRecord(
                key="mem-phase2",
                content=MEMORY_CONTENT,
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                kind=MEMORY_KIND_LONG_TERM,
                scope_type=SCOPE_TYPE_WORKSPACE,
                scope_id=WORKSPACE_ID,
                visibility=VISIBILITY_WORKSPACE,
                importance=1.0,
                source_run_id=first.run_id,
            )
        )
        recalled = memory_manager.recall(
            MemoryQuery(text=QUERY_TEXT, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        )
        assert MEMORY_CONTENT in [record.content for record in recalled]

        provider.seen_messages.clear()
        second = _run_agent(runtime, agent_version, conversation_id="conv-2")
        assert second.success is True
        # 二次会话（新 conversation）system prompt 含跨会话召回的记忆段。
        assert "MEMORY-MARKER" in _system_content(provider)

        # 8) 硬隔离：跨**租户**召回为空（I-1 / I-P2-10；tenant_id 强制过滤）。
        other = memory_manager.recall(
            MemoryQuery(text=QUERY_TEXT, tenant_id="tenant-other", workspace_id=WORKSPACE_ID)
        )
        assert MEMORY_CONTENT not in [record.content for record in other]
    finally:
        engine.dispose()


# -- 用例 2：确定性（同脚本两次运行 → 一致） ----------------------------------


def test_phase2_full_chain_is_deterministic(tmp_path: Path) -> None:
    """同脚本两次全链路 Run → 合成 system prompt / 工具调用结果完全一致（非 flaky）。"""
    factory, engine = build_session_factory(tmp_path / "phase2_det.db")
    try:
        _ensure_sqlite_fts(engine)
        agent_version = make_agent_version(system_prompt="AGENT-PROMPT", provider="scripted")
        _skill_id, skill_registry = _seed_skill_with_binding(
            factory, agent_version_id=agent_version.id
        )
        _seed_knowledge(factory, agent_version_id=agent_version.id)

        tool_registry = ToolRegistry()
        tool_registry.register(TOOL_NAME, _EchoArgsTool(TOOL_NAME))
        mcp_client = _sync_mcp_to_registry(factory, tool_registry)

        def _one_run(conversation_id: str) -> tuple[str, str, list[str]]:
            provider = ScriptedModelProvider(
                [tool_call_content(MCP_TOOL_NAME, {"text": "hi"}), "done"]
            )
            runtime, _manager = _build_agent_runtime(
                factory,
                provider=provider,
                tool_registry=tool_registry,
                skill_registry=skill_registry,
                sandbox=FakeSandboxProvider(),
            )
            result = _run_agent(runtime, agent_version, conversation_id=conversation_id)
            assert result.success is True
            return (
                _system_content(provider),
                result.final_content,
                [tc.status for tc in result.tool_calls],
            )

        first = _one_run("conv-a")
        second = _one_run("conv-b")
        assert first == second, f"两次运行结果不一致：{first!r} != {second!r}"
        # 工具经真实 MCP 适配器执行（两次皆调用同一工具）。
        assert mcp_client.calls == [
            ("echo", {"text": "hi"}),
            ("echo", {"text": "hi"}),
        ]
    finally:
        engine.dispose()


# -- 用例 3：Studio 数据面（真实 HTTP / TestClient / 响应壳 / DB 路径） --------


def _shell_data(resp: Any) -> Any:  # noqa: ANN401
    """取统一响应壳的 ``data``（``{code,message,data,request_id}``）。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def test_phase2_studio_data_plane_via_http(
    client: Any, auth_headers: dict[str, str]
) -> None:  # noqa: ANN401
    """Studio 可视化所需数据可经**真实 HTTP API** 拉取（Skill / Agent / Knowledge /
    Workflow / Memory）。

    真实 ``create_app`` + ``TestClient``（真实中间件 / 统一响应壳 / SQLite）；零网络。
    """
    workspace_id = _shell_data(
        client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "Studio WS"})
    )["id"]

    # Skill：创建 → 列表（Studio SkillBuilder 数据面）。
    skill = client.post(
        "/api/v1/skills",
        headers=auth_headers,
        json={"name": "studio-skill", "display_name": "Studio Skill"},
    )
    assert skill.status_code == 201, skill.text
    skills = client.get("/api/v1/skills", headers=auth_headers)
    assert skills.status_code == 200
    assert "studio-skill" in [item["name"] for item in _shell_data(skills)]

    # Agent：创建 → 列表（Studio AgentStudio 数据面）。
    agent = client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={"name": "Studio Agent", "workspace_id": workspace_id},
    )
    assert agent.status_code == 201, agent.text
    agent_id = _shell_data(agent)["id"]
    agents = client.get("/api/v1/agents", headers=auth_headers)
    assert agent_id in [item["id"] for item in _shell_data(agents)]

    # Knowledge：建库 → 登记文档 → 文档列表（Studio KnowledgeManager 数据面）。
    kb = client.post(
        "/api/v1/knowledge/bases",
        headers=auth_headers,
        json={"name": "Studio KB", "workspace_id": workspace_id},
    )
    assert kb.status_code == 201, kb.text
    kb_id = _shell_data(kb)["id"]
    doc = client.post(
        f"/api/v1/knowledge/bases/{kb_id}/documents",
        headers=auth_headers,
        json={"title": "README", "source_type": "text"},
    )
    assert doc.status_code == 201, doc.text
    documents = client.get(f"/api/v1/knowledge/bases/{kb_id}/documents", headers=auth_headers)
    assert [item["title"] for item in _shell_data(documents)] == ["README"]

    # Workflow：创建 → 列表（Studio WorkflowDesigner 数据面）。
    workflow = client.post(
        "/api/v1/workflows",
        headers=auth_headers,
        json={"name": "Studio Workflow", "workspace_id": workspace_id},
    )
    assert workflow.status_code == 201, workflow.text
    workflows = client.get("/api/v1/workflows", headers=auth_headers)
    assert _shell_data(workflow)["id"] in [item["id"] for item in _shell_data(workflows)]

    # Memory：空态可浏览（Studio MemoryView 数据面；隔离维度经查询串）。
    memories = client.get("/api/v1/memory", headers=auth_headers)
    assert memories.status_code == 200
    assert _shell_data(memories) == []

    # 统一响应壳字段恒存在（成功路径）。
    body = skills.json()
    assert set(body.keys()) >= {"code", "message", "data", "request_id"}
