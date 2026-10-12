"""``ExecutionManager``（ReAct 循环 + 持久化 run/message/tool_call/event；设计 §2.7 / §2.17）。

驱动最小可用 ReAct 循环，并**经 DI 注入的领域 Protocol 仓储**持久化
``agent_run`` / ``message`` / ``tool_call`` / ``agent_event``（W5 架构裁定 Q1 = 方案 B，
Runtime **零 SQL**）。

循环语义（§2.17）：

1. 组装 messages（system_prompt + 历史 + 工具结果）→ 调模型；
2. 若模型产出工具调用 → 逐次经权限校验执行、落 ``tool_call`` 行、追加工具结果消息；
3. 否则视为最终答复，结束；
4. 达到 ``max_iterations`` 仍产出工具调用 → 终态 ``FAILED`` + ``error_type=MAX_ITERATIONS``。

遥测（``I-P1-29``）：成功 / 模型失败 / 工具失败 / 取消均写
``error_type`` / ``tool_error_count`` / ``duration_ms`` / ``success``。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_domain import MESSAGE_ROLE_ASSISTANT as ROLE_ASSISTANT
from astra_domain import MESSAGE_ROLE_TOOL as ROLE_TOOL
from astra_domain import MESSAGE_ROLE_USER as ROLE_USER
from astra_domain import (
    RUN_MODE_INLINE,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    RUN_TRIGGER_USER,
    TOOL_CALL_STATUS_FAILED,
    AgentEventRepository,
    AgentRun,
    AgentRunRepository,
    AgentVersion,
    ExecutionPolicy,
    KnowledgeChunk,
    KnowledgeQuery,
    MemoryQuery,
    MemoryRecord,
    Message,
    MessageRepository,
    PermissionScope,
    RuntimeConfig,
    SkillQuery,
    ToolCall,
    ToolCallRepository,
)
from astra_event import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    ToolCallCompleted,
    ToolCallStarted,
)
from astra_model import ChatMessage
from astra_tool import ToolContext

from .cancellation import CancellationManager
from .concurrency import ConcurrencyController
from .context_budget import truncate_text
from .context_manager import ContextManager
from .errors import RUN_TIMEOUT
from .event_dispatcher import EventDispatcher
from .execution_policy import ExecutionPolicyEngine
from .model_executor import ModelExecutor, ToolCallRequest
from .permission_checker import RuntimePermissionChecker
from .prompt_manager import PromptManager
from .reserved.knowledge_retriever import KnowledgeRetriever
from .reserved.mcp_executor import MCPExecutor
from .reserved.memory_manager import MemoryManager
from .reserved.skill_resolver import SkillResolver
from .tool_executor import ToolExecutionResult, ToolExecutor

__all__ = ["RunContext", "RunResult", "ExecutionManager"]

#: 取消态 ``error_type``（W6：INLINE 断连 / 显式取消，§2.6 Q-note-2；复用 ``agent.error`` 通道）。
CANCELLED_ERROR_TYPE = "CANCELLED"

#: 知识段标题（W5 / T2-30：合成进 ``system_prompt``；``ContextManager.build`` 零改）。
KNOWLEDGE_SECTION_HEADER = "## Knowledge Context"

#: 知识召回条数（RP-02 调用 ``top_k``；W5 裁定 §5.1 默认 5）。
KNOWLEDGE_TOP_K = 5

#: 记忆段标题（W6 / T2-33：合成进 ``system_prompt``；``ContextManager.build`` 零改）。
MEMORY_SECTION_HEADER = "## Memory Context"

#: 记忆召回条数（RP-03 调用 ``limit``；W6 裁定 §3.3 默认 10）。
MEMORY_TOP_K = 10


@dataclass
class RunContext:
    """一次执行的输入上下文（**总是**针对一个明确 ``agent_version``）。

    W6 / T1-27 + T1-28 **加性**扩展（向后兼容）：

    - ``run``：**可选**预建 ``AgentRun``（Application ``open_run`` 先建 Run + task，
      再复用本 Run 执行——断连取消方有 task 可同步）。为空时维持 W5 语义（Runtime
      内部自建 Run）。
    - ``should_cancel``：**可选**取消探针（Application 维护；Runtime 每轮迭代前查询，
      为真则走取消路径 → 终态 ``CANCELLED`` + 沙箱回收）。
    - ``permission_checker``：**可选** per-run 权限校验器（W8 / A36；Application 按
      ``agent_id`` 解析授权后注入；为空时回退 ``ToolExecutor`` 装配期默认，仍 deny-by-default）。
      per-run 构造、**不写回**共享单例（并发隔离，对齐 A35）。
    """

    conversation_id: str
    agent_id: str
    agent_version: AgentVersion
    tenant_id: str = ""
    workspace_id: str | None = None
    user_id: str | None = None
    user_message: str = ""
    trigger: str = RUN_TRIGGER_USER
    run_mode: str = RUN_MODE_INLINE
    idempotency_key: str | None = None
    trace_id: str | None = None
    permission_scope: PermissionScope | None = None
    run: AgentRun | None = None
    should_cancel: Callable[[], bool] | None = None
    permission_checker: RuntimePermissionChecker | None = None


@dataclass
class RunResult:
    """一次执行的结果与遥测。"""

    run_id: str
    status: str
    success: bool
    error_type: str | None
    duration_ms: int
    tool_error_count: int
    iterations: int
    final_content: str = ""
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


class ExecutionManager:
    """ReAct 执行管理器（编排 + 持久化）。"""

    def __init__(
        self,
        *,
        run_repository: AgentRunRepository,
        message_repository: MessageRepository,
        tool_call_repository: ToolCallRepository,
        model_executor: ModelExecutor,
        tool_executor: ToolExecutor,
        context_manager: ContextManager,
        prompt_manager: PromptManager | None = None,
        event_dispatcher: EventDispatcher,
        event_repository: AgentEventRepository | None = None,
        execution_policy: ExecutionPolicyEngine | None = None,
        concurrency: ConcurrencyController | None = None,
        cancellation: CancellationManager | None = None,
        skill_resolver: SkillResolver | None = None,
        mcp_executor: MCPExecutor | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._message_repository = message_repository
        self._tool_call_repository = tool_call_repository
        self._model_executor = model_executor
        self._tool_executor = tool_executor
        self._context_manager = context_manager
        self._prompt_manager = prompt_manager or PromptManager()
        self._dispatcher = event_dispatcher
        self._event_repository = event_repository
        self._policy = execution_policy or ExecutionPolicyEngine()
        self._concurrency = concurrency
        self._cancellation = cancellation
        # RP-01 / RP-04 填充位（W2 裁定 R12 / Erratum-8）：**仅新增可选注入**，
        # 缺省为 ``None``（=未启用），向后兼容（Phase 1 行为不变）。
        self._skill_resolver = skill_resolver
        self._mcp_executor = mcp_executor
        # RP-02 填充位（W5 裁定 B6 / §4.5）：能力包真实实现经**组合根注入**；
        # 缺省 ``None`` ＝ Phase 1 行为不变（知识段不合成）。
        self._knowledge_retriever = knowledge_retriever
        # RP-03 填充位（W6 裁定 B3 / B8 / §5.5）：能力包真实实现经**组合根注入**；
        # 缺省 ``None`` ＝ Phase 1 行为不变（记忆段不合成）。**仅 ``recall``**（抽取归应用层）。
        self._memory_manager = memory_manager

    def _effective_policy(self, raw_runtime_config: Any) -> ExecutionPolicyEngine:
        """按 ``agent_version.runtime_config`` 数据驱动地解析**生效执行策略**。

        当 ``runtime_config`` 显式携带 ``execution`` 段时，以该段字段覆盖装配期注入的基础
        策略（未指定字段回退基础值）；否则沿用基础策略 :attr:`_policy`。这使
        ``run_timeout_ms`` / ``tool_timeout_ms`` / ``max_retry`` 等可按 Agent 版本配置。
        """
        raw_execution: dict[str, Any] | None = None
        if isinstance(raw_runtime_config, dict):
            candidate = raw_runtime_config.get("execution")
            if isinstance(candidate, dict):
                raw_execution = candidate
        if not raw_execution:
            return self._policy
        merged = self._policy.policy.to_dict()
        merged.update(raw_execution)
        return ExecutionPolicyEngine(ExecutionPolicy.from_dict(merged))

    # -- 入口 ---------------------------------------------------------------

    def _compose_system_prompt(self, ctx: RunContext, agent_version: AgentVersion) -> str:
        """按 W2 裁定 R5 §5.2 冻结序列合成生效 ``system_prompt``。

        组装序列（与设计 §2.2 全量链路对齐，本波次加 Skill 段 + Knowledge 段）:

        1. ``base = prompt_manager.load_system_prompt(agent_version)``；
        2. ``resolved = skill_resolver.resolve(SkillQuery(text=<用户输入>, workspace_id=...))``
           （RP-01，签名**不变**）；未注入解析器时跳过（``Phase 1`` 行为不变）；
        3. ``composed = prompt_manager.compose_system_prompt(agent_version, resolved)``
           （Agent ``system_prompt`` 为主 + Skill 指令按绑定顺序追加；无 Skill 时原样返回）；
        4. **知识段（W5 / T2-30）**：``knowledge_retriever.retrieve(KnowledgeQuery(...))``
           （RP-02，签名**不变**）→ 命中片段合成进 ``system_prompt``；未注入检索器时跳过；
        5. **记忆段（W6 / T2-33）**：``memory_manager.recall(MemoryQuery(...))``
           （RP-03，签名**不变**）→ 命中记忆合成进 ``system_prompt``；未注入管理器时跳过。

        **安全降级**：解析器抛 :class:`~astra_core.DomainError` 时回退为空技能集
        / 空知识集 / 空记忆集（不因解析失败而中断整个 Run）。

        ``ContextManager.build`` 只接收**已合成**的 ``system_prompt``（R5 §5.3，签名不变）。
        """
        if self._skill_resolver is None:
            composed = self._prompt_manager.load_system_prompt(agent_version)
        else:
            try:
                resolved = self._skill_resolver.resolve(
                    SkillQuery(
                        text=ctx.user_message,
                        workspace_id=ctx.workspace_id,
                        # W3 裁定 §19.2.3（T2-09.1）：按 `agent_version` 绑定解析
                        # （`RunContext.agent_version` 已在位 → 仅加一个实参；签名零改）。
                        agent_version_id=agent_version.id,
                    )
                )
            except DomainError:
                resolved = []
            composed = self._prompt_manager.compose_system_prompt(agent_version, list(resolved))
        with_knowledge = self._append_knowledge_segment(composed, ctx, agent_version)
        return self._append_memory_segment(with_knowledge, ctx, agent_version)

    def _append_knowledge_segment(
        self, system_prompt: str, ctx: RunContext, agent_version: AgentVersion
    ) -> str:
        """把 RP-02 召回的知识片段合成进 ``system_prompt``（W5 / T2-30；``ContextManager`` 零改）。

        未注入 ``knowledge_retriever``（``None``）时**原样返回**（Phase 1 行为不变）；
        检索抛 :class:`~astra_core.DomainError` 或**无命中**时亦原样返回（不中断 Run）。

        Args:
            system_prompt: 已合成的系统提示（Skill 段之后）。
            ctx: 运行上下文（``user_message`` / ``workspace_id`` 供检索）。
            agent_version: 当前 ``AgentVersion``（``id`` 用于 KB 绑定解析）。

        Returns:
            追加知识段后的 ``system_prompt``（无命中时不变）。
        """
        if self._knowledge_retriever is None:
            return system_prompt
        try:
            chunks = self._knowledge_retriever.retrieve(
                KnowledgeQuery(
                    text=ctx.user_message,
                    workspace_id=ctx.workspace_id,
                    top_k=KNOWLEDGE_TOP_K,
                    # W5 裁定 B7：按 `agent_version` 绑定解析 KB（`RunContext` 已在位）。
                    agent_version_id=agent_version.id,
                )
            )
        except DomainError:
            return system_prompt
        return _format_knowledge_segment(system_prompt, list(chunks))

    def _append_memory_segment(
        self, system_prompt: str, ctx: RunContext, agent_version: AgentVersion
    ) -> str:
        """把 RP-03 召回的长期记忆合成进 ``system_prompt``（W6 / T2-33；``ContextManager`` 零改）。

        未注入 ``memory_manager``（``None``）时**原样返回**（Phase 1 行为不变）；
        召回抛 :class:`~astra_core.DomainError` 或**无命中**时亦原样返回（不中断 Run）。

        隔离维度经 ``MemoryQuery`` 加性字段传入（``tenant_id`` / ``workspace_id`` /
        ``agent_id`` / ``user_id`` / ``trigger``）；能力包内**强制 ``tenant_id`` 过滤**，
        非用户触发**不召回 ``USER``**（R-19 / B5）。

        Args:
            system_prompt: 已合成的系统提示（Skill 段 + Knowledge 段之后）。
            ctx: 运行上下文（隔离维度 + 用户输入）。
            agent_version: 当前 ``AgentVersion``（``id`` 备用）。

        Returns:
            追加记忆段后的 ``system_prompt``（无命中时不变）。
        """
        if self._memory_manager is None:
            return system_prompt
        try:
            records = self._memory_manager.recall(
                MemoryQuery(
                    text=ctx.user_message,
                    limit=MEMORY_TOP_K,
                    tenant_id=ctx.tenant_id,
                    workspace_id=ctx.workspace_id,
                    agent_id=ctx.agent_id,
                    user_id=ctx.user_id,
                    trigger=ctx.trigger,
                )
            )
        except DomainError:
            return system_prompt
        return _format_memory_segment(system_prompt, list(records))

    def run(self, ctx: RunContext) -> RunResult:
        """执行一次 Run（ReAct 循环 + 持久化 + 事件双通道）。"""
        agent_version = ctx.agent_version
        runtime_config = _coerce_runtime_config(agent_version.runtime_config)
        policy = self._effective_policy(agent_version.runtime_config)
        # W2 / T2-09（Erratum-8）：Skill 指令组装位点——**必须先解析并合成**，
        # 否则 Skill 指令永不到达模型上下文（R5 §5.2 冻结序列）。
        system_prompt = self._compose_system_prompt(ctx, agent_version)

        started = utcnow()
        if ctx.run is not None:
            # W6：复用 Application 预建的 Run（task 已先建 → 断连取消可同步 task），
            # 跳过内部 add / guard_run_creation；W5 语义（ctx.run 为空）保持不变。
            run = ctx.run
        else:
            run = AgentRun(
                tenant_id=ctx.tenant_id,
                agent_id=ctx.agent_id,
                agent_version_id=agent_version.id,
                conversation_id=ctx.conversation_id,
                user_id=ctx.user_id,
                trigger=ctx.trigger,
                run_mode=ctx.run_mode,
                status=RUN_STATUS_RUNNING,
                trace_id=ctx.trace_id,
                idempotency_key=ctx.idempotency_key,
                started_at=started,
            )
            if self._concurrency is not None:
                run = self._concurrency.guard_run_creation(self._run_repository, run)
            else:
                run = self._run_repository.add(run)

        self._dispatcher.bind(run.id, trace_id=run.trace_id)
        tool_ctx = ToolContext(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            run_id=run.id,
            agent_id=ctx.agent_id,
            permission_scope=ctx.permission_scope,
        )

        messages: list[Message] = []
        tool_calls: list[ToolCall] = []
        sessions: list[Any] = []
        history: list[ChatMessage] = []
        iterations = 0
        error_type: str | None = None
        cancelled = False
        final_content = ""

        self._dispatcher.emit(
            AgentStarted.create(
                run_id=run.id,
                agent_id=run.agent_id,
                agent_version_id=agent_version.id,
                conversation_id=run.conversation_id,
                run_mode=run.run_mode,
            ),
            run_id=run.id,
        )

        if ctx.user_message:
            user_message = self._persist_message(
                conversation_id=run.conversation_id,
                run_id=run.id,
                role=ROLE_USER,
                content=ctx.user_message,
            )
            messages.append(user_message)
            history.append(ChatMessage(role="user", content=ctx.user_message))

        try:
            for index in range(int(runtime_config.max_iterations)):
                iterations = index + 1
                self._touch_heartbeat(run.id)
                if ctx.should_cancel is not None and ctx.should_cancel():
                    cancelled = True
                    error_type = CANCELLED_ERROR_TYPE
                    break
                if _run_timeout_exceeded(started, policy.run_timeout_ms):
                    error_type = RUN_TIMEOUT
                    break
                self._dispatcher.emit(
                    AgentThinking.create(run_id=run.id, iteration=iterations), run_id=run.id
                )
                model_messages = self._context_manager.build(
                    system_prompt=system_prompt, history=history
                )
                result = self._model_executor.complete(
                    agent_version.model_config,
                    model_messages,
                    # M1：执行期凭证 / endpoint 绑定上下文（仅透传 router，**不进采样参数**）。
                    tenant_id=ctx.tenant_id,
                    run_id=run.id,
                )
                assistant_text = result.content or ""
                tool_requests = self._model_executor.parse_tool_calls(assistant_text)

                assistant_message = self._persist_message(
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    role=ROLE_ASSISTANT,
                    content=assistant_text,
                )
                messages.append(assistant_message)
                history.append(ChatMessage(role="assistant", content=assistant_text))
                self._dispatcher.emit(
                    AgentMessage.create(
                        run_id=run.id,
                        message_id=assistant_message.id,
                        role=ROLE_ASSISTANT,
                        content=assistant_text,
                    ),
                    run_id=run.id,
                )

                if not tool_requests:
                    final_content = assistant_text
                    break

                for request in tool_requests:
                    tool_call = self._execute_tool_with_retry(
                        run=run,
                        ctx=ctx,
                        tool_ctx=tool_ctx,
                        request=request,
                        runtime_config=runtime_config,
                        sessions=sessions,
                        policy=policy,
                    )
                    tool_calls.append(tool_call)
                    output_text = _stringify(tool_call.output)
                    truncated, _ = truncate_text(
                        output_text, runtime_config.context.tool_output_max_chars
                    )
                    tool_message = self._persist_message(
                        conversation_id=run.conversation_id,
                        run_id=run.id,
                        role=ROLE_TOOL,
                        content=truncated,
                    )
                    messages.append(tool_message)
                    history.append(
                        ChatMessage(role="tool", content=truncated, name=tool_call.tool_name)
                    )
            else:
                # 迭代用尽仍产出工具调用 → 上界失败。
                error_type = str(ErrorCode.MAX_ITERATIONS)
        except DomainError as exc:
            error_type = str(exc.code)

        return self._finalize(
            run=run,
            started=started,
            runtime_config=runtime_config,
            messages=messages,
            tool_calls=tool_calls,
            sessions=sessions,
            iterations=iterations,
            error_type=error_type,
            final_content=final_content,
            cancelled=cancelled,
        )

    # -- 内部：心跳 ---------------------------------------------------------

    def _touch_heartbeat(self, run_id: str) -> None:
        """更新 Run 心跳（W6 / T1-31；Runtime 零 SQL，经领域 Protocol）。

        仓储未实现 ``touch_heartbeat`` 时静默跳过（向后兼容）。
        """
        touch = getattr(self._run_repository, "touch_heartbeat", None)
        if touch is not None:
            touch(run_id)

    # -- 内部：工具执行（含重试） -------------------------------------------

    def _execute_tool_with_retry(
        self,
        *,
        run: AgentRun,
        ctx: RunContext,
        tool_ctx: ToolContext,
        request: ToolCallRequest,
        runtime_config: RuntimeConfig,
        sessions: list[Any],
        policy: ExecutionPolicyEngine | None = None,
    ) -> ToolCall:
        """执行一次逻辑工具调用（失败按策略重试，产生**新** ``tool_call`` 行）。"""
        engine = policy or self._policy
        attempt = self._tool_call_repository.next_attempt(run.id, request.name)
        while True:
            result = self._tool_executor.execute(
                request,
                ctx=tool_ctx,
                attempt=attempt,
                tool_timeout_ms=engine.tool_timeout_ms,
                # per-run 校验器：``ctx`` 为 ``RunContext`` 时取其按 ``agent_id`` 解析的校验器；
                # ``None``（内部单测直调的退化路径）→ 回退 ``ToolExecutor`` 装配期默认（零回归）。
                permission_checker=(ctx.permission_checker if ctx is not None else None),
            )
            tool_call = self._persist_tool_call(
                run=run, request=request, result=result, attempt=attempt
            )
            if result.sandbox_session is not None and result.sandbox_session not in sessions:
                sessions.append(result.sandbox_session)
            self._emit_tool_events(run=run, tool_call=tool_call, result=result)
            if result.ok or not engine.should_retry(
                attempt=attempt, error_code=result.error_code, status=result.status
            ):
                return tool_call
            attempt += 1

    def _persist_tool_call(
        self,
        *,
        run: AgentRun,
        request: ToolCallRequest,
        result: ToolExecutionResult,
        attempt: int,
    ) -> ToolCall:
        """落一条 ``tool_call`` 行（每次尝试一行）。"""
        tool_call = ToolCall(
            run_id=run.id,
            tool_id=result.tool_id,
            tool_name=result.tool_name or request.name,
            tool_type=result.tool_type,
            tool_ref=dict(result.tool_ref),
            attempt=attempt,
            trace_id=run.trace_id,
            input=dict(request.arguments),
            output=_as_output(result.output),
            status=result.status,
            duration_ms=result.duration_ms,
            sandbox_session_id=result.sandbox_session_id,
            error=result.error,
        )
        return self._tool_call_repository.add(tool_call)

    def _emit_tool_events(
        self, *, run: AgentRun, tool_call: ToolCall, result: ToolExecutionResult
    ) -> None:
        """发 ``tool_call.started`` / ``tool_call.completed`` 事件。"""
        self._dispatcher.emit(
            ToolCallStarted.create(
                run_id=run.id,
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                attempt=tool_call.attempt,
                arguments=dict(tool_call.input),
            ),
            run_id=run.id,
        )
        self._dispatcher.emit(
            ToolCallCompleted.create(
                run_id=run.id,
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                status=tool_call.status,
                duration_ms=tool_call.duration_ms,
                error=tool_call.error,
            ),
            run_id=run.id,
        )

    # -- 内部：持久化消息 ---------------------------------------------------

    def _persist_message(
        self,
        *,
        conversation_id: str,
        run_id: str,
        role: str,
        content: str,
    ) -> Message:
        """落一条 ``message`` 行并返回领域实体。"""
        message = Message(
            conversation_id=conversation_id,
            run_id=run_id,
            role=role,
            content=content,
        )
        return self._message_repository.add(message)

    # -- 内部：收尾 ---------------------------------------------------------

    def _finalize(
        self,
        *,
        run: AgentRun,
        started: Any,
        runtime_config: RuntimeConfig,
        messages: list[Message],
        tool_calls: list[ToolCall],
        sessions: list[Any],
        iterations: int,
        error_type: str | None,
        final_content: str,
        cancelled: bool = False,
    ) -> RunResult:
        """写终态 + 遥测 + 事件，必要时销毁沙箱，返回 :class:`RunResult`。

        ``cancelled`` 为真时终态为 ``CANCELLED``（W6：取消 / 断连，§2.6）。
        """
        completed = utcnow()
        duration_ms = int((completed - started).total_seconds() * 1000)
        success = error_type is None and not cancelled
        tool_error_count = sum(1 for item in tool_calls if item.status == TOOL_CALL_STATUS_FAILED)

        if cancelled:
            run.status = RUN_STATUS_CANCELLED
        else:
            run.status = RUN_STATUS_SUCCESS if success else RUN_STATUS_FAILED
        run.success = success
        run.error_type = error_type
        run.completed_at = completed
        run.duration_ms = duration_ms
        run.tool_error_count = tool_error_count
        run = self._run_repository.update(run)

        if success:
            self._dispatcher.emit(
                AgentCompleted.create(
                    run_id=run.id, duration_ms=duration_ms, iterations=iterations
                ),
                run_id=run.id,
            )
        else:
            self._dispatcher.emit(
                AgentFailed.create(
                    run_id=run.id, error_type=error_type or "UNKNOWN", duration_ms=duration_ms
                ),
                run_id=run.id,
            )
            # 失败 / 取消 / 超时 → 必须回收沙箱（幂等）。
            if self._cancellation is not None and sessions:
                self._cancellation.cancel(sessions)

        # W7 / C7：显式按 run.id 落库——单实例多 Run 并发时，避免 flush 误用「最近绑定」
        # 状态而串到别的 Run（per-run 缓冲隔离见 EventDispatcher）。
        self._dispatcher.flush(run.id)
        return RunResult(
            run_id=run.id,
            status=run.status,
            success=success,
            error_type=error_type,
            duration_ms=duration_ms,
            tool_error_count=tool_error_count,
            iterations=iterations,
            final_content=final_content,
            messages=messages,
            tool_calls=tool_calls,
        )


def _format_knowledge_segment(system_prompt: str, chunks: list[KnowledgeChunk]) -> str:
    """把召回的知识片段追加到 ``system_prompt``（W5 / T2-30）。

    片段为空（全部无文本）时**原样返回**；否则追加 ``KNOWLEDGE_SECTION_HEADER`` 段，
    每条形如 ``[i] <content> (source: <source>)``（``source`` 为空则省略来源）。
    """
    entries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        content = (chunk.content or "").strip()
        if not content:
            continue
        source = (chunk.source or "").strip()
        prefix = f"[{index}] {content}"
        entries.append(f"{prefix} (source: {source})" if source else prefix)
    if not entries:
        return system_prompt
    segment = "\n".join([KNOWLEDGE_SECTION_HEADER, *entries])
    return f"{system_prompt}\n\n{segment}" if system_prompt else segment


def _format_memory_segment(system_prompt: str, records: list[MemoryRecord]) -> str:
    """把召回的记忆记录追加到 ``system_prompt``（W6 / T2-33）。

    记录为空（全部无文本）时**原样返回**；否则追加 ``MEMORY_SECTION_HEADER`` 段，
    每条形如 ``[i] <content>``（``kind`` 非空则附 ``(kind: <kind>)``）。
    """
    entries: list[str] = []
    for index, record in enumerate(records, start=1):
        content = (record.content or "").strip()
        if not content:
            continue
        kind = (record.kind or "").strip()
        prefix = f"[{index}] {content}"
        entries.append(f"{prefix} (kind: {kind})" if kind else prefix)
    if not entries:
        return system_prompt
    segment = "\n".join([MEMORY_SECTION_HEADER, *entries])
    return f"{system_prompt}\n\n{segment}" if system_prompt else segment


def _coerce_runtime_config(value: Any) -> RuntimeConfig:
    """把 ``agent_version.runtime_config``（dict / RuntimeConfig）归一化为 ``RuntimeConfig``。"""
    if isinstance(value, RuntimeConfig):
        return value
    if isinstance(value, dict):
        return RuntimeConfig.from_dict(value)
    return RuntimeConfig()


def _run_timeout_exceeded(started: Any, run_timeout_ms: int | None) -> bool:
    """判断 Run 级总超时是否已到（``run_timeout_ms`` 为 ``None`` 时视为不超时）。"""
    if run_timeout_ms is None:
        return False
    elapsed_ms = int((utcnow() - started).total_seconds() * 1000)
    return elapsed_ms >= int(run_timeout_ms)


def _stringify(value: Any) -> str:
    """把工具输出归一化为字符串（供喂模型的消息副本截断）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _as_output(value: Any) -> dict[str, Any] | None:
    """把工具输出归一化为可落 ``tool_call.output`` 的字典（**完整原文**）。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}
