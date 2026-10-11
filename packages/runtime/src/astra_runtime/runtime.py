"""``AgentRuntime``（Runtime 入口；设计 §2.7）。

由 Application 调用（Router 不感知 Runtime）；依赖**抽象接口**
（``ModelProvider`` / ``Tool`` / ``SandboxProvider`` / ``EventBus``）与**领域 Protocol 仓储**，
不绑定具体实现（具体装配由组合根 / 集成测试完成，W6 T1-31）。
"""

from __future__ import annotations

from typing import Any

from astra_domain import (
    AgentEventRepository,
    AgentRunRepository,
    MessageRepository,
    RuntimeConfig,
    ToolCallRepository,
)
from astra_event import EventBus
from astra_model import ModelRouter
from astra_tool import ToolRegistry

from .cancellation import CancellationManager
from .concurrency import ConcurrencyController
from .context_manager import ContextManager
from .event_dispatcher import EventDispatcher
from .execution_manager import ExecutionManager, RunContext, RunResult
from .execution_policy import ExecutionPolicyEngine
from .model_executor import ModelExecutor
from .permission_checker import RuntimePermissionChecker
from .prompt_manager import PromptManager
from .reserved.knowledge_retriever import KnowledgeRetriever
from .reserved.mcp_executor import MCPExecutor
from .reserved.memory_manager import MemoryManager
from .reserved.skill_resolver import SkillResolver
from .tool_executor import ToolExecutor

__all__ = ["AgentRuntime", "RunContext", "RunResult"]


class AgentRuntime:
    """Runtime 门面（封装 :class:`ExecutionManager`）。"""

    def __init__(self, execution_manager: ExecutionManager) -> None:
        self._execution_manager = execution_manager

    @property
    def execution_manager(self) -> ExecutionManager:
        """底层执行管理器（供装配 / 测试）。"""
        return self._execution_manager

    def run(self, run_ctx: RunContext) -> RunResult:
        """执行一次 Agent Run。"""
        return self._execution_manager.run(run_ctx)

    @classmethod
    def build(
        cls,
        *,
        run_repository: AgentRunRepository,
        message_repository: MessageRepository,
        tool_call_repository: ToolCallRepository,
        event_bus: EventBus,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        permission_checker: RuntimePermissionChecker | None = None,
        sandbox_provider: Any = None,
        event_repository: AgentEventRepository | None = None,
        runtime_config: RuntimeConfig | None = None,
        concurrency: ConcurrencyController | None = None,
        cancellation: CancellationManager | None = None,
        skill_resolver: SkillResolver | None = None,
        mcp_executor: MCPExecutor | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> AgentRuntime:
        """装配一个 ``AgentRuntime``（全部依赖经 DI 注入，Runtime 零 SQL）。

        说明（W8 / A36）：``permission_checker`` 为**装配期静态回退**（缺省 deny-by-default）；
        **per-agent 规则**由 Application 按 ``agent_id`` 解析、经 ``RunContext.permission_checker``
        **per-run** 注入（``ExecutionManager`` 逐次投递至 ``ToolExecutor.execute``）。本签名不变
        （A30 保持）。

        W2 / T2-09 / T2-12 **加性**扩展（Erratum-8 / R12 / R7 风险规避——**新增可选关键字形参**
        = 向后兼容，非改签名）：

        - ``skill_resolver``：RP-01 真实实现（``astra_skill.resolver.SkillResolver``），由**组合根**
          装配注入（缺省 ``None`` = 不启用 Skill 解析，Phase 1 行为不变）；
        - ``mcp_executor``：RP-04 真实实现（``astra_mcp.runtime.McpExecutor``），同理由**组合根**
          注入（缺省 ``None``）。
        - ``knowledge_retriever``：**RP-02** 真实实现（``astra_knowledge`` 的
          ``KnowledgeRetriever``，W5 / T2-30），由**组合根** ``build_knowledge_retriever(...)``
          装配注入（缺省 ``None`` ＝ 不启用知识检索，Phase 1 行为不变）；知识段在
          ``ExecutionManager._compose_system_prompt`` 合成
          （``ContextManager.build`` 签名冻结、零改）。
        - ``memory_manager``：**RP-03** 真实实现（``astra_memory`` 的 ``MemoryManager``，
          W6 / T2-33），由**组合根** ``build_memory_manager(...)`` 装配注入（缺省 ``None`` ＝
          不启用记忆召回，Phase 1 行为不变）；记忆段同知识段在
          ``ExecutionManager._compose_system_prompt`` 合成（``ContextManager.build`` 签名冻结）。
          **Runtime 仅 ``recall``**（LLM 抽取归应用层，W6 裁定 B2）。
        """
        runtime_config = runtime_config or RuntimeConfig()
        execution_policy = ExecutionPolicyEngine(runtime_config.execution)
        dispatcher = EventDispatcher(event_bus=event_bus, event_repository=event_repository)
        tool_executor = ToolExecutor(
            tool_registry=tool_registry,
            permission_checker=permission_checker,
            sandbox_provider=sandbox_provider,
            tool_timeout_ms=execution_policy.tool_timeout_ms,
        )
        model_executor = ModelExecutor(
            model_router=model_router,
            timeout_ms=execution_policy.model_timeout_ms,
        )
        context_manager = ContextManager(context_config=runtime_config.context)
        manager = ExecutionManager(
            run_repository=run_repository,
            message_repository=message_repository,
            tool_call_repository=tool_call_repository,
            model_executor=model_executor,
            tool_executor=tool_executor,
            context_manager=context_manager,
            prompt_manager=PromptManager(),
            event_dispatcher=dispatcher,
            event_repository=event_repository,
            execution_policy=execution_policy,
            concurrency=concurrency,
            cancellation=cancellation
            or (
                CancellationManager(sandbox_provider=sandbox_provider)
                if sandbox_provider is not None
                else None
            ),
            skill_resolver=skill_resolver,
            mcp_executor=mcp_executor,
            knowledge_retriever=knowledge_retriever,
            memory_manager=memory_manager,
        )
        return cls(manager)
