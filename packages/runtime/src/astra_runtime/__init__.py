"""Astra AI Runtime 执行内核（``astra_runtime``，W5 / T1-23 ~ T1-25）。

🔴 **抽象包（零 ORM）**（W5 架构裁定 Q1 = 方案 B）：runtime **不得** import
   ``sqlalchemy`` / ``alembic`` / ``astra_database`` / ``astra_conversation`` / ``astra_agent`` /
   ``astra_api`` / ``fastapi`` / ``starlette``；持久化一律经 **DI 注入的领域 Protocol 仓储**
   （``astra_domain``），SQL 并发下沉 ``conversation/repositories``。

七组件（设计 §2.7）：``PromptManager`` / ``ContextManager`` / ``ModelExecutor`` /
``ToolExecutor`` / ``RuntimePermissionChecker`` / ``EventDispatcher`` / ``ExecutionManager``。

T1-24：``context_budget`` / ``execution_policy`` / ``cancellation`` / ``concurrency``。
T1-25：``reserved``（RP-01~RP-05 空实现）。
"""

from __future__ import annotations

from .cancellation import CancellationManager
from .concurrency import ConcurrencyController
from .context_budget import (
    TokenCounter,
    TruncationResult,
    apply_budget,
    count_tokens,
    messages_token_count,
    truncate_text,
)
from .context_manager import ContextManager
from .errors import (
    RUN_TIMEOUT,
    context_length_exceeded_error,
    max_iterations_error,
    run_conflict_error,
    run_timeout_error,
    tool_timeout_error,
)
from .event_dispatcher import EventDispatcher
from .execution_manager import ExecutionManager, RunContext, RunResult
from .execution_policy import ExecutionPolicyEngine
from .model_executor import ModelExecutor, ToolCallRequest
from .permission_checker import RuntimePermissionChecker
from .prompt_manager import PromptManager
from .reserved import (
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
from .runtime import AgentRuntime
from .tool_executor import ToolExecutionResult, ToolExecutor

__all__ = [
    # 入口 / 编排
    "AgentRuntime",
    "ExecutionManager",
    "RunContext",
    "RunResult",
    # 七组件
    "PromptManager",
    "ContextManager",
    "ModelExecutor",
    "ToolCallRequest",
    "ToolExecutor",
    "ToolExecutionResult",
    "RuntimePermissionChecker",
    "EventDispatcher",
    # T1-24
    "apply_budget",
    "count_tokens",
    "messages_token_count",
    "truncate_text",
    "TruncationResult",
    "TokenCounter",
    "ExecutionPolicyEngine",
    "CancellationManager",
    "ConcurrencyController",
    # 错误工厂
    "max_iterations_error",
    "context_length_exceeded_error",
    "tool_timeout_error",
    "run_conflict_error",
    "run_timeout_error",
    "RUN_TIMEOUT",
    # T1-25 预留位
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
