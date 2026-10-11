"""Runtime 预留位（RP-01~RP-05；总纲 §12.2）。

每个预留位具备**完整 Protocol 签名** + **可装配的 ``Null*`` 空实现**；输入输出类型落
``astra_domain.ports``；Phase 2 只加实现、**不改签名**。

> RP-06（PEP）/ RP-07（PDP）**已在** ``astra_tool.permission_checker`` 落地（W4/T1-17），
> Runtime 仅经 ``RuntimePermissionChecker`` 调用，**不重复实现**。
"""

from __future__ import annotations

from .knowledge_retriever import KnowledgeRetriever, NullKnowledgeRetriever
from .mcp_executor import MCPExecutor, NullMCPExecutor
from .memory_manager import MemoryManager, NullMemoryManager
from .planner import NullPlanner, Planner
from .skill_resolver import NullSkillResolver, SkillResolver

__all__ = [
    "SkillResolver",
    "NullSkillResolver",
    "KnowledgeRetriever",
    "NullKnowledgeRetriever",
    "MemoryManager",
    "NullMemoryManager",
    "MCPExecutor",
    "NullMCPExecutor",
    "Planner",
    "NullPlanner",
    "build_null_reserved",
]


def build_null_reserved() -> dict[str, object]:
    """一键装配全部空实现（Phase 1 默认预留位集合）。"""
    return {
        "skill_resolver": NullSkillResolver(),
        "knowledge_retriever": NullKnowledgeRetriever(),
        "memory_manager": NullMemoryManager(),
        "mcp_executor": NullMCPExecutor(),
        "planner": NullPlanner(),
    }
