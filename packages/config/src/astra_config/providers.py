"""Provider 自动装配工厂（决策 D4 —— 业务代码不判断环境）。

🔴 **本模块是 ``ASTRA_MODE=local|server`` 分流的唯一允许位置**（含 mode 与
   DB URL 的一致性校验）。上层（如 ``apps/api``）仅通过 ``dependencies/container.py``
   获取 :class:`Providers`，不得出现 ``if mode == ...``。

本轮（W2 / T0-16）收口装配：``database`` / ``storage`` / ``event_bus`` / ``task_queue`` /
``model_registry`` / ``secrets`` / ``scheduler``。

Phase 1（T1-03）扩展装配位：``model_providers`` / ``model_router`` / ``tool_registry`` /
``sandbox`` / ``runtime``（**占位可空**：对应能力包由 W3–W5 落地，**函数级延迟导入**，
未就位时为 ``None``，装配位保留）。

设计取舍（避免静默降级 / T2-54 Server Provider 闭环）：
- ``mode=local``：SQLite + **真实**进程内能力（LocalFileStorage / LocalEventBus /
  InProcessTaskQueue / LocalScheduler）；
- ``mode=server``：**两档真实 Provider 闭环**（不再是 ``UnsupportedXxx`` 占位）：
  - **Community 基础档**（未配置 ``ASTRA_REDIS_URL``）：PostgreSQL（或部署档 DB）+
    LocalFileStorage + LocalEventBus + InProcessTaskQueue + InProcessBackgroundExecutor
    + LocalScheduler + LocalProcessSandbox —— 可运行闭环；
  - **Compose / Team 档**（配置 ``ASTRA_REDIS_URL`` 且 ``astra-task[redis]`` 就位）：
    PostgreSQL + RedisTaskQueue + WorkerProcessExecutor + DockerSandbox；
  - **缺少可选依赖**（如显式配置 Redis 但缺 ``astra-task[redis]``）→ **装配期**抛
    ``DomainError(CONFIGURATION_ERROR)``（**明确配置错误**，**不**延迟到首次请求才失败）。
- ``model_registry``（含 stub）与 ``secrets``（EnvSecretProvider）**两模式一致**，
  均为 Phase 0 真实交付物，非占位。
- ``providers.py`` 对能力包一律**函数级延迟导入**，避免 ``config ↔ 能力包``
  的模块级循环依赖（同 ``_build_database``）。
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

from .settings import Settings

__all__ = [
    "DatabaseProvider",
    "Providers",
    "build_providers",
    "validate_mode_database_consistency",
    "is_postgres_url",
    "is_sqlite_url",
]

_logger = logging.getLogger("astra_config.providers")


@dataclass
class DatabaseProvider:
    """数据库 Provider：持有 SQLAlchemy 引擎与会话工厂。

    Attributes:
        engine: SQLAlchemy ``Engine``。
        session_factory: 会话工厂（``sessionmaker``）。
    """

    engine: Any
    session_factory: Any


@dataclass
class Providers:
    """Provider 容器：组合根（composition root）产物。

    Attributes:
        settings: 当前生效配置。
        database: 数据库 Provider。
        storage: 文件存储 Provider（W2 填充）。
        event_bus: 事件总线 Provider（W2 填充）。
        task_queue: 任务队列 Provider（W2 填充）。
        model_registry: 模型 Provider 注册表（W2 填充）。
        secrets: 机密提供者（W2 新增，决策 D8）。
        scheduler: 调度器 Provider（W2 新增，可选）。
        model_providers: 真实 Model Provider 容器（T1-03 装配位；能力包由 W3 落地，
            本波次可空）。
        model_router: Model Router（T1-03 装配位；W3 落地，本波次可空）。
        tool_registry: Tool 注册表（T1-03 装配位；W4 落地，本波次可空）。
        sandbox: Sandbox Provider（T1-03 装配位；W4 落地，本波次可空）。
        runtime: Agent Runtime 装配位（T1-03；**保留且恒为 ``None``**）。Runtime 需多依赖
            DI，由**组合根** ``AgentRuntime.build(...)`` 装配（W6 / A30），**不新增
            ``build_runtime``**。
        worker_executor: 后台执行体槽位（W1 / T2-02；与 ``task_queue`` **正交**）。
            local = :class:`InProcessBackgroundExecutor`；server = :class:`WorkerProcessExecutor`
            （无 Redis 时回落占位）。

    Note:
        新增装配位一律**可空**（能力包尚未就位时为 ``None``），装配仍**仅**在
        :func:`build_providers` 内按 ``mode`` 分流（C-01 / 决策 D4）；业务代码不得
        出现 ``if mode == ...``。
    """

    settings: Settings
    database: DatabaseProvider | None = None
    storage: Any | None = None
    event_bus: Any | None = None
    task_queue: Any | None = None
    model_registry: Any | None = None
    secrets: Any | None = None
    scheduler: Any | None = None
    # -- Phase 1 新增装配位（T1-03；占位可空） ------------------------------
    model_providers: Any | None = None
    model_router: Any | None = None
    tool_registry: Any | None = None
    sandbox: Any | None = None
    runtime: Any | None = None
    # -- Phase 2 新增装配位（W1 / T2-02；执行体槽，与 task_queue 并列） ------
    worker_executor: Any | None = None
    # -- Phase 2 新增装配位（W2 / T2-08 · T2-11 · T2-12；裁定 §14.1） --------
    # ``skill_registry`` / ``mcp_registry`` 由 ``_build_optional`` 装配（能力包就位即
    # 装配，工厂缺失回落 ``None``）；``skill_resolver`` / ``mcp_executor`` 因 DI 依赖多，
    # 由**组合根**（``AppServices``）装配并传入 ``AgentRuntime.build(...)``，此处恒 ``None``。
    skill_registry: Any | None = None
    mcp_registry: Any | None = None
    skill_resolver: Any | None = None
    mcp_executor: Any | None = None
    # -- Phase 2 新增装配位（W6 / T2-34；裁定 B7 / §2.2） --------------------
    # ``memory_store``：能力包就位即按 **capability 选路**装配（``vector_search=true`` →
    # ``VectorMemoryStore``；否则 ``SqlMemoryStore``）；能力包缺失回落到 ``None``。
    memory_store: Any | None = None
    # -- Phase 2 新增装配位（W7 / T2-39；Task/Scheduler 增强） ----------------
    # ``scheduler_runner``：调度轮询执行体（``SchedulerTick``）槽位。因需注入
    # ``ScheduleRepository`` / ``TaskExecutionRepository``（多 DI 依赖，经会话工厂装配），
    # 由**组合根**（``astra_api.dependencies.services.build_app_services``）装配并挂入
    # ``AppServices.scheduler``；此处**保留且恒为 ``None``**
    # （同 ``runtime`` / ``skill_resolver``）。
    scheduler_runner: Any | None = None


def is_postgres_url(url: str) -> bool:
    """判断连接串是否为 PostgreSQL（含 ``postgresql+psycopg://`` 等方言后缀）。"""
    scheme = url.split(":", 1)[0].lower()
    backend = scheme.split("+", 1)[0]
    return backend in {"postgresql", "postgres"}


