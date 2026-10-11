"""Phase 2b 子链路端到端（F-2a；设计 §4.5 / W6 遗留观察项）。

**2b 子链路**（stub 驱动、确定性、**零网络**）：``Workflow → Knowledge → Memory``。

全程走**真实**组件 + **真实** SQLite：

- 真实 :class:`~astra_workflow.engine.WorkflowEngine` + :class:`~astra_workflow.run.InlineRunner`
  + SQL 仓储（``workflow_run`` / ``workflow_node_run`` **落库**）；
- 真实 :class:`~astra_workflow.nodes.ToolNode` + ``RuntimeBridgeImpl``
  + 真实 ``ToolExecutor``（**权限单一判定链**）；
- 真实 :class:`~astra_knowledge.retriever.KnowledgeRetriever`（SQLite FTS5 关键字路）+ 五 SQL 仓储；
- 真实 ``MemoryManager``（RP-03 ``remember`` / ``recall``）+ ``SqlMemoryStore``。

断言覆盖：

1. **Knowledge**：``retrieve``（RP-02）/ ``search``（Rich）命中期望 chunk、
   ``metadata.mode=="keyword"``、``resolve_kb_ids`` 命中该 ``workspace_id`` 的 KB；
2. **Workflow**：最小 workflow（2 节点 + 边）经真实引擎运行 → ``workflow_run`` 终态 ``SUCCEEDED``、
   ``workflow_node_run`` 落库、节点 output 以 ``node_key`` 命名空间注入（``I-P2-05``）；
3. **Memory**：``remember``（RP-03）写入 → ``recall`` 召回（跨会话沉淀语义）；
4. **跨域贯通**：``Workflow 运行 → Knowledge 命中 → Memory 沉淀 → recall 召回`` 端到端链路。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astra_domain import KnowledgeQuery, MemoryQuery, MemoryRecord
from astra_knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    build_knowledge_repositories,
    build_knowledge_retriever,
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
from astra_runtime import RuntimePermissionChecker, ToolExecutor
from astra_tool import (
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

from tests.unit.runtime_stubs import allow_tool, build_session_factory

# -- 常量 --------------------------------------------------------------------

TENANT_ID = "tenant-phase2b"
WORKSPACE_ID = "ws-phase2b"
USER_ID = "user-phase2b"

TOOL_NAME = "echo"

#: 跨域贯通链路使用的检索语料与查询（确定性）。
CORPUS_TEXT = "AstraAi 知识检索支持工作流编排与关键字召回"
QUERY_TEXT = "AstraAi 知识检索"

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


def _seed_knowledge(factory: Any, *, content: str = CORPUS_TEXT) -> str:  # noqa: ANN401
    """植一个 workspace 归属的 KB + 1 文档 + 1 分块，返回 ``kb_id``。"""
    repositories = build_knowledge_repositories(factory)
    base = repositories.knowledge_bases.add(
        KnowledgeBase(
            id="kb-phase2b",
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            name="phase2b-kb",
            status="ACTIVE",
            created_by=USER_ID,
        )
    )
    document = repositories.documents.add(
        Document(
            id="doc-phase2b",
            tenant_id=TENANT_ID,
            knowledge_base_id=base.id,
            title="phase2b",
            source_type="text",
            status="READY",
        )
    )
    repositories.chunks.add(
        DocumentChunk(
            id="chunk-phase2b",
            document_id=document.id,
            ordinal=0,
            content=content,
            meta={"format": "text"},
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


def _published_fetch_transform_version() -> WorkflowVersion:
    """构造已发布的「fetch → transform → end」最小图版本。"""
    nodes = [
        WorkflowNode(
            workflow_version_id="wv-phase2b",
            node_key="fetch",
            type=NODE_TYPE_TOOL,
            config={"tool": TOOL_NAME, "arguments": {"query": QUERY_TEXT}},
        ),
        WorkflowNode(
            workflow_version_id="wv-phase2b",
            node_key="transform",
            type=NODE_TYPE_TOOL,
            config={"tool": TOOL_NAME, "arguments": {"from_fetch": "${fetch.query}"}},
        ),
        WorkflowNode(workflow_version_id="wv-phase2b", node_key="end", type=NODE_TYPE_END),
    ]
    edges = [
        WorkflowEdge(
            workflow_version_id="wv-phase2b", from_node_key="fetch", to_node_key="transform"
        ),
        WorkflowEdge(
            workflow_version_id="wv-phase2b", from_node_key="transform", to_node_key="end"
        ),
    ]
    return WorkflowVersion(
        id="wv-phase2b",
        workflow_id="wf-phase2b",
        version="v1",
        definition=build_definition(nodes, edges, entry="fetch"),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by=USER_ID,
    )


# -- 子链路 ①：Knowledge（SQLite FTS5 关键字路） ------------------------------


def test_phase2b_knowledge_keyword_retrieval(tmp_path: Path) -> None:
    """① ``retrieve`` / ``search`` 命中期望 chunk；``mode=keyword``；KB 经 workspace 回落解析。"""
    factory, engine = build_session_factory(tmp_path / "phase2b_knowledge.db")
    try:
        _ensure_sqlite_fts(engine)
        kb_id = _seed_knowledge(factory)
        retriever = build_knowledge_retriever(
            session_factory=factory, model_router=_router(), vector_search=False
        )
        assert retriever.vector_search is False

        # resolve_kb_ids：workspace 回落命中该 workspace 的 KB。
        assert retriever.resolve_kb_ids(
            KnowledgeQuery(text=QUERY_TEXT, workspace_id=WORKSPACE_ID)
        ) == [kb_id]

        # RP-02 retrieve：命中期望 chunk。
        chunks = retriever.retrieve(
            KnowledgeQuery(text=QUERY_TEXT, workspace_id=WORKSPACE_ID, top_k=5)
        )
        assert chunks, "retrieve 未召回任何 chunk"
        assert any("知识检索" in chunk.content for chunk in chunks)

        # Rich search：引用可回溯 + 关键字路 mode。
        hits = retriever.search(QUERY_TEXT, kb_ids=[kb_id], top_k=5)
        assert hits, "search 未召回任何 chunk"
        assert hits[0].chunk_id == "chunk-phase2b"
        assert hits[0].metadata.get("mode") == "keyword"
    finally:
        engine.dispose()


# -- 子链路 ②：Workflow（真实引擎 + SQL 落库 + node_key 命名空间） ------------


def test_phase2b_workflow_run_persists_and_namespaces_output(tmp_path: Path) -> None:
    """② 最小 workflow 运行至 ``SUCCEEDED``；``workflow_node_run`` 落库；``node_key`` 注入。"""
    factory, engine = build_session_factory(tmp_path / "phase2b_workflow.db")
    try:
        stack = _build_workflow_stack(factory)
        stack["versions"].add(_published_fetch_transform_version())
        stack["runs"].add(
            WorkflowRun(
                id="run-phase2b",
                workflow_version_id="wv-phase2b",
                tenant_id=TENANT_ID,
                input={},
            )
        )

        executed = stack["runner"].execute("run-phase2b")

        # workflow_run 终态落库（回读自 SQLite）。
        assert executed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
        assert stack["runs"].get("run-phase2b").status == WORKFLOW_RUN_STATUS_SUCCEEDED

        # workflow_node_run 落库（END 节点不产记录；按执行顺序）。
        recorded = stack["node_runs"].list_by_run("run-phase2b")
        assert [row.node_key for row in recorded] == ["fetch", "transform"]
        assert all(row.status == WORKFLOW_NODE_RUN_STATUS_SUCCEEDED for row in recorded)

        # I-P2-05：节点 output 以 node_key 命名空间注入。
        outputs = executed.output["outputs"]
        assert outputs["fetch"] == {"query": QUERY_TEXT}
        # transform 引用 ${fetch.query} → 命名空间注入生效。
        assert outputs["transform"] == {"from_fetch": QUERY_TEXT}
    finally:
        engine.dispose()


# -- 子链路 ③：Memory（RP-03 remember / recall 沉淀） -------------------------


def test_phase2b_memory_remember_then_recall(tmp_path: Path) -> None:
    """③ ``remember``（RP-03）写入一条记忆 → 后续 ``recall`` 可召回（跨会话沉淀语义）。"""
    factory, engine = build_session_factory(tmp_path / "phase2b_memory.db")
    try:
        repositories = build_memory_repositories(factory)
        manager = MemoryManager(
            store=SqlMemoryStore(repository=repositories.memories),
            relation_repository=repositories.relations,
        )

        manager.remember(
            MemoryRecord(
                key="mem-phase2b",
                content="用户偏好深色主题",
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                kind=MEMORY_KIND_LONG_TERM,
                scope_type=SCOPE_TYPE_WORKSPACE,
                scope_id=WORKSPACE_ID,
                visibility=VISIBILITY_WORKSPACE,
                importance=1.0,
            )
        )

        recalled = manager.recall(
            MemoryQuery(text="深色", tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        )
        assert [record.content for record in recalled] == ["用户偏好深色主题"]
    finally:
        engine.dispose()


# -- 跨域贯通：Workflow → Knowledge → Memory --------------------------------


def test_phase2b_cross_domain_flow_is_deterministic(tmp_path: Path) -> None:
    """④ 端到端：``Workflow 运行 → Knowledge 检索命中 → Memory 沉淀 → recall 召回``。"""
    factory, engine = build_session_factory(tmp_path / "phase2b_flow.db")
    try:
        _ensure_sqlite_fts(engine)
        kb_id = _seed_knowledge(factory)

        # 1) Workflow 运行 → 取其节点 output 作为下游检索查询。
        stack = _build_workflow_stack(factory)
        stack["versions"].add(_published_fetch_transform_version())
        stack["runs"].add(
            WorkflowRun(
                id="run-flow",
                workflow_version_id="wv-phase2b",
                tenant_id=TENANT_ID,
                input={},
            )
        )
        executed = stack["runner"].execute("run-flow")
        assert executed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
        query = executed.output["outputs"]["fetch"]["query"]
        assert query == QUERY_TEXT

        # 2) Knowledge 检索命中。
        retriever = build_knowledge_retriever(
            session_factory=factory, model_router=_router(), vector_search=False
        )
        hits = retriever.search(query, kb_ids=[kb_id], top_k=1)
        assert hits, "跨域链路：Knowledge 检索未命中"
        assert hits[0].metadata.get("mode") == "keyword"
        retrieved_content = hits[0].content

        # 3) Memory 沉淀检索命中内容（跨越 Run 边界）。
        repositories = build_memory_repositories(factory)
        manager = MemoryManager(
            store=SqlMemoryStore(repository=repositories.memories),
            relation_repository=repositories.relations,
        )
        manager.remember(
            MemoryRecord(
                key="mem-flow",
                content=retrieved_content,
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                kind=MEMORY_KIND_LONG_TERM,
                scope_type=SCOPE_TYPE_WORKSPACE,
                scope_id=WORKSPACE_ID,
                visibility=VISIBILITY_WORKSPACE,
                importance=1.0,
                source_run_id="run-flow",
            )
        )

        # 4) 再 recall 召回。
        recalled = manager.recall(
            MemoryQuery(text=QUERY_TEXT, tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
        )
        assert retrieved_content in [record.content for record in recalled]
    finally:
        engine.dispose()
