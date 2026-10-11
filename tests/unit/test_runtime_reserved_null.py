"""Runtime 预留位空实现单测（T1-25 / 总纲 §12.1）。

断言 5 个空实现**可装配、签名可调用**，且输入输出类型落 ``astra_domain.ports``。
"""

from __future__ import annotations

from astra_domain import (
    KnowledgeChunk,
    KnowledgeQuery,
    MCPCallRequest,
    MCPCallResult,
    MemoryQuery,
    MemoryRecord,
    Plan,
    ResolvedSkill,
    SkillQuery,
)
from astra_runtime.reserved import (
    KnowledgeRetriever,
    MCPExecutor,
    MemoryManager,
    NullKnowledgeRetriever,
    NullMCPExecutor,
    NullMemoryManager,
    NullPlanner,
    NullSkillResolver,
    Planner,
    SkillResolver,
    build_null_reserved,
)


def test_null_implementations_are_instantiable() -> None:
    assert isinstance(NullSkillResolver(), SkillResolver)
    assert isinstance(NullKnowledgeRetriever(), KnowledgeRetriever)
    assert isinstance(NullMemoryManager(), MemoryManager)
    assert isinstance(NullMCPExecutor(), MCPExecutor)
    assert isinstance(NullPlanner(), Planner)


def test_null_skill_resolver_signature() -> None:
    result = NullSkillResolver().resolve(SkillQuery(text="x"))
    assert result == []
    assert all(isinstance(item, ResolvedSkill) for item in result)


def test_null_knowledge_retriever_signature() -> None:
    chunks = NullKnowledgeRetriever().retrieve(KnowledgeQuery(text="x", top_k=3))
    assert chunks == []
    assert all(isinstance(item, KnowledgeChunk) for item in chunks)


def test_null_memory_manager_signature() -> None:
    manager = NullMemoryManager()
    assert manager.remember(MemoryRecord(key="k", content="v")) is None
    assert manager.recall(MemoryQuery(text="v")) == []


def test_null_mcp_executor_signature() -> None:
    result = NullMCPExecutor().call(MCPCallRequest(server="s", tool_name="t"))
    assert isinstance(result, MCPCallResult)
    assert result.ok is False


def test_null_planner_signature() -> None:
    plan = NullPlanner().plan("goal")
    assert isinstance(plan, Plan)
    assert plan.goal == "goal"
    assert plan.steps == []


def test_build_null_reserved_bundle() -> None:
    bundle = build_null_reserved()
    assert set(bundle) == {
        "skill_resolver",
        "knowledge_retriever",
        "memory_manager",
        "mcp_executor",
        "planner",
    }
    assert isinstance(bundle["planner"], NullPlanner)