def is_sqlite_url(url: str) -> bool:
    """判断连接串是否为 SQLite。"""
    return url.split(":", 1)[0].lower().startswith("sqlite")


def validate_mode_database_consistency(settings: Settings) -> None:
    """校验 ``mode`` 与 ``database_url`` 的一致性（D4 唯一校验点）。

    Args:
        settings: 生效配置。

    Raises:
        DomainError: 当 mode 与 DB URL 不匹配，或 server 模式缺少 psycopg 驱动时，
            错误码为 ``CONFIGURATION_ERROR``。
    """
    mode = settings.mode
    url = settings.database_url

    if mode == "server":
        if not is_postgres_url(url):
            raise DomainError(
                "ASTRA_MODE=server 需 PostgreSQL 连接串，"
                f"当前 ASTRA_DATABASE_URL={url!r} 非 PostgreSQL；"
                "如需使用 SQLite 请设 ASTRA_MODE=local。",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise DomainError(
                "ASTRA_MODE=server 需 PostgreSQL 驱动 psycopg，请安装 "
                "`astra-database[postgres]`（例如 `uv sync --extra postgres`）；"
                "推荐连接串形如 postgresql+psycopg://user:pass@host:5432/db。",
                code=ErrorCode.CONFIGURATION_ERROR,
            ) from exc
    elif mode == "local":
        if not is_sqlite_url(url):
            raise DomainError(
                "ASTRA_MODE=local 需 SQLite 连接串，"
                f"当前 ASTRA_DATABASE_URL={url!r} 非 SQLite；"
                "如需使用 PostgreSQL 请设 ASTRA_MODE=server。",
                code=ErrorCode.CONFIGURATION_ERROR,
            )


def build_providers(settings: Settings) -> Providers:
    """依据 ``settings.mode`` 自动装配 Provider。

    这是**全平台唯一**允许按 ``ASTRA_MODE`` 分流（并做一致性校验）的位置。

    Args:
        settings: 生效配置。

    Returns:
        装配完成的 :class:`Providers`。

    Raises:
        DomainError: 当 ``mode`` 非法、或 mode 与 DB URL 不一致、或缺少驱动时
            （错误码 ``CONFIGURATION_ERROR``）。
    """
    # 一致性校验（避免静默误配 / 静默降级）。
    validate_mode_database_consistency(settings)

    mode = settings.mode

    # 两模式一致的真实交付物。
    database = _build_database(settings)
    secrets = _build_secret_provider(settings)
    model_registry = _build_model_registry(settings)

    # Phase 1 新增装配位（T1-03）：Model Provider / Router / ToolRegistry / Sandbox /
    # Runtime。对应能力包由 W3–W5 落地；本波次尚未就位 → 延迟导入失败即返回 ``None``
    # （装配**可空**，占位保留）。所有装配仍**只**在本函数内进行（C-01 / D4）。
    phase1_slots = _build_phase1_slots(settings)

    # Phase 2 新增装配位（W2 / T2-08 · T2-11）：Skill / MCP 注册表（能力包就位即装配）。
    phase2_slots = _build_phase2_slots(settings)

    if mode == "local":
        storage = _build_local_storage(settings)
        event_bus = _build_local_event_bus(settings)
        task_queue = _build_inprocess_task_queue(settings)
        scheduler = _build_local_scheduler(settings)
        worker_executor = _build_inprocess_background_executor(settings)
    elif mode == "server":
        # T2-54：server 两档**真实** Provider 闭环（不再装配 UnsupportedXxx 占位）。
        storage = _build_server_storage(settings)
        event_bus = _build_server_event_bus(settings)
        task_queue, queue_is_redis = _build_server_task_queue(settings)
        scheduler = _build_server_scheduler(settings)
        worker_executor = _build_server_worker_executor(settings, task_queue, queue_is_redis)
        _report_server_tier(settings, queue_is_redis)
    else:  # pragma: no cover - Literal 约束下不可达，保留防御
        raise DomainError(
            f"Unsupported ASTRA_MODE: {mode!r}",
            code=ErrorCode.CONFIGURATION_ERROR,
        )

    return Providers(
        settings=settings,
        database=database,
        storage=storage,
        event_bus=event_bus,
        task_queue=task_queue,
        model_registry=model_registry,
        secrets=secrets,
        scheduler=scheduler,
        worker_executor=worker_executor,
        **phase1_slots,
        **phase2_slots,
        memory_store=_build_memory_store(settings, database),
    )


# -- 数据库（已存在） --------------------------------------------------------


def _build_database(settings: Settings) -> DatabaseProvider:
    """构建数据库 Provider。

    延迟导入 ``astra_database`` 以避免 ``config ↔ database`` 的模块级循环依赖。
    """
    from astra_database import create_engine_from_settings, create_session_factory

    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    return DatabaseProvider(engine=engine, session_factory=session_factory)


# -- 机密（D8，两模式一致） --------------------------------------------------


def _build_secret_provider(settings: Settings) -> Any:
    """构建机密提供者（EnvSecretProvider，两模式一致）。"""
    from astra_security import EnvSecretProvider

    secrets_dir = Path(settings.data_dir).expanduser() / "secrets"
    return EnvSecretProvider(prefix="ASTRA_", secrets_dir=secrets_dir)


# -- 模型注册表（两模式一致，Phase 0 真实交付物） ---------------------------


def _build_model_registry(settings: Settings) -> Any:
    """构建模型注册表并注册 StubModelProvider（两模式一致）。"""
    from astra_model import ModelRegistry, StubModelProvider

    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    return registry


# -- Phase 1 装配位（T1-03：占位可空 + 函数级延迟导入） ---------------------


def _build_phase1_slots(settings: Settings) -> dict[str, Any]:
    """构建 Phase 1 新增装配位（Model Provider / Router / ToolRegistry / Sandbox / Runtime）。

    各能力包由 **W3–W5** 落地；本波次尚未就位，``_build_optional`` 会因导入失败
    返回 ``None``（装配位**可空**）。当能力包就位后，仅需其提供约定的工厂函数，
    无需改动本模块的结构。

    Args:
        settings: 生效配置。

    Returns:
        以 :class:`Providers` 字段名为键的装配结果字典。
    """
    return {
        "model_providers": _build_optional(
            settings, module="astra_model.providers", factory="build_model_providers"
        ),
        "model_router": _build_optional(
            settings, module="astra_model.router", factory="build_model_router"
        ),
        "tool_registry": _build_optional(
            settings, module="astra_tool", factory="build_tool_registry"
        ),
        "sandbox": _build_optional(
            settings, module="astra_sandbox", factory="build_sandbox_provider"
        ),
        # W6 / A30：``runtime`` 槽位**保留且恒为 ``None``**——``AgentRuntime`` 需多依赖
        # DI，由**组合根**（``astra_api.dependencies.services.build_app_services``）经
        # ``AgentRuntime.build(...)`` 装配；**不新增 ``build_runtime``**（裁定 §6.2）。
        "runtime": None,
    }


def _build_phase2_slots(settings: Settings) -> dict[str, Any]:
    """构建 Phase 2 新增装配位（W2 / T2-08 · T2-11；裁定 §14.1）。

    - ``skill_registry`` / ``mcp_registry``：走 ``_build_optional``（能力包就位即装配，
      工厂缺失回落 ``None``）；
    - ``skill_resolver`` / ``mcp_executor``：因 DI 依赖多，由**组合根**（``AppServices``）
      装配并传入 ``AgentRuntime.build(...)``，此处恒 ``None``。

    Args:
        settings: 生效配置。

    Returns:
        以 :class:`Providers` 字段名为键的装配结果字典。
    """
    return {
        "skill_registry": _build_optional(
            settings, module="astra_skill", factory="build_skill_registry"
        ),
        "mcp_registry": _build_optional(settings, module="astra_mcp", factory="build_mcp_registry"),
        "skill_resolver": None,
        "mcp_executor": None,
    }


def _build_memory_store(settings: Settings, database: DatabaseProvider | None) -> Any | None:
    """装配 Memory 存储抽象（W6 / T2-34；能力选路，仿 knowledge；裁决 §2.2）。

    - ``vector_search=true``（PostgreSQL + pgvector）→ ``VectorMemoryStore``；
      否则 → ``SqlMemoryStore``（SQLite / PG 同实现）；
    - ``vector_search`` 三态按 **dialect + ``pg_extension`` 确定性探测**解析
      （**非 try/except 推断**）；
    - 能力包 / 工厂缺失 → ``None``（装配位保留，**函数级延迟导入**避免循环依赖）；
    - **占位 / 未就绪的 Database Provider**（如 server 占位装配 ``session_factory=object()``）
      → ``None``（**确定性判定**，**非** try/except 能力推断）。

    Args:
        settings: 生效配置。
        database: 数据库 Provider（提供 ``session_factory``）。

    Returns:
        已装配的 ``MemoryStore``，或 ``None``（能力包未就位 / 数据库 Provider 未就绪）。
    """
    if database is None:
        return None
    session_factory = getattr(database, "session_factory", None)
    if not callable(session_factory):
        # 占位 Database Provider（能力选路的 dialect 探测依赖可调用会话工厂）→ 装配位保留为空。
        return None
    try:
        from astra_memory import build_memory_store, resolve_memory_vector_capability
    except ImportError:
        return None
    vector_search = resolve_memory_vector_capability(
        explicit=settings.capability.vector_search,
        session_factory=session_factory,
    )
    return build_memory_store(
        session_factory=session_factory,
        vector_search=vector_search,
        embedding_dimensions=settings.capability.embedding_dimensions,
    )


def _build_optional(settings: Settings, *, module: str, factory: str) -> Any | None:
    """延迟导入能力包工厂并构建；能力包 / 工厂缺失时返回 ``None``（装配位保留）。

    以**字符串**指定模块名，导入发生在**函数级**（而非模块级），避免
    ``config ↔ 能力包`` 的模块级循环依赖。

    Args:
        settings: 生效配置。
        module: 能力包模块名（如 ``astra_model.providers``）。
        factory: 模块内工厂函数名（如 ``build_model_providers``）。

    Returns:
        工厂构建结果；模块或工厂不存在时返回 ``None``。
    """
    try:
        target = importlib.import_module(module)
    except ImportError:
        return None
    builder = getattr(target, factory, None)
    if builder is None:
        return None
    return builder(settings)


# -- local 模式：真实实现 ----------------------------------------------------


def _build_local_storage(settings: Settings) -> Any:
    """构建本地文件存储（``{data_dir}/storage/``）。"""
    from astra_storage import create_local_file_storage

    base_dir = Path(settings.data_dir).expanduser() / "storage"
    return create_local_file_storage(base_dir)


def _build_local_event_bus(settings: Settings) -> Any:
    """构建进程内事件总线。"""
    from astra_event import create_local_event_bus

    return create_local_event_bus()


def _build_inprocess_task_queue(settings: Settings) -> Any:
    """构建进程内任务队列。"""
    from astra_task import create_inprocess_task_queue

    return create_inprocess_task_queue()


def _build_inprocess_background_executor(settings: Settings) -> Any:
    """构建进程内后台执行体（社区默认；线程池 + 驱动 task 状态机）。"""
    from astra_task import InProcessBackgroundExecutor

    return InProcessBackgroundExecutor()


def _build_local_scheduler(settings: Settings) -> Any:
    """构建本地调度器（懒启动）。"""
    from astra_task import create_local_scheduler

    return create_local_scheduler()


# -- server 模式：两档真实装配（T2-54：Community 基础档 / Compose·Team 档） ------


def _build_server_storage(settings: Settings) -> Any:
    """server 基础档：**本地持久**文件存储（LocalFileStorage）。

    设计 §2.8.1：``ASTRA_MODE=server`` **不得**因模式本身把 ``storage`` 装配成
    ``UnsupportedStorage``。基础档以**本地持久存储**完成可运行闭环；S3/MinIO 属
    **未交付的增强**（后续波次），本增量**不**以占位对象冒充，而是直接使用本地实现。
    """
    return _build_local_storage(settings)


def _build_server_event_bus(settings: Settings) -> Any:
    """server 基础档：进程内事件总线（LocalEventBus）。

    设计 §2.8.1：server 模式**不得**把 ``event_bus`` 装配成 ``UnsupportedEventBus``；
    Redis Stream 事件总线属**未交付的增强**，本增量使用进程内事件总线完成闭环。
    """
    return _build_local_event_bus(settings)


def _build_server_scheduler(settings: Settings) -> Any:
    """server 基础档：本地调度器（LocalScheduler）。

    设计 §2.8.1：server 模式**不得**把 ``scheduler`` 装配成 ``UnsupportedScheduler``；
    分布式调度属**未交付的增强**，本增量使用本地调度器完成闭环。
    """
    return _build_local_scheduler(settings)


def _build_server_task_queue(settings: Settings) -> tuple[Any, bool]:
    """构建 server 任务队列（Community 基础档 ↔ Compose·Team 档）。

    分档规则（T2-54 / 设计 §2.8.1）：

    - **未配置** ``ASTRA_REDIS_URL`` → Community 基础档：``InProcessTaskQueue``
      （**真实**进程内队列，可运行闭环；**非** ``UnsupportedTaskQueue`` 占位）；
    - **已配置** ``ASTRA_REDIS_URL`` 且 ``astra-task[redis]`` 就位 → Compose·Team 档：
      :class:`~astra_task.queue.redis.RedisTaskQueue`；
    - **已配置** ``ASTRA_REDIS_URL`` 但缺少可选依赖（``astra-task[redis]`` /
      ``redis`` 客户端）→ **装配期**抛 ``DomainError(CONFIGURATION_ERROR)``
      （**明确配置错误**，**不**装配占位后延迟到首次请求才失败）。

    Args:
        settings: 生效配置。

    Returns:
        ``(task_queue, queue_is_redis)``。

    Raises:
        DomainError: 显式配置 Redis 但缺少可选依赖（``CONFIGURATION_ERROR``）。
    """
    redis_url = getattr(settings, "redis_url", "") or ""
    if not redis_url:
        # Community 基础档：进程内队列（真实实现，非占位）。
        return _build_inprocess_task_queue(settings), False
    try:
        from astra_task.queue.redis import RedisTaskQueue, redis_available
    except ImportError as exc:  # pragma: no cover - astra_task 缺失（装配不可达）
        raise DomainError(
            "已配置 ASTRA_REDIS_URL 但未安装 astra-task[redis]（redis + arq）；"
            "请执行 `uv sync --extra redis`，或清空 ASTRA_REDIS_URL 以使用进程内队列"
            "（Community 基础档）。",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"field": "redis_url", "extra": "redis"},
        ) from exc
    if not redis_available():
        raise DomainError(
            "已配置 ASTRA_REDIS_URL 但 Redis 客户端不可用（缺少 redis 依赖）；"
            "请安装 `astra-task[redis]`，或清空 ASTRA_REDIS_URL 以使用进程内队列。",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"field": "redis_url", "extra": "redis"},
        )
    return RedisTaskQueue(redis_url=redis_url), True


