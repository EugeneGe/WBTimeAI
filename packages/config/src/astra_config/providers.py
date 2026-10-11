"""Provider 自动装配工厂（决策 D4 —— 业务代码不判断环境）。

🔴 **本模块是 ``ASTRA_MODE=local|server`` 分流的唯一允许位置**（含 mode 与
   DB URL 的一致性校验）。上层（如 ``apps/api``）仅通过 ``dependencies/container.py``
   获取 :class:`Providers`，不得出现 ``if mode == ...``。

本轮（W2 / T0-16）收口装配：``database`` / ``storage`` / ``event_bus`` / ``task_queue`` /
``model_registry`` / ``secrets`` / ``scheduler``。

Phase 1（T1-03）扩展装配位：``model_providers`` / ``model_router`` / ``tool_registry`` /
``sandbox`` / ``runtime``（**占位可空**：对应能力包由 W3–W5 落地，**函数级延迟导入**，
未就位时为 ``None``，装配位保留）。

设计取舍（避免静默降级）：
- ``mode=local``：SQLite + **真实**进程内能力（LocalFileStorage / LocalEventBus /
  InProcessTaskQueue / LocalScheduler）；
- ``mode=server``：PostgreSQL + 外部中间件；尚未实现的能力装配为**占位对象**
  （首次调用抛 ``NotImplementedYetError``），并打印结构化 ``WARNING``——
  应用**仍可启动**（行为降级而非模块缺失，对齐验收 #14）。
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
        storage = _build_unsupported_storage(settings)
        event_bus = _build_unsupported_event_bus(settings)
        task_queue, queue_is_redis = _build_server_task_queue(settings)
        scheduler = _build_unsupported_scheduler(settings)
        worker_executor = _build_worker_process_executor(settings, task_queue, queue_is_redis)
        _warn_placeholders(settings, task_queue_is_placeholder=not queue_is_redis)
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


# -- server 模式：Redis 优先 + 占位回落（W1 / T2-02；非静默） ---------------


def _build_server_task_queue(settings: Settings) -> tuple[Any, bool]:
    """构建 server 任务队列：**Redis 优先、占位回落**（W1 裁定 §3.2）。

    当且仅当「``redis_url`` 已配置 **且** ``astra-task[redis]`` 可导入」时构建
    :class:`~astra_task.queue.redis.RedisTaskQueue`；否则回落既有
    :class:`~astra_task.placeholder.UnsupportedTaskQueue`——回落由
    :func:`_warn_placeholders` 以结构化 ``WARNING`` **非静默** 报告。

    Args:
        settings: 生效配置。

    Returns:
        ``(task_queue, queue_is_redis)``。
    """
    redis_url = getattr(settings, "redis_url", "")
    if not redis_url:
        return _build_unsupported_task_queue(settings), False
    try:
        from astra_task.queue.redis import RedisTaskQueue, redis_available
    except ImportError:  # pragma: no cover - astra_task 缺失（装配不可达）
        return _build_unsupported_task_queue(settings), False
    if not redis_available():
        return _build_unsupported_task_queue(settings), False
    return RedisTaskQueue(redis_url=redis_url), True


def _build_worker_process_executor(
    settings: Settings, task_queue: Any, queue_is_redis: bool
) -> Any:
    """构建 server 后台执行体：Redis 就绪 → ``WorkerProcessExecutor``，否则占位回落。

    Args:
        settings: 生效配置。
        task_queue: 本模式装配的任务队列。
        queue_is_redis: ``task_queue`` 是否为 Redis 实现。

    Returns:
        执行体（:class:`WorkerProcessExecutor` 或 :class:`UnsupportedBackgroundExecutor`）。
    """
    from astra_task import UnsupportedBackgroundExecutor, WorkerProcessExecutor

    if queue_is_redis:
        return WorkerProcessExecutor(task_queue=task_queue)
    return UnsupportedBackgroundExecutor(feature="Worker 进程执行体", available_in="Team")


# -- server 模式：占位（非静默；首次调用抛 NotImplementedYetError） ---------


def _build_unsupported_storage(settings: Settings) -> Any:
    """server 占位：S3/MinIO 存储。"""
    from astra_storage import UnsupportedStorage

    return UnsupportedStorage(feature="S3/MinIO 存储", available_in="Team")


def _build_unsupported_event_bus(settings: Settings) -> Any:
    """server 占位：Redis Stream 事件总线。"""
    from astra_event import UnsupportedEventBus

    return UnsupportedEventBus(feature="Redis Stream 事件总线", available_in="Team")


def _build_unsupported_task_queue(settings: Settings) -> Any:
    """server 占位：Redis 任务队列。"""
    from astra_task import UnsupportedTaskQueue

    return UnsupportedTaskQueue(feature="Redis 任务队列", available_in="Team")


def _build_unsupported_scheduler(settings: Settings) -> Any:
    """server 占位：分布式调度器。"""
    from astra_task import UnsupportedScheduler

    return UnsupportedScheduler(feature="分布式调度器", available_in="Team")


def _warn_placeholders(settings: Settings, *, task_queue_is_placeholder: bool = True) -> None:
    """对 server 模式下的占位能力打印结构化 WARNING（不静默降级）。

    Args:
        settings: 生效配置。
        task_queue_is_placeholder: ``task_queue`` 是否为占位实现（Redis 就绪时
            **不**误报占位）。``worker_executor`` 与 ``task_queue`` 同步回落，
            其占位一并由 ``task_queue`` 告警体现。
    """
    placeholders = [
        ("storage", "S3/MinIO 存储", "Team"),
        ("event_bus", "Redis Stream 事件总线", "Team"),
    ]
    if task_queue_is_placeholder:
        placeholders.append(("task_queue", "Redis 任务队列", "Team"))
    placeholders.append(("scheduler", "分布式调度器", "Team"))
    for capability, target, phase in placeholders:
        _logger.warning(
            "provider.placeholder",
            extra={
                "event": "provider.placeholder",
                "mode": settings.mode,
                "capability": capability,
                "implementation": target,
                "available_in": phase,
            },
        )
