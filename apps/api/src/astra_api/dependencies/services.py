"""应用服务容器（组合根产物）：``AppServices``。

🔴 本模块是 API 层构造**应用服务**的唯一入口：由 lifespan 在启动时构建，
   挂到 ``app.state.services``；Router **只**依赖此处与 :mod:`.auth`。
   本模块**不感知 mode**（唯一分流点在 ``astra_config.providers``）。

W6 / T1-31 扩展：新增 ``agent`` / ``conversation`` / ``run`` / ``agent_run`` /
``model`` / ``tool`` / ``tool_permissions`` / ``runtime`` / ``audit`` / ``idempotency``
字段 + getter；``AgentRuntime`` 由**组合根按 DI 装配**（``AgentRuntime.build``），
**不新增 ``build_runtime``**（裁定 Q6/A30）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from astra_agent import AgentService, build_agent_services
from astra_agent.bindings import load_skill_bindings
from astra_application import (
    AgentRunService,
    AuditService,
    AuthService,
    CreateAgentTaskCommand,
    EvaluationService,
    IdempotencyService,
    KnowledgeService,
    MarketplaceService,
    MemoryService,
    SettingsService,
    WorkflowService,
)
from astra_application.dto import AuditRecordDTO, SystemSettingsDTO
from astra_application.services.memory_service import resolve_memory_store
from astra_audit import RepositoryAuditSink
from astra_config import FeatureFlagService, Providers
from astra_conversation import ConversationService, RunService, build_conversation_services
from astra_core import DomainError, ErrorCode, generate_id
from astra_database import (
    SqlAuditRepository,
    SqlFeatureFlagStore,
    SqlModelProviderRepository,
    SqlModelRepository,
    SqlPluginRepository,
    SqlResourcePermissionRepository,
    SqlSandboxSessionRepository,
    SqlTaskRepository,
    SqlToolPermissionRepository,
    SqlToolRepository,
    session_scope,
)
from astra_database.repositories import (
    SqlScheduleRepository,
    SqlTaskExecutionRepository,
)
from astra_domain import (
    ADMIN_PERMISSION,
    AUDIT_OUTCOME_SUCCESS,
    Agent,
    AgentRepository,
    AgentSkillRepository,
    ApprovalRepository,
    AuditRepository,
    ConcurrencyConfig,
    PluginRepository,
    ResourcePermissionRepository,
    TaskRepository,
)
from astra_domain.repositories import ScheduleRepository, TaskExecutionRepository
from astra_evaluation import (
    EvaluationRunner,
    RunHandle,
    RunOutcome,
    ToolCallView,
    build_evaluation_repositories,
)
from astra_event import AgentCompleted, ApprovalDecided
from astra_identity import AuthorizationService, IdentityServices, build_identity_services
from astra_knowledge import (
    build_knowledge_repositories,
    build_knowledge_retriever,
    resolve_vector_search_capability,
)
from astra_mcp import (
    MCPDiscovery,
    MCPPermissionRepository,
    MCPPermissionService,
    MCPRegistry,
    MCPServer,
    MCPServerRepository,
    MCPToolRepository,
    SqlMCPPermissionRepository,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
    build_mcp_client,
    build_mcp_registry,
)
from astra_memory import build_memory_manager
from astra_model import (
    ChatMessage,
    ModelCatalogService,
    ModelCredentialBinder,
    ProviderResolver,
    ProviderRuntime,
    build_model_catalog_service,
    build_model_router,
    build_provider_resolver,
)
from astra_plugin.marketplace import (
    KIND_AGENT,
    KIND_SKILL,
    KIND_WORKFLOW,
    content_digest,
    normalize_resource,
)
from astra_runtime import (
    AgentRuntime,
    ConcurrencyController,
    RuntimePermissionChecker,
    ToolExecutor,
)
from astra_security import (
    AesGcmCipher,
    CredentialService,
    CredentialServiceDecoder,
    LoginGuard,
    PasswordHasher,
    ResourcePermissionChecker,
    SessionService,
    TokenService,
)
from astra_security.egress import SecurityEgressPolicy
from astra_security.permission import ApprovalService
from astra_security.permission.capability import (
    denied_capabilities,
    granted_capabilities,
    match_capability,
)
from astra_security.repositories import SqlApprovalRepository
from astra_skill import (
    SKILL_STATUS_ACTIVE,
    SKILL_VERSION_STATUS_PUBLISHED,
    LoadedSkill,
    Skill,
    SkillRegistry,
    SkillRepository,
    SkillVersion,
    SkillVersionRepository,
    SqlAgentSkillRepository,
    SqlSkillRepository,
    SqlSkillVersionRepository,
    build_skill_registry,
    build_skill_resolver,
)
from astra_task import SchedulerTick, Task
from astra_tool import (
    PermissionService,
    ToolRegistry,
    build_tool_registry,
    build_tool_services,
)
from astra_workflow import (
    APPROVAL_EXPIRED_ERROR,
    WORKFLOW_RUN_STATUS_RUNNING,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WorkflowRepositories,
    WorkflowRunRepository,
)
from astra_workflow.engine.concurrency import ConcurrencyGuardImpl
from astra_workflow.engine.runtime_bridge import build_runtime_bridge
from astra_workflow.factory import build_workflow_engine, build_workflow_repositories
from astra_workflow.nodes import (
    APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE,
    build_default_node_registry,
)
from astra_workflow.run import (
    EventBusWorkflowEventSink,
    InlineRunner,
    QueuedRunner,
    ReplayService,
)
from astra_workspace import (
    GitService,
    ProjectStorage,
    WorkspaceServices,
    build_workspace_services,
)
from astra_workspace.application.change_review_service import (
    ChangeReviewService,
    GitWriteCredential,
)
from astra_workspace.application.remote_task_service import (
    ACTION_EXECUTE,
    PROJECT_CLONE_TASK_TYPE,
    REMOTE_TASK_TYPE,
    TASK_RESOURCE_TYPE,
    ExecutionTaskEventSource,
    GitRefView,
    RemoteAccessDecision,
    RemotePrincipal,
    RemoteTaskService,
    RemoteTaskSpec,
)
from astra_workspace.git import parse_for_each_ref
from astra_workspace.repositories import SqlProjectRepository
from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

__all__ = [
    "AppServices",
    "build_app_services",
    "get_app_services",
    "get_identity",
    "get_workspace_services",
    "get_auth_service",
    "get_settings_service",
    "get_feature_flags",
    "get_agent_service",
    "get_conversation_service",
    "get_run_service",
    "get_agent_run_service",
    "get_model_catalog_service",
    "get_tool_registry",
    "get_tool_permission_service",
    "get_runtime",
    "get_audit_service",
    "get_idempotency_service",
    "get_permission_checker",
    "get_model_credential_binder",
    "get_provider_runtime",
    "get_provider_resolver",
    "get_agent_repository",
    "get_task_repository",
    "get_skill_repository",
    "get_skill_version_repository",
    "get_mcp_server_repository",
    "get_mcp_tool_repository",
    "get_mcp_permission_repository",
    "get_mcp_registry",
    "get_plugin_repository",
    "get_audit_repository",
    "get_workflow_service",
    "get_approval_service",
    "get_approval_repository",
    # -- W6 / T2-35（前端/API 流）
    "get_knowledge_service",
    "get_memory_service",
    # -- W8 / T2-44（Marketplace 收口）
    "get_marketplace_service",
    # -- W9 / T2-47（Evaluation 最小闭环）
    "get_evaluation_service",
    # -- W7 / T2-39（Task/Scheduler 增强）
    "get_schedule_repository",
    "get_task_execution_repository",
    "get_scheduler",
    "AppServicesDep",
]


@dataclass
class AppServices:
    """应用服务集合（组合根产物，供 Router 取用）。

    Attributes:
        providers: Provider 容器（供审计 / 诊断，业务不感知 mode）。
        identity: 身份子域服务。
        workspace: 工作区子域服务。
        credentials: 凭证安全服务（AES-GCM）。
        auth: 认证应用服务。
        settings: 设置应用服务。
        feature_flags: Feature Flag 读取服务（T0-21，纯逻辑 + 注入覆盖）。
        agent: Agent 子域服务（创建 / 版本发布 / 工具绑定）。
        conversation: 会话 / 消息服务。
        run: Run ↔ Task 挂靠服务（含重启兜底扫描）。
        agent_run: Agent / Run 用例编排器（调用 Runtime）。
        model: 模型目录服务（Provider / Model / 凭证引用）。
        provider_resolver: 执行期 Provider 绑定器（M1；把注册表原型绑定为「租户 endpoint +
            解密凭证」的具体实例；挂 ``providers.model_router``，业务不感知）。
        tool: Tool 注册表（内置工具浏览器）。
        tool_permissions: Tool 授权读写服务。
        runtime: Agent Runtime（组合根 DI 装配）。
        audit: 审计应用服务。
        idempotency: 幂等记录读写服务（``Idempotency-Key``）。
        schedules: 调度仓储（领域 ``ScheduleRepository`` Protocol；``/schedules`` 数据源）。
        task_executions: 任务执行记录仓储（领域 ``TaskExecutionRepository`` Protocol）。
        scheduler: 调度轮询执行体（``SchedulerTick``；组合根装配，``/schedules/{id}/trigger``）。
        evaluation: Evaluation 用例编排器（W9 / T2-47；逐例 ``agent_run`` 经组合根桥接 Runtime）。
        approval_repository: 审批仓储（``ApprovalRepository`` Protocol；W10 / T2-49 待办列表）。
    """

    providers: Providers
    identity: IdentityServices
    workspace: WorkspaceServices
    credentials: CredentialService
    auth: AuthService
    settings: SettingsService
    feature_flags: FeatureFlagService
    # -- W6 / T1-27 ~ T1-31 -------------------------------------------------
    agent: AgentService
    conversation: ConversationService
    run: RunService
    agent_run: AgentRunService
    model: ModelCatalogService
    tool: ToolRegistry
    tool_permissions: PermissionService
    runtime: AgentRuntime
    audit: AuditService
    idempotency: IdempotencyService
    model_credentials: ModelCredentialBinder
    provider_runtime: ProviderRuntime
    # -- M1：执行期 Provider 绑定器（组合根装配；挂 ``providers.model_router``，业务不感知） --
    provider_resolver: ProviderResolver
    # -- W3 / T2-14：capability 判定（``GET /permissions/check`` 数据源） ------
    permission: ResourcePermissionChecker
    # -- W3 / T2-17：2a API 骨架（skill / mcp / plugin / audit） --------------
    skill: SkillRepository
    skill_versions: SkillVersionRepository
    mcp: MCPServerRepository
    mcp_tools: MCPToolRepository
    mcp_permissions: MCPPermissionRepository
    mcp_permission_service: MCPPermissionService
    mcp_registry: MCPRegistry
    mcp_discovery: MCPDiscovery
    mcp_client_factory: Callable[[MCPServer], Any]
    plugins: PluginRepository
    audit_repository: AuditRepository
    audit_sink: RepositoryAuditSink
    # -- 领域 Protocol 直取（T1-28 / T1-29；Router 不感知 ORM，仅面向 Protocol） --
    agent_repository: AgentRepository
    tasks: TaskRepository
    # -- W4 / T2-25：Workflow 用例编排（API + SSE；Router 只经本槽取用） --------
    workflow: WorkflowService
    # -- W4 / T2-26：审批机制（组合根装配 ApprovalService + 决议续跑） ----------
    approval: ApprovalService
    # -- W10 / T2-49：审批仓储装配位（**复用** ApprovalService 的同一实例；零新构造） -----
    approval_repository: ApprovalRepository
    # -- W6 / T2-35（前端/API 流）：Knowledge / Memory 用例编排 -----------------
    # -- W6 frontend/api: knowledge/memory --
    knowledge: KnowledgeService
    memory: MemoryService
    # -- W8 / T2-44：Marketplace 用例编排（导入 / 导出；Router 只经本槽取用） -----
    marketplace: MarketplaceService
    # -- W9 / T2-47：Evaluation 用例编排（任务集 / 用例 / 评测 / 对比；Router 只经本槽取用） --
    evaluation: EvaluationService
    # -- W7 / T2-39：Task/Scheduler 增强（调度仓储 / 执行记录 / 轮询执行体） ------
    schedules: ScheduleRepository
    task_executions: TaskExecutionRepository
    scheduler: SchedulerTick
    # -- R3 / T2-60：远程 Task / Project 用例（scope 校验 + 事件游标服务） -------
    remote_tasks: RemoteTaskService
    # -- R3 / T2-61：变更审阅（受限 Diff / 显式 Apply / 显式 Push） --------------
    change_review: ChangeReviewService


def build_app_services(providers: Providers) -> AppServices:
    """依 Providers 构建应用服务集合。

    Args:
        providers: lifespan 装配的 Provider 容器。

    Returns:
        :class:`AppServices`。

    Raises:
        RuntimeError: 数据库 Provider 未装配，或 EventBus / RunService 无法装配。
        DomainError: 缺少 ``ASTRA_SECRET_KEY``（``CONFIGURATION_ERROR``）。
    """
    if providers.database is None:
        raise RuntimeError("Database Provider 未装配，无法构建应用服务")
    settings = providers.settings
    session_factory = providers.database.session_factory

    identity = build_identity_services(session_factory)
    workspace = build_workspace_services(session_factory)

    cipher = AesGcmCipher.from_secret(settings.secret_key)
    credentials = CredentialService(session_factory, cipher)

    token_service = TokenService(
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )
    session_service = SessionService(
        session_factory,
        token_service,
        session_ttl_seconds=settings.refresh_token_ttl_seconds,
    )
    login_guard = LoginGuard(
        session_factory,
        max_attempts=settings.login_max_attempts,
        lock_seconds=settings.login_lock_seconds,
    )
    auth = AuthService(
        identity=identity,
        password_hasher=PasswordHasher(),
        token_service=token_service,
        session_service=session_service,
        login_guard=login_guard,
        access_token_ttl_seconds=settings.access_token_ttl_seconds,
    )

    system = SystemSettingsDTO(
        mode=settings.mode,
        app_name=settings.app_name,
        app_version=settings.app_version,
    )
    settings_service = SettingsService(
        system=system,
        users=identity.users,
        credentials=credentials,
    )

    # Feature Flag（T0-21 / D7）：组装在组合根完成。
    feature_flags = FeatureFlagService(
        store=SqlFeatureFlagStore(session_factory),
        overrides=settings.feature_flags,
    )

    # -- W6：Agent / Conversation / Run / Model / Tool / Runtime / 审计 / 幂等 ----
    task_repository = SqlTaskRepository(session_factory)
    sandbox_sessions = SqlSandboxSessionRepository(session_factory)

    conversation_services = build_conversation_services(
        session_factory,
        task_repository=task_repository,
        sandbox_repository=sandbox_sessions,
        sandbox_provider=providers.sandbox,
    )
    run_service = conversation_services.run_service
    if run_service is None:  # pragma: no cover - 组合根恒传 task_repository
        raise RuntimeError("RunService 未装配（需 task_repository）")

    # Skill 绑定解析（W3 / T2-09.1 · §19.2.3）：Skill 的 SQL 仓储 / ``agent_skill`` 绑定仓储
    # 均落 ``astra_skill``，经组合根注入（避免 ``agent→skill`` / ``skill→agent`` 包依赖边）。
    skill_repository = SqlSkillRepository(session_factory)
    agent_skill_repository = SqlAgentSkillRepository(session_factory)
    agent_services = build_agent_services(
        session_factory, agent_skill_repository=agent_skill_repository
    )

    model_catalog = build_model_catalog_service(
        provider_repository=SqlModelProviderRepository(session_factory),
        model_repository=SqlModelRepository(session_factory),
        registry=providers.model_providers,
    )

    # 模型凭证复用（T1-30 / C-07）：仅存引用 + 显式可审计解密（明文仅内存）。
    model_credentials = ModelCredentialBinder(
        provider_repository=SqlModelProviderRepository(session_factory)
    )

    # Tool 注册表：优先取 Providers 装配；缺失时按配置就地装配（非 mode 分支）。
    tool_registry = providers.tool_registry or build_tool_registry(settings)
    # 资源权限仓储（运行期**唯一**判定源落点，W3 / T2-13）：``/tools/permissions`` 的
    # grant / revoke / list 与运行期 ``ResourcePermissionChecker`` 共用同一 ``resource_permission``
    # 表（裁定 §20 Erratum-2）。同一实例既供 Tool 授权读写、亦供判定链读取。
    resource_permission_repository = SqlResourcePermissionRepository(session_factory)
    tool_permissions = build_tool_services(
        # ``SqlToolRepository`` 的 ``add``/``get`` 返回 ``Tool | ToolVersion`` 并集，与领域
        # ``ToolRepository`` Protocol 的 ``add(entity: Tool)`` 存在既有协变缺口（W4 已知）：
        # 该缺口在 CI 口径（``mypy packages apps``）下为 load-bearing，
        # ``ignore`` **必需**（运行时可用）。
        tool_repository=SqlToolRepository(session_factory),  # type: ignore[arg-type]
        tool_permission_repository=SqlToolPermissionRepository(session_factory),
        # ★ W3 / T2-13 补丁（裁定 §20）：授权写 / 读重指向 ``resource_permission``。
        resource_permission_repository=resource_permission_repository,
        # 授权写入时把持久化 ``tool`` 行 id 归一到运行期注册表条目（实例级授权方可命中）。
        tool_registry=tool_registry,
    )

    # Model Router：优先取 Providers 装配；缺失时就地装配（内容等价）。
    model_router = providers.model_router or build_model_router(settings)

    event_bus = providers.event_bus
    if event_bus is None:  # pragma: no cover - build_providers 恒装配
        raise RuntimeError("EventBus Provider 未装配，无法构建 Runtime")

    # Skill 解析（W3 / T2-09.1 · 裁定 §19.2.3）：**绑定驱动** —— 组合根构造 ``bindings_provider``
    # （按 ``agent_version`` 的已启用绑定 → ``skill.name`` → 注册表生效版本），经
    # ``build_skill_resolver`` 注入 runtime（补 F28「生产恒走 NullSkillResolver」缺口）。
    skill_registry: SkillRegistry = providers.skill_registry or build_skill_registry(settings)
    skill_resolver = build_skill_resolver(
        skill_registry,
        bindings_provider=build_skill_bindings_provider(
            skill_repository=skill_repository,
            agent_skill_repository=agent_skill_repository,
            skill_registry=skill_registry,
        ),
    )

    # AgentRuntime 组合根 DI 装配（裁定 §6.3；不新增 build_runtime）。
    # W8 / A36：``AgentRuntime.build`` **不传** ``permission_checker``——装配期默认仅为回退
    # （deny-by-default）；per-agent 授权经 ``RunContext.permission_checker`` **per-run** 注入。
    #
    # W5 / T2-30（B5 / B6 / E3 补 F28 型缺口）：Knowledge Retriever（RP-02 真实实现）经组合根
    # 装配注入——``capability.vector_search`` 三态按 **dialect + pg_extension 确定性探测**解析
    # （**非 try/except 推断**）；不接线则生产恒走 ``NullKnowledgeRetriever``（知识段恒空）。
    vector_search = resolve_vector_search_capability(
        explicit=settings.capability.vector_search,
        session_factory=session_factory,
    )
    knowledge_retriever = build_knowledge_retriever(
        session_factory=session_factory,
        model_router=model_router,
        vector_search=vector_search,
        embedding_dimensions=settings.capability.embedding_dimensions,
    )

    # -- W6 backend: memory -------------------------------------------------
    # 记忆管理器（RP-03 真实实现）经组合根装配注入 runtime（补 F28 型缺口，W6 裁定 B8）：
    # 不接线 → 生产恒走 ``NullMemoryManager``（recall 恒 []、记忆永不回灌上下文）。
    # ``vector_search`` 复用上方 knowledge 的**确定性探测**产物（dialect + pg_extension，非
    # try/except 推断）；``providers.memory_store`` 已按同一能力在 Provider 层装配（T2-34）。
    memory_manager = build_memory_manager(
        session_factory=session_factory,
        settings=settings.memory,
        model_router=model_router,
        extraction_model_config=_memory_extraction_model_config(settings),
        vector_search=vector_search,
        embedding_dimensions=settings.capability.embedding_dimensions,
        store=providers.memory_store,
    )
    # -- W6 backend: memory (end) -------------------------------------------
    runtime = AgentRuntime.build(
        run_repository=conversation_services.runs,
        message_repository=conversation_services.messages,
        tool_call_repository=conversation_services.tool_calls,
        event_repository=conversation_services.events,
        event_bus=event_bus,
        model_router=model_router,
        tool_registry=tool_registry,
        sandbox_provider=providers.sandbox,
        skill_resolver=skill_resolver,
        knowledge_retriever=knowledge_retriever,
        memory_manager=memory_manager,
    )

    def _resolve_permission_checker(agent_id: str) -> RuntimePermissionChecker:
        """按 Agent 解析 Tool 授权 → 装配 Runtime 校验器（per-run）。

        W3 / T2-13（裁定 §2.2）：运行期**唯一**判定源 ＝ ``ResourcePermissionChecker``（组合根
        注入）。主体（``agent_id``）经 ``ToolContext.agent_id`` 在**每次判定**解析，故返回**共享的**
        无状态适配器（只读、无缓存、不写回共享单例）。
        """
        return runtime_permission_checker

    agent_run = AgentRunService(
        agents=agent_services.agent_service,
        runs=conversation_services.runs,
        runtime=runtime,
        run_service=run_service,
        concurrency=ConcurrencyController(),
        sandbox_sessions=sandbox_sessions,
        sandbox_provider=providers.sandbox,
        events=conversation_services.events,
        permission_checker_resolver=_resolve_permission_checker,
    )

    idempotency = IdempotencyService(runs=conversation_services.runs, tasks=task_repository)

    audit = AuditService(repository=SqlAuditRepository(session_factory))

    # 权限单一判定链（W3 / T2-13 · 裁定 §2.2）：运行期**唯一**判定源经组合根注入。
    # ``ResourcePermissionChecker`` 读 ``resource_permission`` + ``agent_tool.permission_scope``
    # （只收窄）；以 ``RuntimePermissionChecker`` 形态注入 runtime（ToolExecutor / AgentRuntime
    # 签名零改）。适配器为**薄委托、零逻辑**——判定链唯一实现仍在 ``astra_security``。
    resource_checker = ResourcePermissionChecker(
        repository=resource_permission_repository,
        audit=SqlAuditRepository(session_factory),
    )
    runtime_permission_checker = _ResourcePermissionCheckerAdapter(resource_checker)

    # 显式可审计解密（T1-30）：明文仅内存；解密写 ``audit_log``。
    provider_runtime = ProviderRuntime(
        provider_repository=SqlModelProviderRepository(session_factory),
        decoder=CredentialServiceDecoder(credentials, cipher),
        audit=_audit_recorder(audit),
    )

    # M1 · 执行期 Provider 绑定（组合根**唯一**装配出口，H5）：把「注册表原型 + 租户行 +
    # 解密凭证」合流器注入 ``model_router``（**reference** 语义，Runtime 装配零改）。
    # 🔴 无 ``if mode ==``（H3）：解密唯一经 ``provider_runtime``（写审计），明文仅内存（H4）。
    provider_resolver = build_provider_resolver(
        provider_repository=SqlModelProviderRepository(session_factory),
        provider_runtime=provider_runtime,
    )
    model_router.bind_provider_resolver(provider_resolver)

    # -- W3 / T2-17：2a API 骨架（skill / mcp / plugin / audit） -------------
    # Router 经 ``AppServices`` 面向**领域 Protocol** 取用（N-8，无 ORM 直调）。
    # ``skill_repository`` 已在 T2-09.1 接线处构造（供解析链复用）。
    skill_version_repository = SqlSkillVersionRepository(session_factory)
    mcp_server_repository = SqlMCPServerRepository(session_factory)
    mcp_tool_repository = SqlMCPToolRepository(session_factory)
    mcp_permission_repository = SqlMCPPermissionRepository(session_factory)
    # MCP 授权读写服务（W3 / T2-13 补丁 · 裁定 §21.4 X1/X2）：``/mcp/permissions`` 重指向
    # ``resource_permission``（运行期**唯一**判定源），先做 ``mcp_tool_id → tool 行 id`` 映射；
    # 复用**同一** ``SqlResourcePermissionRepository`` 实例（与运行期判定链同源）。
    # ``mcp_permission`` 仓储（``mcp_permission_repository``）保留为 deprecated 默认策略模板兜底。
    mcp_permission_service = MCPPermissionService(
        mcp_permission_repository=mcp_permission_repository,
        mcp_tool_repository=mcp_tool_repository,
        mcp_server_repository=mcp_server_repository,
        # ``SqlToolRepository`` 的 ``add``/``get`` 返回 ``Tool | ToolVersion`` 并集，与领域
        # ``ToolRepository`` Protocol 的 ``add(entity: Tool)`` 存在既有协变缺口（W4 已知）：
        # 该缺口在 CI 口径（``mypy packages apps``）下为 load-bearing，
        # ``ignore`` **必需**（运行时可用）。
        tool_repository=SqlToolRepository(session_factory),  # type: ignore[arg-type]
        resource_permission_repository=resource_permission_repository,
    )
    mcp_registry = providers.mcp_registry or build_mcp_registry(settings)
    mcp_discovery = MCPDiscovery(tool_repository=mcp_tool_repository)
    plugin_repository = SqlPluginRepository(session_factory)
    audit_repository = SqlAuditRepository(session_factory)

    def _mcp_client_factory(server: MCPServer) -> Any:
        """按 Server 配置装配 MCP 客户端（组合根；测试可覆写 ``services.mcp_client_factory``）。"""
        return build_mcp_client(server, settings=settings)

    # 基础审计消费（T2-17 · §7.3）：写库经注入领域 Protocol；失败 → 本地落盘 + 告警。
    audit_settings = settings.audit
    audit_sink = RepositoryAuditSink(
        repository=audit_repository,
        fallback_dir=audit_settings.fallback_dir or None,
        fallback_enabled=audit_settings.fallback_enabled,
        logger=logging.getLogger("astra_api.audit"),
    )

    # -- W4 / T2-25：Workflow 域（组合根装配引擎 + 用例编排服务） ----------------
    # 分层：``workflow`` 为能力包（仅禁 Web）；引擎经 ``build_workflow_engine`` 装配，
    # 节点内 ``TOOL`` / ``MCP`` **必过** ``ToolExecutor``（权限单一判定链）+ ``EgressPolicy``
    # （唯一出网入口）；工作流级持久化由 ``astra_workflow`` 经注入仓储完成（runtime 零改）。
    workflow_repositories = build_workflow_repositories(session_factory)
    # T2-26 审批机制（**零迁移**）：SQL 仓储 + 机制服务（迁移 ``0010`` 已建 ``approval`` 表）。
    # ``HUMAN_APPROVAL`` 节点依赖 ``astra_domain.ApprovalGateway`` Protocol（不 import
    # ``astra_security``），真实 ``ApprovalService`` 由**组合根**注入。
    approval_repository = SqlApprovalRepository(session_factory)
    approval_service = ApprovalService(approval_repository, event_bus=event_bus)
    workflow_concurrency = ConcurrencyGuardImpl(ConcurrencyConfig())
    workflow_bridge = build_runtime_bridge(
        tool_executor=ToolExecutor(
            tool_registry=tool_registry,
            permission_checker=runtime_permission_checker,
        ),
        checker_resolver=_resolve_permission_checker,
        egress_policy=SecurityEgressPolicy(),
    )
    workflow_node_registry = build_default_node_registry(
        bridge=workflow_bridge,
        # T2-26：以真实 ``ApprovalService`` 装配 ``ApprovalGateway``（替换 T2-25 占位）。
        gateway=approval_service,
        concurrency=workflow_concurrency,
    )

    def _workflow_id_resolver(run: Any) -> str:
        """由运行经固定引用版本回读 ``workflow_id``（不可得 → 空，**不伪造**）。"""
        version = workflow_repositories.versions.get(
            str(getattr(run, "workflow_version_id", "") or "")
        )
        return str(getattr(version, "workflow_id", "") or "")

    workflow_sink = EventBusWorkflowEventSink(event_bus, workflow_id_resolver=_workflow_id_resolver)
    workflow_engine = build_workflow_engine(
        workflow_node_registry,
        versions=workflow_repositories.versions,
        sink=workflow_sink,
        bridge=workflow_bridge,
        concurrency=workflow_concurrency,
    )
    workflow_inline = InlineRunner(
        workflow_engine,
        workflow_repositories.runs,
        node_runs=workflow_repositories.node_runs,
        versions=workflow_repositories.versions,
        sink=workflow_sink,
    )
    # 后期绑定：QueuedRunner 的执行回调即 Application ``WorkflowService.execute``
    # （同 ``agent.run`` 的 ``execute_agent`` 范式，F17）；用可变引用打破构造环。
    workflow_ref: dict[str, WorkflowService] = {}
    workflow_queued = QueuedRunner(
        workflow_repositories.runs,
        tasks=task_repository,
        queue=providers.task_queue,
        executor=lambda run_id: workflow_ref["service"].execute(run_id),
    )
    workflow_service = WorkflowService(
        workflows=workflow_repositories.workflows,
        versions=workflow_repositories.versions,
        runs=workflow_repositories.runs,
        node_runs=workflow_repositories.node_runs,
        inline=workflow_inline,
        queued=workflow_queued,
        replay_service=ReplayService(
            workflow_repositories.runs,
            workflow_repositories.node_runs,
            versions=workflow_repositories.versions,
        ),
    )
    workflow_ref["service"] = workflow_service

    # T2-26：订阅审批决议 → 续跑 / 置终态（``ApprovalDecided`` → ``WorkflowService.resume``，
    # 裁定 §3.4 / §4）。载荷仅含 ``approval_id``，经 ``ApprovalService.get`` 反查 ``subject_ref``。
    _subscribe_approval_resume(
        event_bus=event_bus,
        approval_service=approval_service,
        workflow_service=workflow_service,
        runs=workflow_repositories.runs,
        sink=workflow_sink,
    )

    # -- W6 backend: memory -------------------------------------------------
    # 订阅 ``AgentCompleted`` → 触发记忆抽取（W6 裁定 B2 / §1.3-②：「LLM 抽取落应用层，
    # Runtime 仅 ``recall``（RP-03）」）；**异常隔离**（抽取失败不影响 Run 终态）。
    _subscribe_memory_extraction(
        event_bus=event_bus,
        memory_manager=memory_manager,
        runs=conversation_services.runs,
        messages=conversation_services.messages,
    )
    # -- W6 backend: memory (end) -------------------------------------------

    # -- W6 / T2-35（前端/API 流）：Knowledge / Memory 用例服务装配 --------------
    # -- W6 frontend/api: knowledge/memory --
    # Knowledge：复用上面已装配的 RP-02 检索器（``knowledge_retriever``）+ 五仓储（CRUD 用）。
    # Memory：优先采用组合根已装配的 ``providers.memory_store``（T2-34 Provider 层按同一
    # capability 装配的 ``MemoryStore``），经 ``_SearchStoreAdapter`` 适配为用例端口
    # （浏览走 ``search``、删除经 ``repository.get`` 预检得 404 语义）；缺失时回退占位存储。
    knowledge_repositories = build_knowledge_repositories(session_factory)
    knowledge_service = KnowledgeService(
        knowledge_bases=knowledge_repositories.knowledge_bases,
        documents=knowledge_repositories.documents,
        retriever=knowledge_retriever,
    )
    memory_service = MemoryService(
        store=resolve_memory_store(
            session_factory,
            store=providers.memory_store,
            vector_search=vector_search,
            embedding_dimensions=settings.capability.embedding_dimensions,
        )
    )

    # -- W8 / T2-44：Marketplace（导入 / 导出）用例编排 --------------------------
    # 分层：编排落 astra_application（新边 application→plugin，R4）；资源创建 / 读取经
    # **注入** ResourceImporter（组合根适配既有 agent / skill / workflow 用例；R4/N-8）。
    marketplace_service = MarketplaceService(
        importer=_MarketplaceResourceImporter(
            agent_service=agent_services.agent_service,
            agent_repository=agent_services.agents,
            skill_repository=skill_repository,
            skill_version_repository=skill_version_repository,
            workflow_service=workflow_service,
            workflow_repositories=workflow_repositories,
        ),
        permission=_IdentityPermissionChecker(identity.authorization),
    )

    # -- W9 / T2-47：Evaluation（任务集 / 用例 / 批量评测 / 回归对比）用例编排 ----
    # 分层：编排落 astra_application（新边 application→evaluation，R1）；逐例 ``agent_run``
    # 创建复用正式 Runtime / 权限 / Sandbox——真实桥接由**组合根**以 ``AgentRunLauncher``
    # 实现注入（能力包保持松耦合、可注入 fake 单测；R1/§5.1）。
    evaluation_repositories = build_evaluation_repositories(session_factory)
    evaluation_launcher = _EvaluationRunLauncher(
        conversation_service=conversation_services.conversation_service,
        agent_run=agent_run,
        runs=conversation_services.runs,
        tool_calls=conversation_services.tool_calls,
    )
    evaluation_service = EvaluationService(
        datasets=evaluation_repositories.datasets,
        cases=evaluation_repositories.cases,
        runs=evaluation_repositories.runs,
        results=evaluation_repositories.results,
        runner=EvaluationRunner(
            datasets=evaluation_repositories.datasets,
            cases=evaluation_repositories.cases,
            runs=evaluation_repositories.runs,
            results=evaluation_repositories.results,
            launcher=evaluation_launcher,
        ),
        permission=_IdentityPermissionChecker(identity.authorization),
    )

    # -- W7 / T2-39：Task/Scheduler 增强（调度仓储 / 执行记录 / 轮询执行体） ------
    # 分层：``astra_task`` 保持**零 ORM**（R2）；调度 / 执行记录的 ORM + SQL 一律落
    # ``astra_database``（``SqlScheduleRepository`` / ``SqlTaskExecutionRepository``），
    # 经**领域 Protocol** 注入 ``SchedulerTick``（组合根装配，Router 只经 ``AppServices`` 取用）。
    schedule_repository = SqlScheduleRepository(session_factory)
    task_execution_repository = SqlTaskExecutionRepository(session_factory)
    scheduler_runner = SchedulerTick(
        schedules=schedule_repository,
        executions=task_execution_repository,
    )

    # -- R3 / T2-60：远程 Task / Project 用例（scope 校验 + 事件游标服务） ------
    # 分层：能力包 ``astra_workspace.application.RemoteTaskService`` **零** Web / **零**
    # ``astra_runtime`` / **零** ORM；授权 / 审计 / 提交 / 克隆派发 / 事件源**全部经注入适配器**
    # （组合根，C-7 单写者）。A-14：创建 / 取消 / Diff / Download 以 ``EXECUTE`` + capability
    # 细分校验，**不新增** action 枚举；``TASK`` 资源类型仅为字符串（无 DB 枚举迁移）。
    remote_projects = _SessionScopedProjectRepository(session_factory)
    remote_authorizer = _RemoteTaskAuthorizer(
        authorization=identity.authorization,
        permissions=resource_permission_repository,
    )
    remote_audit = _RemoteAuditSink(audit)
    # R5 补全轮（F2/F3）：Sandbox / 受管目录 / Git 用例**抽局部变量**，供 RemoteTaskService
    # （ArtifactReader / GitRefsProvider）与 ChangeReviewService **复用同一实例**（单一裁决点）。
    sandbox_provider = providers.sandbox
    project_storage = ProjectStorage(settings.workspace_root)
    git_service = GitService(sandbox_provider) if sandbox_provider is not None else None
    remote_task_service = RemoteTaskService(
        tasks=task_repository,
        task_executions=task_execution_repository,
        projects=remote_projects,
        authorizer=remote_authorizer,
        audit=remote_audit,
        events=ExecutionTaskEventSource(task_execution_repository),
        submitter=_RemoteTaskSubmitter(
            tasks=task_repository,
            task_queue=providers.task_queue,
            # R5 补全轮（F8a/F8c）：执行期限额经**组合根**注入（提交面强制点：pending 上限 +
            # deadline 落载荷）。能力包 / 公开签名零改（行为收紧）。
            max_pending_per_user=settings.remote_execution.max_pending_per_user,
            max_duration_seconds=settings.remote_execution.max_duration_seconds,
        ),
        clone_dispatcher=_ProjectCloneDispatcher(
            tasks=task_repository,
            task_queue=providers.task_queue,
        ),
        # R5A-01(a) / F2：Artifact 下载经注入 **Storage** 读取器（key 直通；LocalFileStorage 自带
        # containment）——装配后下载端点可达（此前恒 503）。
        artifact_reader=_StorageArtifactReader(providers.storage),
        # R5A-01(b) / F3：Git 引用查询仅经 Sandbox（``GitService.for_each_ref``）；仅当装配
        # Sandbox 时注入（对齐 change_review 的 ``GitService(sandbox) if sandbox
        # else None`` 体例）。
        git_refs_provider=(
            _SandboxGitRefsProvider(
                projects=remote_projects,
                sandbox=sandbox_provider,
                storage=project_storage,
                git_service=git_service,
            )
            if sandbox_provider is not None and git_service is not None
            else None
        ),
    )

    # -- R3 / T2-61：变更审阅（受限 Diff / 显式 Apply / 显式 Push） -------------
    # 分层：能力包 ``astra_workspace.application.ChangeReviewService`` **零** Web / **零**
    # ``astra_runtime`` / **零** ORM；Git **仅经 Sandbox**（``GitService``）；``checkout_ref``
    # 经 ``ProjectStorage``（``ManagedWorkspacePaths``）canonical containment 还原（前向硬约束）。
    # 授权 / 审计复用 T2-60 同实例；写凭证经 ``_ProjectGitCredentialProvider`` **短时**解密。
    change_review_service = ChangeReviewService(
        tasks=task_repository,
        executions=task_execution_repository,
        projects=remote_projects,
        git=git_service,
        sandbox=sandbox_provider,
        storage=project_storage,
        authorizer=remote_authorizer,
        audit=remote_audit,
        credentials=_ProjectGitCredentialProvider(
            projects=remote_projects,
            decoder=CredentialServiceDecoder(credentials, cipher),
        ),
    )

    return AppServices(
        providers=providers,
        identity=identity,
        workspace=workspace,
        credentials=credentials,
        auth=auth,
        settings=settings_service,
        feature_flags=feature_flags,
        agent=agent_services.agent_service,
        conversation=conversation_services.conversation_service,
        run=run_service,
        agent_run=agent_run,
        model=model_catalog,
        tool=tool_registry,
        tool_permissions=tool_permissions,
        runtime=runtime,
        audit=audit,
        idempotency=idempotency,
        model_credentials=model_credentials,
        provider_runtime=provider_runtime,
        provider_resolver=provider_resolver,
        permission=resource_checker,
        skill=skill_repository,
        skill_versions=skill_version_repository,
        mcp=mcp_server_repository,
        mcp_tools=mcp_tool_repository,
        mcp_permissions=mcp_permission_repository,
        mcp_permission_service=mcp_permission_service,
        mcp_registry=mcp_registry,
        mcp_discovery=mcp_discovery,
        mcp_client_factory=_mcp_client_factory,
        plugins=plugin_repository,
        audit_repository=audit_repository,
        audit_sink=audit_sink,
        agent_repository=agent_services.agents,
        tasks=task_repository,
        workflow=workflow_service,
        approval=approval_service,
        # -- W10 / T2-49：复用 ApprovalService 的同一 SQL 仓储实例（零新构造）
        approval_repository=approval_repository,
        # -- W6 / T2-35（前端/API 流）
        # -- W6 frontend/api: knowledge/memory --
        knowledge=knowledge_service,
        memory=memory_service,
        # -- W8 / T2-44（Marketplace 收口）
        marketplace=marketplace_service,
        # -- W9 / T2-47（Evaluation 最小闭环）
        evaluation=evaluation_service,
        # -- W7 / T2-39（Task/Scheduler 增强）
        schedules=schedule_repository,
        task_executions=task_execution_repository,
        scheduler=scheduler_runner,
        # -- R3 / T2-60（远程 Task / Project 用例）
        remote_tasks=remote_task_service,
        # -- R3 / T2-61（变更审阅：受限 Diff / 显式 Apply / 显式 Push）
        change_review=change_review_service,
    )


def build_skill_bindings_provider(
    *,
    skill_repository: SkillRepository,
    agent_skill_repository: AgentSkillRepository,
    skill_registry: SkillRegistry,
) -> Callable[[str], list[LoadedSkill]]:
    """构造**绑定驱动**的 ``bindings_provider``（W3 / T2-09.1 · 裁定 §19.2.3）。

    返回 ``(agent_version_id) -> list[LoadedSkill]``：取该 ``AgentVersion`` 的绑定
    （``load_skill_bindings``，按 ``id`` 升序）→ **过滤 ``enabled=True``** → 经
    ``SkillRepository.get(skill_id)`` 取 ``name`` → ``registry.resolve(name)`` 取**生效版本**
    ``LoadedSkill``。``skill`` 缺失 / 未注册时**跳过**（宽松，不中断解析）。

    🔴 本函数在**组合根**（``apps/api``）中，故可同时依赖 ``astra_agent`` 的绑定解析与
    ``astra_skill`` 的仓储 / 注册表——``astra_skill`` **不** import ``astra_agent``（守 R2 §2.1）。

    Args:
        skill_repository: Skill 领域仓储（``skill_id`` → ``Skill``）。
        agent_skill_repository: ``agent_skill`` 绑定仓储（领域 Protocol）。
        skill_registry: 已装配的 Skill 注册表（解析生效版本）。

    Returns:
        ``bindings_provider`` 回调。
    """

    def _provider(agent_version_id: str) -> list[LoadedSkill]:
        """返回某 ``AgentVersion`` 已启用绑定对应的生效 ``LoadedSkill``（按绑定顺序）。"""
        resolved: list[LoadedSkill] = []
        for binding in load_skill_bindings(agent_skill_repository, agent_version_id):
            if not getattr(binding, "enabled", True):
                continue
            skill = skill_repository.get(binding.skill_id)
            if skill is None:
                continue
            loaded = skill_registry.resolve(skill.name)
            if loaded is not None:
                resolved.append(loaded)
        return resolved

    return _provider


def _audit_recorder(audit: AuditService) -> Callable[[dict[str, Any]], None]:
    """构造 ``ProviderRuntime`` 的解密审计回调（写 ``audit_log``；失败不阻断）。

    Args:
        audit: 审计应用服务。

    Returns:
        接收结构化审计载荷的回调（**绝不**包含明文字段）。
    """

    def _record(payload: dict[str, Any]) -> None:
        try:
            audit.record(
                AuditRecordDTO(
                    tenant_id=str(payload.get("tenant_id", "")),
                    action=str(payload.get("action", "model.credential.decrypt")),
                    request_id=generate_id(),
                    run_id=payload.get("run_id"),
                    resource_type=payload.get("resource_type"),
                    resource_id=payload.get("resource_id"),
                    outcome=str(payload.get("outcome", AUDIT_OUTCOME_SUCCESS)),
                    metadata=dict(payload.get("metadata") or {}),
                )
            )
        except Exception:  # noqa: BLE001 - 审计失败不得阻断运行时解密
            pass

    return _record


#: 审批被拒后 Run 的终态错误码字面值（W4 裁定 §3.2：``REJECTED → FAILED``）。
APPROVAL_REJECTED_ERROR = "APPROVAL_REJECTED"

#: 决议状态字面值（与 ``astra_domain.ApprovalStatus`` 同口径，避免拼写漂移）。
_APPROVAL_STATUS_APPROVED = "APPROVED"
_APPROVAL_STATUS_REJECTED = "REJECTED"
_APPROVAL_STATUS_EXPIRED = "EXPIRED"

#: 允许置 ``FAILED`` 的运行状态（对齐 ``WorkflowRun`` 状态机，``PENDING`` 不可直置失败）。
_FAILABLE_RUN_STATUSES: frozenset[str] = frozenset(
    {WORKFLOW_RUN_STATUS_RUNNING, WORKFLOW_RUN_STATUS_WAITING_APPROVAL}
)


def _subscribe_approval_resume(
    *,
    event_bus: Any,
    approval_service: ApprovalService,
    workflow_service: WorkflowService,
    runs: WorkflowRunRepository,
    sink: EventBusWorkflowEventSink | None = None,
) -> Callable[[Any], None]:
    """订阅 ``ApprovalDecided`` → 审批决议续跑 / 置终态（W4 / T2-26；裁定 §3.4）。

    组合根**唯一**接线点：``ApprovalDecided`` 载荷仅含 ``approval_id`` / ``status`` /
    ``decided_by``（**不含** ``workflow_run_id``），故必须经 :meth:`ApprovalService.get`
    反查审批记录 → 取 ``subject_ref``（格式 ``"{workflow_run_id}:{node_key}"``）得运行标识。

    - ``APPROVED`` → ``WorkflowService.resume(workflow_run_id)``（自挂起节点续跑，裁定 §3.4）；
    - ``REJECTED`` / ``EXPIRED`` → 运行置终态 ``FAILED``（``error=APPROVAL_REJECTED`` /
      ``APPROVAL_EXPIRED``；裁定 §3.2 / §9-c）。🔴 ``WorkflowService`` 无 ``fail`` 用例，
      能力包 / 应用包**零改**——故此处**直接经 WorkflowRun 仓储**置终态（**最小加性**落点）。

    Args:
        event_bus: 事件总线（``subscribe``）。
        approval_service: 审批机制服务（``get`` 反查主体）。
        workflow_service: Workflow 用例编排器（``resume`` 续跑）。
        runs: WorkflowRun 仓储（置终态用）。
        sink: 事件出口（失败时 emit ``workflow.failed``；可空）。

    Returns:
        已注册的处理器（供测试 / 观测；重复发布下幂等）。
    """

    def _on_approval_decided(event: Any) -> None:
        """处理一条 ``ApprovalDecided``：反查运行 → 续跑 / 置终态。"""
        payload = dict(getattr(event, "payload", {}) or {})
        approval_id = str(payload.get("approval_id", "") or "")
        if not approval_id:
            return
        raw_status = payload.get("status", "")
        status = str(getattr(raw_status, "value", raw_status) or "").upper()
        approval = approval_service.get(approval_id)
        if approval is None:
            return
        # 仅处理 Workflow 节点发起的审批（其余主体类型不在本订阅职责内）。
        if str(getattr(approval, "subject_type", "") or "") != APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE:
            return
        subject_ref = str(getattr(approval, "subject_ref", "") or "")
        workflow_run_id = subject_ref.split(":", 1)[0]
        if not workflow_run_id:
            return
        if status == _APPROVAL_STATUS_APPROVED:
            workflow_service.resume(workflow_run_id)
            return
        if status not in {_APPROVAL_STATUS_REJECTED, _APPROVAL_STATUS_EXPIRED}:
            return
        _fail_workflow_run(
            workflow_run_id,
            runs=runs,
            sink=sink,
            error=(
                APPROVAL_EXPIRED_ERROR
                if status == _APPROVAL_STATUS_EXPIRED
                else APPROVAL_REJECTED_ERROR
            ),
        )

    event_bus.subscribe(ApprovalDecided.type, _on_approval_decided)
    return _on_approval_decided


def _fail_workflow_run(
    workflow_run_id: str,
    *,
    runs: WorkflowRunRepository,
    error: str,
    sink: EventBusWorkflowEventSink | None = None,
) -> None:
    """把挂起 / 运行中的 ``WorkflowRun`` 置终态 ``FAILED``（幂等；终态 / 不可置失败跳过）。

    Args:
        workflow_run_id: 运行标识。
        runs: WorkflowRun 仓储。
        error: 失败原因字面值（``APPROVAL_EXPIRED`` / ``APPROVAL_REJECTED``）。
        sink: 事件出口（非空则 emit ``workflow.failed``）。
    """
    run = runs.get(workflow_run_id)
    if run is None or run.is_terminal or run.status not in _FAILABLE_RUN_STATUSES:
        return
    run.fail(error=error)
    runs.update(run)
    if sink is not None:
        sink.run_failed(run)


# -- W6 backend: memory -----------------------------------------------------

#: 记忆抽取事件订阅日志器（隔离失败仅告警）。
_MEMORY_LOGGER = logging.getLogger("astra_api.memory")


def _memory_extraction_model_config(settings: Any) -> dict[str, Any] | None:
    """解析记忆抽取所用模型配置 ``{provider, model}``（未配置 → ``None``，不抽取）。

    ``MemorySettings.extraction_model`` 覆盖模型名；Provider / 模型名任一为空则返回 ``None``
    （**不静默 fallback**，仅关闭抽取）。
    """
    provider = str(getattr(settings, "model_default_provider", "") or "").strip()
    model = str(
        getattr(settings.memory, "extraction_model", None)
        or getattr(settings, "model_default_model", "")
        or ""
    ).strip()
    if not provider or not model:
        return None
    return {"provider": provider, "model": model}


def _subscribe_memory_extraction(
    *,
    event_bus: Any,
    memory_manager: Any,
    runs: Any,
    messages: Any,
) -> Callable[[Any], None]:
    """订阅 ``AgentCompleted`` → 触发记忆抽取（W6 裁定 B2 / §1.3-②；异常隔离）。

    组合根**唯一**接线点：``AgentCompleted`` 载荷仅含 ``run_id``，故须经 ``AgentRun`` 仓储反查
    租户 / 用户 / 触发维度，并经 ``MessageRepository.list_by_conversation`` 取该 Run 的消息
    （按 ``run_id`` 过滤）后交给能力包 ``MemoryManager.extract``（**Rich 方法**，非 RP-03）。

    🔴 **异常隔离**：抽取全程失败**不影响 Run 终态**（仅结构化 WARN；对齐知识段降级）。

    Args:
        event_bus: 事件总线（``subscribe``）。
        memory_manager: 能力包 ``MemoryManager``（含 Rich ``extract``）。
        runs: ``AgentRun`` 领域仓储（反查隔离维度）。
        messages: ``Message`` 领域仓储（按会话取消息）。

    Returns:
        已注册的处理器（供测试 / 观测）。
    """

    def _on_agent_completed(event: Any) -> None:
        """处理一条 ``AgentCompleted``：反查 Run → 取消息 → 触发抽取。"""
        payload = dict(getattr(event, "payload", {}) or {})
        run_id = str(payload.get("run_id", "") or "")
        if not run_id:
            return
        try:
            run = runs.get(run_id)
            if run is None:
                return
            conversation_id = str(getattr(run, "conversation_id", "") or "")
            chat_messages = [
                ChatMessage(
                    role=str(getattr(message, "role", "") or ""),  # type: ignore[arg-type]
                    content=str(getattr(message, "content", "") or ""),
                )
                for message in messages.list_by_conversation(conversation_id)
                if str(getattr(message, "run_id", "") or "") == run_id
            ]
            memory_manager.extract(
                run=run,
                messages=chat_messages,
                tenant_id=getattr(run, "tenant_id", None),
                user_id=getattr(run, "user_id", None),
                trigger=getattr(run, "trigger", None),
            )
        except Exception:  # noqa: BLE001 - 抽取异常隔离：不影响 Run 终态
            _MEMORY_LOGGER.warning("agent.completed 记忆抽取失败（已隔离）", exc_info=True)

    event_bus.subscribe(AgentCompleted.type, _on_agent_completed)
    return _on_agent_completed


class _ResourcePermissionCheckerAdapter(RuntimePermissionChecker):
    """把 ``astra_security.ResourcePermissionChecker`` 适配为 ``RuntimePermissionChecker``。

    🔴 **组合根薄委托、零业务逻辑**：判定链唯一实现仍在 ``astra_security.permission.checker``；
    本适配器仅把 ``check`` / ``is_allowed`` 委托给注入的单一判定链实现，从而在不改动
    ``ToolExecutor`` / ``AgentRuntime`` 签名的前提下完成注入（W3 裁定 §2.2 / §10.1）。
    """

    def __init__(self, checker: ResourcePermissionChecker) -> None:
        super().__init__()  # 无 delegate（deny-by-default 回退）；本类覆写 check / is_allowed
        self._resource_checker = checker

    @property
    def resource_checker(self) -> ResourcePermissionChecker:
        """暴露底层单一判定链实现（供装配 / 断言）。"""
        return self._resource_checker

    def check(
        self, ctx: Any, tool: Any, action: str
    ):  # noqa: ANN201 - 与 RuntimePermissionChecker 同形
        """委托单一判定链（① resource_permission → ② scope 只收窄 → ③ 默认拒绝 → ④ PEP/PDP）。"""
        return self._resource_checker.check(ctx, tool, action)

    def is_allowed(self, ctx: Any, tool: Any, action: str) -> bool:
        """委托单一判定链（仅 ``ALLOW`` 放行）。"""
        return self._resource_checker.is_allowed(ctx, tool, action)


# -- W8 / T2-44：Marketplace 组合根适配器（桥接既有 agent / skill / workflow 用例） ----

#: 资源清单在实体配置中的保留键（agent ``runtime_config`` / workflow ``definition``）。
_MARKETPLACE_RESOURCE_KEY = "_marketplace_resource"


class _IdentityPermissionChecker:
    """把 ``astra_identity.AuthorizationService`` 适配为 ``MarketplacePermissionChecker``。

    🔴 **组合根薄委托、零业务逻辑**：判定链唯一实现仍在 ``astra_identity``（``membership →
    role → role_permission → permission``，``admin = *`` 通配放行）；本适配器仅把 ``can``
    委托给注入的 RBAC 判定服务，供 ``MarketplaceService`` 经注入 Protocol 使用。
    """

    def __init__(self, authorization: AuthorizationService) -> None:
        """注入 RBAC 判定服务。"""
        self._authorization = authorization

    def can(self, user_id: str, permission: str) -> bool:
        """判定用户是否具备某权限码（含 ``*`` 通配）。"""
        return self._authorization.has_permission(user_id, permission)


class _MarketplaceResourceImporter:
    """``ResourceImporter`` 组合根适配：把 marketplace 用例桥接到既有能力用例。

    🔴 组合根**薄适配**（R4 / N-8）：资源创建 / 读取复用既有 agent（``AgentService``）/
    workflow（``WorkflowService``）/ skill（``SkillRepository`` / ``SkillVersionRepository``）
    用例；``MarketplaceService`` 仅面向注入的 ``ResourceImporter`` Protocol，对具体能力包
    **松耦合**（``astra_application`` 不 import 任何能力包实现）。

    - ``agent``：``Agent``（身份）+ ``AgentVersion``（版本）；资源清单**原样**存于
      ``AgentVersion.runtime_config[_MARKETPLACE_RESOURCE_KEY]``；
    - ``skill``：``Skill`` + ``SkillVersion``；资源清单**原样**存于 ``SkillVersion.manifest``；
    - ``workflow``：``Workflow`` + ``WorkflowVersion``；资源清单**原样**存于
      ``WorkflowVersion.definition[_MARKETPLACE_RESOURCE_KEY]``。

    三步「摘要一致 ⇒ 幂等」的基石：``create`` 落库的即 ``import`` 前**已规范化**的资源；
    ``existing_digest`` 原样回读 → ``content_digest(normalize(resource))`` 恒定一致（避免
    同名同版本**假冲突**）。
    """

    def __init__(
        self,
        *,
        agent_service: AgentService,
        agent_repository: AgentRepository,
        skill_repository: SkillRepository,
        skill_version_repository: SkillVersionRepository,
        workflow_service: WorkflowService,
        workflow_repositories: WorkflowRepositories,
    ) -> None:
        """装配适配器（全部依赖由组合根注入）。"""
        self._agent_service = agent_service
        self._agents = agent_repository
        self._skills = skill_repository
        self._skill_versions = skill_version_repository
        self._workflow_service = workflow_service
        self._workflow_repositories = workflow_repositories

    # -- ResourceImporter 实现 ----------------------------------------------

    def existing_digest(self, *, kind: str, name: str, version: str, tenant_id: str) -> str | None:
        """返回同 ``(kind, name, version)`` 已存在资源的**内容摘要**（无 → ``None``）。"""
        stored = self._existing_resource(kind, name, version, tenant_id)
        if stored is None:
            return None
        return content_digest(normalize_resource(kind, stored))

    def create(
        self,
        *,
        kind: str,
        manifest: Any,
        resource: Mapping[str, Any],
        tenant_id: str,
        owner_id: str,
    ) -> str:
        """创建资源（返回资源 id；``resource`` 为已规范化的清单）。

        Raises:
            DomainError: 未知资源种类（``VALIDATION_ERROR``）。
        """
        if kind == KIND_AGENT:
            return self._create_agent(resource, tenant_id=tenant_id, owner_id=owner_id)
        if kind == KIND_SKILL:
            return self._create_skill(resource, tenant_id=tenant_id, owner_id=owner_id)
        if kind == KIND_WORKFLOW:
            return self._create_workflow(resource, tenant_id=tenant_id, owner_id=owner_id)
        raise DomainError("未知资源种类", code=ErrorCode.VALIDATION_ERROR, data={"kind": kind})

    def read(self, *, kind: str, resource_id: str, tenant_id: str) -> Mapping[str, Any] | None:
        """读取资源清单（无 / 跨租户 → ``None``）。"""
        if kind == KIND_AGENT:
            return self._read_agent(resource_id, tenant_id)
        if kind == KIND_SKILL:
            return self._read_skill(resource_id, tenant_id)
        if kind == KIND_WORKFLOW:
            return self._read_workflow(resource_id, tenant_id)
        return None

    # -- agent ---------------------------------------------------------------

    def _find_agent(self, name: str, tenant_id: str) -> Agent | None:
        """按 ``(tenant_id, name)`` 查找 Agent（无 → ``None``）。"""
        for agent in self._agents.list_by_tenant(tenant_id):
            if getattr(agent, "name", None) == name:
                return agent
        return None

    def _create_agent(self, resource: Mapping[str, Any], *, tenant_id: str, owner_id: str) -> str:
        """创建（或复用）+ 发布 Agent 版本；返回 Agent id。"""
        name = str(resource.get("name") or "")
        version = str(resource.get("version") or "")
        agent = self._find_agent(name, tenant_id)
        if agent is None:
            agent = self._agent_service.create_agent(
                tenant_id=tenant_id,
                name=name,
                created_by=owner_id,
                description=str(resource.get("description") or "") or None,
            )
        self._agent_service.publish_version(
            agent_id=agent.id,
            system_prompt=str(resource.get("system_prompt") or ""),
            model_config={"model": str(resource.get("model") or "")},
            runtime_config={_MARKETPLACE_RESOURCE_KEY: dict(resource)},
            created_by=owner_id,
            version=version,
        )
        return agent.id

    def _read_agent(self, resource_id: str, tenant_id: str) -> Mapping[str, Any] | None:
        """按 id 读取 Agent 当前版本的资源清单（跨租户 / 无版本 → ``None``）。"""
        agent = self._agent_service.get_agent(resource_id)
        if agent is None or getattr(agent, "tenant_id", None) != tenant_id:
            return None
        current = getattr(agent, "current_version_id", None)
        if not current:
            return None
        version = self._agent_service.load_version(agent, current)
        stored = (version.runtime_config or {}).get(_MARKETPLACE_RESOURCE_KEY)
        return dict(stored) if isinstance(stored, Mapping) else None

    def _existing_resource(
        self, kind: str, name: str, version: str, tenant_id: str
    ) -> Mapping[str, Any] | None:
        """按 ``(kind, name, version)`` 回读已落地资源清单（无 → ``None``）。"""
        if kind == KIND_AGENT:
            agent = self._find_agent(name, tenant_id)
            if agent is None:
                return None
            match = next(
                (
                    item
                    for item in self._agent_service.list_versions(agent.id)
                    if item.version == version
                ),
                None,
            )
            if match is None:
                return None
            stored = (match.runtime_config or {}).get(_MARKETPLACE_RESOURCE_KEY)
            return dict(stored) if isinstance(stored, Mapping) else None
        if kind == KIND_SKILL:
            skill = self._skills.get_by_name(tenant_id, name)
            if skill is None:
                return None
            skill_record = self._skill_versions.get_by_version(skill.id, version)
            if skill_record is None:
                return None
            return dict(skill_record.manifest or {})
        if kind == KIND_WORKFLOW:
            workflow = self._workflow_repositories.workflows.get_by_name(tenant_id, name)
            if workflow is None:
                return None
            workflow_record = self._workflow_repositories.versions.get_by_version(
                workflow.id, version
            )
            if workflow_record is None:
                return None
            stored = (workflow_record.definition or {}).get(_MARKETPLACE_RESOURCE_KEY)
            return dict(stored) if isinstance(stored, Mapping) else None
        return None

    # -- skill ---------------------------------------------------------------

    def _create_skill(self, resource: Mapping[str, Any], *, tenant_id: str, owner_id: str) -> str:
        """创建（或复用）Skill + 发布 SkillVersion；返回 Skill id。"""
        name = str(resource.get("name") or "")
        version = str(resource.get("version") or "")
        skill = self._skills.get_by_name(tenant_id, name)
        if skill is None:
            skill = self._skills.add(
                Skill(
                    tenant_id=tenant_id,
                    name=name,
                    display_name=str(resource.get("display_name") or "") or name,
                    description=str(resource.get("description") or "") or None,
                    category=str(resource.get("category") or ""),
                    status=SKILL_STATUS_ACTIVE,
                    created_by=owner_id,
                )
            )
        new_version = self._skill_versions.add(
            SkillVersion(
                skill_id=skill.id,
                version=version,
                instructions=str(resource.get("instructions") or ""),
                manifest=dict(resource),
                status=SKILL_VERSION_STATUS_PUBLISHED,
                created_by=owner_id,
            )
        )
        skill.current_version_id = new_version.id
        skill.status = SKILL_STATUS_ACTIVE
        skill.touch()
        self._skills.update(skill)
        return skill.id

    def _read_skill(self, resource_id: str, tenant_id: str) -> Mapping[str, Any] | None:
        """按 id 读取 Skill 当前版本的资源清单（跨租户 / 无版本 → ``None``）。"""
        skill = self._skills.get(resource_id)
        if skill is None or getattr(skill, "tenant_id", None) != tenant_id:
            return None
        current = getattr(skill, "current_version_id", None)
        if not current:
            return None
        version = self._skill_versions.get(current)
        if version is None:
            return None
        return dict(version.manifest or {})

    # -- workflow ------------------------------------------------------------

    def _create_workflow(
        self, resource: Mapping[str, Any], *, tenant_id: str, owner_id: str
    ) -> str:
        """创建（或复用）+ 发布 Workflow 版本；返回 Workflow id。"""
        name = str(resource.get("name") or "")
        version = str(resource.get("version") or "")
        workflow = self._workflow_repositories.workflows.get_by_name(tenant_id, name)
        if workflow is None:
            created = self._workflow_service.create(
                tenant_id=tenant_id,
                name=name,
                created_by=owner_id,
                description=str(resource.get("description") or "") or None,
            )
            workflow_id = created.id
        else:
            workflow_id = workflow.id
        definition: dict[str, Any] = {
            "nodes": list(resource.get("nodes") or []),
            "edges": list(resource.get("edges") or []),
            "entry": str(resource.get("entry") or ""),
            _MARKETPLACE_RESOURCE_KEY: dict(resource),
        }
        self._workflow_service.publish(
            workflow_id,
            tenant_id=tenant_id,
            created_by=owner_id,
            definition=definition,
            version=version,
        )
        return workflow_id

    def _read_workflow(self, resource_id: str, tenant_id: str) -> Mapping[str, Any] | None:
        """按 id 读取 Workflow 当前版本的资源清单（跨租户 / 无版本 → ``None``）。"""
        workflow = self._workflow_repositories.workflows.get(resource_id)
        if workflow is None or getattr(workflow, "tenant_id", None) != tenant_id:
            return None
        current = getattr(workflow, "current_version_id", None)
        if not current:
            return None
        version = self._workflow_repositories.versions.get(current)
        if version is None:
            return None
        stored = (version.definition or {}).get(_MARKETPLACE_RESOURCE_KEY)
        return dict(stored) if isinstance(stored, Mapping) else None


# -- W9 / T2-47：Evaluation 组合根适配器（桥接真实 Runtime 创建逐例 agent_run） ----

#: 逐例 ``agent_run`` 的终态集合（``agent_run.status`` 口径）。
_AGENT_RUN_TERMINAL_STATUSES: frozenset[str] = frozenset({"SUCCESS", "FAILED", "CANCELLED"})

#: 逐例执行异常 / 未知终态的统一失败字面值。
_AGENT_RUN_FAILED = "FAILED"

#: Evaluation 组合根日志器（执行异常隔离仅告警）。
_EVALUATION_LOGGER = logging.getLogger("astra_api.evaluation")


class _EvaluationRunLauncher:
    """``AgentRunLauncher`` 组合根适配：把 Evaluation 逐例执行桥接到正式 Runtime（R1/§5.1）。

    🔴 组合根**薄适配**（R1）：Evaluation 能力包仅面向注入的 ``AgentRunLauncher`` Protocol，
    **不 import** ``astra_runtime`` / ``astra_agent``；逐例 Run 的创建 / 执行 / 取消复用既有
    ``AgentRunService``（建会话 → ``open_run`` → 固定 ``agent_version_id`` → ``execute``），
    从而复用正式 Runtime / 权限 / Sandbox（§2.13.2「复用正式 Runtime、权限和 Sandbox」）。

    ``await_result`` 的 ``tool_error_count`` 口径（冻结 §5.3）由 ``tool_calls`` 快照承载——
    **只**统计 ``FAILED``；``DENIED`` 单独读取（见 ``astra_evaluation.count_tool_errors``）。
    """

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        agent_run: AgentRunService,
        runs: Any,
        tool_calls: Any,
    ) -> None:
        """装配适配器（全部依赖由组合根注入）。"""
        self._conversations = conversation_service
        self._agent_run = agent_run
        self._runs = runs
        self._tool_calls = tool_calls

    # -- AgentRunLauncher 实现 ----------------------------------------------

    def launch(
        self,
        *,
        tenant_id: str,
        organization_id: str | None,
        workspace_id: str | None,
        agent_id: str,
        agent_version_id: str,
        input: Any,
        user_id: str | None = None,
    ) -> RunHandle:
        """创建一条逐例 ``agent_run``（**固定** ``agent_version_id``）并返回句柄。

        Raises:
            DomainError: Agent 不存在（``NOT_FOUND``，由 ``AgentRunService.open_run`` 抛出）。
        """
        conversation = self._conversations.create_conversation(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id or "",
            title="evaluation",
        )
        dto = self._agent_run.open_run(
            CreateAgentTaskCommand(
                tenant_id=tenant_id,
                agent_id=agent_id,
                conversation_id=conversation.id,
                user_id=user_id,
                user_message=self._as_message(input),
                workspace_id=workspace_id,
            )
        )
        # 固定版本（可重放，§4.2）：``open_run`` 默认取 Agent 当前版本，此处改回请求版本。
        run = self._runs.get(dto.id)
        if run is not None and agent_version_id and run.agent_version_id != agent_version_id:
            run.agent_version_id = agent_version_id
            self._runs.update(run)
        return RunHandle(run_id=dto.id)

    def await_result(self, handle: RunHandle) -> RunOutcome:
        """同步执行至终态并取回结果快照（**执行异常隔离**，以 Run 终态为准）。"""
        try:
            self._agent_run.execute(handle.run_id)
        except Exception:  # noqa: BLE001 - 隔离执行异常（无模型 / Sandbox 失败等），以 Run 终态为准
            _EVALUATION_LOGGER.warning(
                "Evaluation 逐例 agent_run 执行异常（已隔离）", exc_info=True
            )
        run = self._runs.get(handle.run_id)
        status = str(getattr(run, "status", "") or "") if run is not None else ""
        if status not in _AGENT_RUN_TERMINAL_STATUSES:
            status = _AGENT_RUN_FAILED
        return RunOutcome(
            run_id=handle.run_id,
            status=status,
            output=self._output_of(handle.run_id),
            error_type=getattr(run, "error_type", None),
            duration_ms=getattr(run, "duration_ms", None),
            token_usage=self._token_usage(run),
            cost=self._cost(run),
            tool_calls=self._tool_call_views(handle.run_id),
        )

    def cancel(self, run_id: str) -> None:
        """按 A-9 取消一个已启动的 Run（传播到 runtime 取消路径）。"""
        self._agent_run.cancel(run_id)

    # -- 内部 ---------------------------------------------------------------

    @staticmethod
    def _as_message(value: Any) -> str:
        """把用例 ``input`` 归一为 Runtime 用户消息文本。"""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)

    def _output_of(self, run_id: str) -> str | None:
        """取该 Run 会话的**最后一条 assistant 消息**文本（无 → ``None``）。"""
        run = self._runs.get(run_id)
        conversation_id = str(getattr(run, "conversation_id", "") or "") if run is not None else ""
        if not conversation_id:
            return None
        messages = self._conversations.list_messages(conversation_id)
        for message in reversed(messages):
            if str(getattr(message, "role", "") or "") == "assistant":
                content = getattr(message, "content", None)
                return str(content) if content is not None else None
        return None

    @staticmethod
    def _token_usage(run: Any) -> dict[str, Any] | None:
        """取 Run 的 token 用量（空 → ``None``）。"""
        usage = getattr(run, "token_usage", None)
        return dict(usage) if usage else None

    @staticmethod
    def _cost(run: Any) -> float | None:
        """取 Run 的成本（``Decimal`` → ``float``；空 → ``None``）。"""
        cost = getattr(run, "cost", None)
        return float(cost) if cost is not None else None

    def _tool_call_views(self, run_id: str) -> list[ToolCallView]:
        """取该 Run 下工具调用快照（``tool_error_count`` / tool 序列评分口径）。"""
        return [
            ToolCallView(
                name=str(getattr(call, "tool_name", "") or ""),
                status=str(getattr(call, "status", "") or ""),
            )
            for call in self._tool_calls.list_by_run(run_id)
        ]


# -- R3 / T2-60：远程 Task / Project 组合根适配器 ------------------------------

#: 远程审计 / 入队日志器（失败隔离仅告警）。
_REMOTE_LOGGER = logging.getLogger("astra_api.remote")


class _RemoteTaskAuthorizer:
    """``RemoteTaskAuthorizer`` 适配：RBAC（``admin = *`` / 精确码）+ resource_permission scope。

    🔴 **A-14**：复用既有 ``EXECUTE`` 动作；capability 细分（``task.submit`` / ``task.cancel`` /
    ``git.diff`` / ``artifact.download`` …）经 ``resource_permission.scope.capabilities`` 判定；
    ``TASK`` 资源类型仅为**字符串**（无 DB 枚举迁移）。判定顺序：

    1. RBAC 通配（``admin = *``）→ 全量放行（``role``）；
    2. RBAC 精确权限码 → 放行（``rbac``）；
    3. ``resource_permission``（``TASK`` × ``EXECUTE``）scope：按 ``resource_id`` 收窄 + capability
       匹配（``scoped``）；无任何规则 → ``no_grant``（``in_scope=False`` → 统一 404）。
    """

    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        permissions: ResourcePermissionRepository,
    ) -> None:
        """装配适配器（组合根注入 RBAC 判定 + 资源权限仓储）。"""
        self._authorization = authorization
        self._permissions = permissions

    def authorize(
        self,
        principal: RemotePrincipal,
        *,
        capability: str,
        resource_type: str = TASK_RESOURCE_TYPE,
        resource_id: str | None = None,
    ) -> RemoteAccessDecision:
        """判定 ``principal`` 对 ``resource_id`` 是否具备 ``capability``（A-14）。"""
        if self._authorization.has_permission(principal.user_id, ADMIN_PERMISSION):
            return RemoteAccessDecision(allowed=True, in_scope=True, reason="role")
        if self._authorization.has_permission(principal.user_id, capability):
            return RemoteAccessDecision(allowed=True, in_scope=True, reason="rbac")
        rules = [
            rule
            for rule in self._permissions.list_for_subject(
                principal.tenant_id, "user", principal.user_id
            )
            if rule.resource_type == resource_type and rule.action == ACTION_EXECUTE
        ]
        if not rules:
            return RemoteAccessDecision(allowed=False, in_scope=False, reason="no_grant")
        type_level = any(rule.resource_id is None for rule in rules)
        granted_ids = {rule.resource_id for rule in rules if rule.resource_id}
        # 集合操作（``resource_id is None``）→ 逐项鉴权交由后续列表过滤；此处只要有足迹即在范围。
        in_scope = type_level or resource_id is None or resource_id in granted_ids
        allowed = False
        for rule in rules:
            if rule.effect != "ALLOW":
                continue
            if rule.resource_id is not None and rule.resource_id != resource_id:
                continue
            if match_capability(
                capability,
                declared=granted_capabilities(rule.scope),
                denied=denied_capabilities(rule.scope),
            ):
                allowed = True
        return RemoteAccessDecision(
            allowed=allowed, in_scope=in_scope, reason="scoped" if allowed else "denied"
        )


class _RemoteAuditSink:
    """``RemoteAuditSink`` 适配：把远程动作审计写入既有 ``AuditService``（落 ``audit_log``）。"""

    def __init__(self, audit: AuditService) -> None:
        """注入审计应用服务（组合根已装配的同一实例）。"""
        self._audit = audit

    def record(
        self,
        *,
        tenant_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        metadata: dict[str, Any],
    ) -> None:
        """写一条审计记录（**不含**宿主路径 / Secret 明文；失败隔离仅告警）。"""
        try:
            self._audit.record(
                AuditRecordDTO(
                    tenant_id=tenant_id,
                    action=action,
                    request_id=generate_id(),
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                    metadata={"user_id": user_id, **dict(metadata)},
                )
            )
        except Exception:  # noqa: BLE001 - 审计失败不得阻断业务
            _REMOTE_LOGGER.warning("远程审计写入失败（已隔离）", exc_info=True)


def _enqueue_best_effort(
    queue: Any | None,
    *,
    handler: str,
    payload: dict[str, Any],
    task: Task,
    tenant_id: str | None,
) -> None:
    """把任务**尽力**入队（队列缺失 / 失败 → 告警，任务已持久化为 ``PENDING`` 可被恢复重投）。"""
    if queue is None or not hasattr(queue, "enqueue"):
        return
    message = {
        "handler": handler,
        "payload": dict(payload),
        "task_id": task.task_id,
        "tenant_id": tenant_id,
    }
    try:
        queue.enqueue(message)
    except Exception:  # noqa: BLE001 - 入队失败隔离：任务已落 PENDING，可经启动恢复重投
        _REMOTE_LOGGER.warning(
            "远程任务入队失败（任务已落 PENDING，可经启动恢复重投）",
            extra={"task_id": task.task_id, "handler": handler},
            exc_info=True,
        )


class _RemoteTaskSubmitter:
    """``RemoteTaskSubmitter`` 适配：构造 ``remote.agent_run`` 任务（幂等）+ 入队。

    🔴 **幂等（F-R2）**：同 ``(tenant_id, idempotency_key)`` 同体 → 复用既有 ``task_id``
    （按载荷 ``idempotency_key`` 匹配；无新列 / 无新迁移）。

    🔴 **执行期限额强制（R5 补全轮 · F8a / F8c；N10）**：本适配为**提交面**的两个**强制点**：

    1. **pending 上限（F8a）**：在**幂等查找之后 / 创建之前**统计该 user 的**未终态**远程任务
       （``payload.created_by == user_id`` 且 status ∉ {SUCCESS, FAILED, CANCELLED}）；
       ``>= max_pending_per_user`` → ``DomainError(RESOURCE_LIMIT_EXCEEDED)``（**不静默排队**）。
       **幂等复用不计数**（复用走既有 ``task_id``，不新建）。
    2. **deadline 落载荷（F8c）**：``max_duration_seconds`` 非空时在 ``payload`` 写 ``deadline_at``
       （ISO8601，``utcnow() + max_duration_seconds``；**免迁移**——payload 为 JSON）；worker 侧
       （``remote_agent_run``）运行**前**读取，过期即**不运行执行体**、经租约落稳定失败终态。

    两个 cap 均**构造注入**（组合根取 ``settings.remote_execution``）；缺省 ``None`` = **不启用**
    该检查（向后兼容既有装配 / 测试）。
    """

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        task_queue: Any | None = None,
        max_pending_per_user: int | None = None,
        max_duration_seconds: int | None = None,
    ) -> None:
        """装配（任务仓储 + 队列 Provider + 可选执行期限额）。

        Args:
            tasks: 任务仓储（注入 Protocol）。
            task_queue: 队列 Provider（可空；缺省 → 尽最大努力入队，落库不受影响）。
            max_pending_per_user: 单用户未终态远程任务上限（可空；缺省 → 不启用 pending 检查）。
            max_duration_seconds: 单次执行时长上限（秒；可空；缺省 → 不写 ``deadline_at``）。
        """
        self._tasks = tasks
        self._queue = task_queue
        self._max_pending_per_user = max_pending_per_user
        self._max_duration_seconds = max_duration_seconds

    def submit(self, spec: RemoteTaskSpec, *, tenant_id: str, user_id: str) -> str:
        """创建并派发远程任务，返回 ``task_id``（幂等复用）。

        Raises:
            DomainError: 该 user 未终态远程任务数达 ``max_pending_per_user``
                （``RESOURCE_LIMIT_EXCEEDED`` → 429）。
        """
        existing = self._find_idempotent(tenant_id, spec.idempotency_key)
        if existing is not None:
            return existing
        creator = spec.created_by or user_id
        # F8a：幂等查找之后 / 创建之前 → pending 上限强制（幂等复用**不**计数）。
        self._enforce_pending_limit(tenant_id=tenant_id, user_id=creator)
        payload: dict[str, Any] = {
            "project_id": spec.project_id,
            "workspace_id": spec.workspace_id,
            "agent_version_id": spec.agent_version_id,
            "workflow_version_id": spec.workflow_version_id,
            "requirement": spec.requirement,
            "base_ref": spec.base_ref,
            "environment_id": spec.environment_id,
            "idempotency_key": spec.idempotency_key,
            "limits": dict(spec.limits),
            "created_by": creator,
        }
        # F8c：写 deadline_at（免迁移；worker 侧运行前快速失败）。
        deadline_at = self._deadline_at()
        if deadline_at is not None:
            payload["deadline_at"] = deadline_at
        task = Task(
            tenant_id=tenant_id,
            workspace_id=spec.workspace_id,
            type=REMOTE_TASK_TYPE,
            execution_mode="QUEUED",
            payload=payload,
        )
        task.enqueue()
        task = self._tasks.add(task)
        _enqueue_best_effort(
            self._queue, handler=REMOTE_TASK_TYPE, payload=payload, task=task, tenant_id=tenant_id
        )
        return str(task.task_id)

    def _enforce_pending_limit(self, *, tenant_id: str, user_id: str) -> None:
        """统计该 user 未终态远程任务；达上限 → ``RESOURCE_LIMIT_EXCEEDED``（**非静默**）。"""
        cap = self._max_pending_per_user
        if cap is None:
            return
        pending = 0
        for task in self._tasks.list(tenant_id=tenant_id, type=REMOTE_TASK_TYPE):
            if bool(getattr(task, "is_terminal", False)):
                continue
            payload = dict(getattr(task, "payload", None) or {})
            if str(payload.get("created_by") or "") == user_id:
                pending += 1
        if pending >= cap:
            raise DomainError(
                "远程任务待处理数已达上限（请等待在途任务完成后重试）",
                code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                status_code=429,
                data={"limit": cap, "scope": "pending_per_user", "pending": pending},
            )

    def _deadline_at(self) -> str | None:
        """由 ``max_duration_seconds`` 计算 ``deadline_at``（ISO8601 UTC；缺省 → ``None``）。"""
        seconds = self._max_duration_seconds
        if seconds is None:
            return None
        from datetime import timedelta

        from astra_common.time import utcnow

        return (utcnow() + timedelta(seconds=int(seconds))).isoformat()

    def _find_idempotent(self, tenant_id: str, idempotency_key: str | None) -> str | None:
        """按载荷 ``idempotency_key`` 查找既有远程任务（无 → ``None``）。"""
        if not idempotency_key:
            return None
        for task in self._tasks.list(tenant_id=tenant_id, type=REMOTE_TASK_TYPE):
            payload = dict(getattr(task, "payload", None) or {})
            if str(payload.get("idempotency_key") or "") == idempotency_key:
                return str(task.task_id)
        return None


class _ProjectCloneDispatcher:
    """``TaskDispatcher`` 适配：派发 ``project.clone`` 任务（返回 ``task_id``）。"""

    def __init__(self, *, tasks: TaskRepository, task_queue: Any | None = None) -> None:
        """装配（任务仓储 + 队列 Provider）。"""
        self._tasks = tasks
        self._queue = task_queue

    def dispatch_clone(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        project_id: str,
        repo_url: str,
        base_ref: str | None = None,
    ) -> str:
        """创建并派发 ``project.clone`` 任务，返回 ``task_id``。"""
        payload: dict[str, Any] = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "repo_url": repo_url,
            "base_ref": base_ref,
        }
        task = Task(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            type=PROJECT_CLONE_TASK_TYPE,
            execution_mode="QUEUED",
            payload=payload,
        )
        task.enqueue()
        task = self._tasks.add(task)
        _enqueue_best_effort(
            self._queue,
            handler=PROJECT_CLONE_TASK_TYPE,
            payload=payload,
            task=task,
            tenant_id=tenant_id,
        )
        return str(task.task_id)


class _SessionScopedProjectRepository:
    """``ProjectRepository`` 适配：为**风格①** ``SqlProjectRepository`` 提供**逐调用**会话。

    🔴 分层（C-7 单写者）：既有 ``SqlProjectRepository``（``astra_workspace.repositories``）为
    **风格①**——构造需**已绑定**的 ``Session``。远程能力包 ``RemoteTaskService``（``application``，
    零 ORM / 零 Web）仅依赖 ``astra_workspace.domain.ProjectRepository`` Protocol；本适配器在
    **组合根**以 ``session_scope`` 打开短时会话并委派，使能力包与 ORM 会话生命周期彻底解耦。
    返回的 ``Project`` 为**纯数据类**（域实体，脱离会话后仍可安全读取）。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """装配（仅持有会话工厂；**不**跨调用复用会话）。"""
        self._session_factory = session_factory

    def get(self, project_id: str) -> Any | None:
        """按主键获取项目（短时会话内委派），不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            return SqlProjectRepository(session).get(project_id)

    def list_by_workspace(self, workspace_id: str, *, scope: Any | None = None) -> list[Any]:
        """列出某 Workspace 下的项目（短时会话内委派）。"""
        with session_scope(self._session_factory) as session:
            return SqlProjectRepository(session).list_by_workspace(workspace_id, scope=scope)


class _ProjectGitCredentialProvider:
    """``GitCredentialProvider`` 适配：从 ``Project.settings`` 读**写凭证引用**并**短时**解密。

    🔴 **L-11（凭证明文不落库 / 日志 / 响应）**：明文仅经 ``CredentialServiceDecoder`` 在**内存**
       短时解出，**仅**在**独立 Push Sandbox** 会话内以环境变量注入 git push；**不**落审计 / 响应 /
       日志，**不**注入 Agent Sandbox / 客户端。

    约定引用键（落 ``Project.settings``）：

    - ``git_write_credential_id``：凭证 id（经 ``CredentialServiceDecoder`` 解密得 token）；
    - ``git_write_username``：用户名（可空）。

    未配置（无凭证 id / 解密失败）→ ``None``（Push 端点据此返回 422，**不静默成功**）。
    """

    #: 写凭证 id 引用键（``Project.settings``）。
    SETTINGS_CREDENTIAL_ID_KEY = "git_write_credential_id"
    #: 写凭证用户名键（``Project.settings``；可空）。
    SETTINGS_USERNAME_KEY = "git_write_username"

    def __init__(self, *, projects: Any, decoder: CredentialServiceDecoder) -> None:
        """装配（项目仓储 + 凭证解密器）。"""
        self._projects = projects
        self._decoder = decoder

    def write_credentials(self, *, tenant_id: str, project_id: str) -> GitWriteCredential | None:
        """返回 Project 写凭证（**短时**）；未配置 / 跨租户 → ``None``。"""
        project = self._projects.get(project_id)
        if project is None or str(getattr(project, "tenant_id", "") or "") != tenant_id:
            return None
        settings = dict(getattr(project, "settings", None) or {})
        credential_id = settings.get(self.SETTINGS_CREDENTIAL_ID_KEY)
        if not credential_id:
            return None
        try:
            token = self._decoder.decrypt(str(credential_id))
        except Exception:  # noqa: BLE001 - 解密失败 → 视为未配置（不静默成功）
            return None
        username = str(settings.get(self.SETTINGS_USERNAME_KEY) or "")
        return GitWriteCredential(username=username, token=token)


# -- R5 补全轮：远程读取侧适配器（F2 ArtifactReader / F3 GitRefsProvider） -------


class _StorageArtifactReader:
    """``ArtifactReader`` 生产适配：经注入 ``Storage`` 读取（key **直通**；F2 / R5A-01a）。

    分层（C-7 单写者）：能力包 ``RemoteTaskService``（``application``，零 ORM / 零 Web）仅依赖
    ``ArtifactReader`` Protocol；本适配器在**组合根**把受管 ``Storage`` 读取委派出去。

    🔴 **不自行拼路径**：``key`` **直通** ``Storage.get``（``LocalFileStorage`` 自带
       canonical containment，拒绝绝对路径 / ``..`` 逃逸）；``content_type`` 返回 ``None``，
       由 ``download_artifact`` 既有 ``or view.content_type or octet-stream`` 兜底。
    """

    def __init__(self, storage: Any) -> None:
        """装配（注入 Storage Provider；``None`` 时保持占位——下载端点将结构化 503）。"""
        self._storage = storage

    def read(self, ref: str) -> tuple[bytes, str | None]:
        """读取 Artifact 内容，返回 ``(bytes, content_type)``（``content_type`` 恒 ``None``）。"""
        return self._storage.get(ref), None


class _SandboxGitRefsProvider:
    """``GitRefsProvider`` 生产适配：仅经 Sandbox 执行 ``git for-each-ref``（F3 / R5A-01b）。

    组合根适配：Project 归属校验 → 受管仓库目录（``ProjectStorage``，canonical containment）
    → 独立 Sandbox 会话内 ``GitService.for_each_ref`` → :func:`parse_for_each_ref` 解析为
    **不含宿主路径**的 :class:`GitRefView`。

    🔴 **仅经 Sandbox**：Git 命令一律经注入 ``GitService``（→ ``SandboxProvider.exec``）；
       本适配器**不**直连宿主 Git。
    🔴 **不泄漏存在性**：Project 未知 / 跨租户 → 返回空元组；命令失败 → 返回空元组（非静默失败
       由端点 200 + 空列表表达，不抛宿主异常）。
    """

    def __init__(
        self,
        *,
        projects: Any,
        sandbox: Any,
        storage: ProjectStorage,
        git_service: GitService,
    ) -> None:
        """装配（项目仓储 + Sandbox + 受管目录 + Git 用例；均为组合根统一实例）。"""
        self._projects = projects
        self._sandbox = sandbox
        self._storage = storage
        self._git = git_service

    def refs(self, project_id: str, *, tenant_id: str) -> tuple[GitRefView, ...]:
        """返回 Project 的 Git 引用（分支 / 标签）；跨租户 / 未知 / 失败 → 空元组。"""
        project = self._projects.get(project_id)
        if project is None or str(getattr(project, "tenant_id", "") or "") != tenant_id:
            return ()
        repo_dir = self._storage.project_repo_dir(project_id)
        session = self._sandbox.create_session(tenant_id=tenant_id)
        try:
            result = self._git.for_each_ref(session, cwd=str(repo_dir))
        finally:
            self._sandbox.destroy(session)
        if not result.ok:
            return ()
        return tuple(
            GitRefView(name=name, commit=commit, kind=kind)
            for name, commit, kind in parse_for_each_ref(result.stdout)
        )


def get_app_services(request: Request) -> AppServices:
    """从 ``app.state`` 取出已装配的 :class:`AppServices`。

    Raises:
        RuntimeError: lifespan 未完成装配时。
    """
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("AppServices 尚未初始化：请确认应用 lifespan 已运行")
    return services


#: FastAPI 依赖类型别名。
AppServicesDep = Annotated[AppServices, Depends(get_app_services)]


def get_identity(services: AppServicesDep) -> IdentityServices:
    """取出身份子域服务。"""
    return services.identity


def get_workspace_services(services: AppServicesDep) -> WorkspaceServices:
    """取出工作区子域服务。"""
    return services.workspace


def get_auth_service(services: AppServicesDep) -> AuthService:
    """取出认证应用服务。"""
    return services.auth


def get_settings_service(services: AppServicesDep) -> SettingsService:
    """取出设置应用服务。"""
    return services.settings


def get_feature_flags(services: AppServicesDep) -> FeatureFlagService:
    """取出 Feature Flag 读取服务（T0-21）。"""
    return services.feature_flags


# -- W6：新增服务 getter（Router 只经 AppServicesDep 取用） ------------------


def get_agent_service(services: AppServicesDep) -> AgentService:
    """取出 Agent 子域服务。"""
    return services.agent


def get_conversation_service(services: AppServicesDep) -> ConversationService:
    """取出会话 / 消息服务。"""
    return services.conversation


def get_run_service(services: AppServicesDep) -> RunService:
    """取出 Run ↔ Task 挂靠服务。"""
    return services.run


def get_agent_run_service(services: AppServicesDep) -> AgentRunService:
    """取出 Agent / Run 用例编排器。"""
    return services.agent_run


def get_model_catalog_service(services: AppServicesDep) -> ModelCatalogService:
    """取出模型目录服务。"""
    return services.model


def get_tool_registry(services: AppServicesDep) -> ToolRegistry:
    """取出 Tool 注册表。"""
    return services.tool


def get_tool_permission_service(services: AppServicesDep) -> PermissionService:
    """取出 Tool 授权读写服务。"""
    return services.tool_permissions


def get_runtime(services: AppServicesDep) -> AgentRuntime:
    """取出 Agent Runtime。"""
    return services.runtime


def get_audit_service(services: AppServicesDep) -> AuditService:
    """取出审计应用服务。"""
    return services.audit


def get_idempotency_service(services: AppServicesDep) -> IdempotencyService:
    """取出幂等记录读写服务。"""
    return services.idempotency


def get_permission_checker(services: AppServicesDep) -> ResourcePermissionChecker:
    """取出权限单一判定链（capability 检查数据源，T2-14）。"""
    return services.permission


def get_model_credential_binder(services: AppServicesDep) -> ModelCredentialBinder:
    """取出模型 Provider 凭证绑定器（T1-30）。"""
    return services.model_credentials


def get_provider_runtime(services: AppServicesDep) -> ProviderRuntime:
    """取出 Provider 运行时（显式可审计解密，T1-30）。"""
    return services.provider_runtime


def get_provider_resolver(services: AppServicesDep) -> ProviderResolver:
    """取出执行期 Provider 绑定器（M1；组合根装配，业务经 ``AppServices`` 取用）。"""
    return services.provider_resolver


def get_agent_repository(services: AppServicesDep) -> AgentRepository:
    """取出 Agent 仓储（面向领域 Protocol；供 Agent 读用例）。"""
    return services.agent_repository


def get_task_repository(services: AppServicesDep) -> TaskRepository:
    """取出 Task 仓储（面向领域 Protocol；供任务视图）。"""
    return services.tasks


# -- W3 / T2-17：2a API 骨架 getter（Router 只经 AppServicesDep 取用） --------


def get_skill_repository(services: AppServicesDep) -> SkillRepository:
    """取出 Skill 仓储（面向领域 Protocol）。"""
    return services.skill


def get_skill_version_repository(services: AppServicesDep) -> SkillVersionRepository:
    """取出 SkillVersion 仓储（面向领域 Protocol）。"""
    return services.skill_versions


def get_mcp_server_repository(services: AppServicesDep) -> MCPServerRepository:
    """取出 MCP Server 仓储。"""
    return services.mcp


def get_mcp_tool_repository(services: AppServicesDep) -> MCPToolRepository:
    """取出 MCP Tool 发现目录仓储。"""
    return services.mcp_tools


def get_mcp_permission_repository(services: AppServicesDep) -> MCPPermissionRepository:
    """取出 MCP Tool 授权仓储。"""
    return services.mcp_permissions


def get_mcp_registry(services: AppServicesDep) -> MCPRegistry:
    """取出 MCP 注册表。"""
    return services.mcp_registry


def get_plugin_repository(services: AppServicesDep) -> PluginRepository:
    """取出插件仓储。"""
    return services.plugins


def get_audit_repository(services: AppServicesDep) -> AuditRepository:
    """取出审计仓储（面向领域 Protocol；供 ``/audit`` 消费）。"""
    return services.audit_repository


# -- W4 / T2-25：Workflow 用例编排 getter（Router 只经 AppServicesDep 取用） ---


def get_workflow_service(services: AppServicesDep) -> WorkflowService:
    """取出 Workflow 用例编排器（W4 / T2-25）。"""
    return services.workflow


# -- W4 / T2-26：审批机制 getter（Router 只经 AppServicesDep 取用） -----------


def get_approval_service(services: AppServicesDep) -> ApprovalService:
    """取出审批机制服务（W4 / T2-26）。"""
    return services.approval


def get_approval_repository(services: AppServicesDep) -> ApprovalRepository:
    """取出审批仓储（面向领域 Protocol；供 ``/approvals`` 只读待办列表，W10 / T2-49）。"""
    return services.approval_repository


# -- W6 / T2-35（前端/API 流）：Knowledge / Memory getter（Router 只经 AppServicesDep 取用） --


def get_knowledge_service(services: AppServicesDep) -> KnowledgeService:
    """取出 Knowledge 用例编排器（W6 / T2-35）。"""
    return services.knowledge


def get_memory_service(services: AppServicesDep) -> MemoryService:
    """取出 Memory 用例编排器（W6 / T2-35）。"""
    return services.memory


# -- W7 / T2-39：Task/Scheduler 增强 getter（Router 只经 AppServicesDep 取用） --


def get_schedule_repository(services: AppServicesDep) -> ScheduleRepository:
    """取出调度仓储（面向领域 Protocol；``/schedules`` 数据源，W7 / T2-39）。"""
    return services.schedules


def get_task_execution_repository(services: AppServicesDep) -> TaskExecutionRepository:
    """取出任务执行记录仓储（面向领域 Protocol，W7 / T2-39）。"""
    return services.task_executions


def get_scheduler(services: AppServicesDep) -> SchedulerTick:
    """取出调度轮询执行体（组合根装配，W7 / T2-39）。"""
    return services.scheduler


# -- W8 / T2-44：Marketplace 用例编排 getter（Router 只经 AppServicesDep 取用） --


def get_marketplace_service(services: AppServicesDep) -> MarketplaceService:
    """取出 Marketplace 用例编排器（W8 / T2-44）。"""
    return services.marketplace


# -- W9 / T2-47：Evaluation 用例编排 getter（Router 只经 AppServicesDep 取用） --


def get_evaluation_service(services: AppServicesDep) -> EvaluationService:
    """取出 Evaluation 用例编排器（W9 / T2-47）。"""
    return services.evaluation