def _build_server_worker_executor(settings: Settings, task_queue: Any, queue_is_redis: bool) -> Any:
    """构建 server 后台执行体（与队列分档一致，**均为真实实现**）。

    - Compose·Team 档（Redis 队列就位）→ :class:`WorkerProcessExecutor`（独立 Worker 进程消费）；
    - Community 基础档 → :class:`InProcessBackgroundExecutor`（线程池 + 任务状态机）。

    🔴 两档均**不**回落 ``UnsupportedBackgroundExecutor`` 占位（T2-54 闭环要求）。

    Args:
        settings: 生效配置。
        task_queue: 本模式装配的任务队列。
        queue_is_redis: ``task_queue`` 是否为 Redis 实现。

    Returns:
        :class:`WorkerProcessExecutor` 或 :class:`InProcessBackgroundExecutor`。
    """
    from astra_task import InProcessBackgroundExecutor, WorkerProcessExecutor

    if queue_is_redis:
        return WorkerProcessExecutor(task_queue=task_queue)
    return InProcessBackgroundExecutor()


def _report_server_tier(settings: Settings, queue_is_redis: bool) -> None:
    """以结构化日志报告 server 档位（**非静默**：显式声明实际装配的档位）。

    Args:
        settings: 生效配置。
        queue_is_redis: ``task_queue`` 是否为 Redis 实现（True → Compose·Team 档）。
    """
    _logger.info(
        "provider.server_tier",
        extra={
            "event": "provider.server_tier",
            "mode": settings.mode,
            "tier": "compose" if queue_is_redis else "community",
            "queue": "redis" if queue_is_redis else "inprocess",
            "worker_executor": "worker_process" if queue_is_redis else "inprocess",
        },
    )


# -- 占位工厂（保留：显式构造 / 陈测试引用；build_providers 不再使用） ---------


def _build_unsupported_storage(settings: Settings) -> Any:
    """显式构造 server 存储占位（S3/MinIO）。

    🔴 ``build_providers`` **不再**在 server 模式装配本占位（T2-54 闭环）；本工厂保留供
    **显式构造**与既有陈测试引用（如 ``test_config_mode_branch``）。
    """
    from astra_storage import UnsupportedStorage

    return UnsupportedStorage(feature="S3/MinIO 存储", available_in="Team")


def _build_unsupported_event_bus(settings: Settings) -> Any:
    """显式构造 server 事件总线占位（Redis Stream）。

    🔴 ``build_providers`` **不再**装配本占位（T2-54）；保留供显式构造 / 陈测试引用。
    """
    from astra_event import UnsupportedEventBus

    return UnsupportedEventBus(feature="Redis Stream 事件总线", available_in="Team")


def _build_unsupported_task_queue(settings: Settings) -> Any:
    """显式构造 server 任务队列占位（Redis 队列）。

    🔴 ``build_providers`` **不再**装配本占位（T2-54）；保留供显式构造 / 陈测试引用。
    """
    from astra_task import UnsupportedTaskQueue

    return UnsupportedTaskQueue(feature="Redis 任务队列", available_in="Team")


def _build_unsupported_scheduler(settings: Settings) -> Any:
    """显式构造 server 调度器占位（分布式调度）。

    🔴 ``build_providers`` **不再**装配本占位（T2-54）；保留供显式构造 / 陈测试引用。
    """
    from astra_task import UnsupportedScheduler

    return UnsupportedScheduler(feature="分布式调度器", available_in="Team")
