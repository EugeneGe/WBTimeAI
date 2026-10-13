"""``astra doctor`` 自检项集合（决策 D5 / 设计 §2.1 / T1-05）。

每个自检项返回 ``(name, status, detail)``：

- ``name``：检查名（稳定标识）；
- ``status``：``"ok"``（通过）/ ``"fail"``（失败）/ ``"skip"``（跳过 / 不适用）；
- ``detail``：面向人的详情（**绝不包含密钥明文**）。

自检项：配置 / 数据库 / 迁移 / 目录 / 依赖（Phase 0 既有）+ **Docker 运行时可探测性**
+ **Model Provider 配置 / 凭证可达性（掩码）**（Phase 1 新增）+ **Worker 可达性（仅探测）**
（W1 / T2-02 新增）。

🔴 本模块**不判断 mode**（C-01）；探测结果仅为**事实陈述**，不改变装配
（装配仍仅在 ``astra_config.providers.build_providers``）。Docker 项**仅探测**，
**不触发**任何 Sandbox / 容器执行（核心原则 ⑪）。
"""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from astra_config import Settings

__all__ = [
    "CheckStatus",
    "CheckOutcome",
    "load_settings",
    "check_database",
    "check_migrations",
    "check_directories",
    "check_dependencies",
    "check_docker",
    "check_provider",
    "check_worker",
    "check_capabilities",
    "check_registry_wiring",
    "evaluate_registry_wiring",
    "build_providers_for_checks",
    "dispose_providers",
]

#: 自检状态。
CheckStatus = Literal["ok", "fail", "skip"]

#: 单项自检结果三元组。
CheckOutcome = tuple[str, CheckStatus, str]

# -- J-1 装配可达性（registry_wiring）----------------------------------------
#: **必填且非空**的注册表槽位（config 装配期即应填充；空即「注册表未接线」）。
#: 依据：V0.4.1 · J-1（R5A-01 同型：注册点未接线 → 产品恒降级）。
_REQUIRED_NONEMPTY_REGISTRIES: tuple[str, ...] = ("model_registry", "tool_registry")

#: **结构就位即可**的注册表槽位（启动 / 发现期由组合根填充，装配期可空，属**正常态**）。
#: 🔴 local 社区模式（无 Docker / dist）下技能 / MCP 目录可缺 → 空注册表**不得**判 FAIL。
_OPTIONAL_REGISTRIES: tuple[str, ...] = ("skill_registry", "mcp_registry")

#: 占位实现类**名前缀**（`UnsupportedXxx` 型；「恒空 / 恒抛却报可用」的非静默降级占位）。
_PLACEHOLDER_CLASS_PREFIXES: tuple[str, ...] = ("Unsupported", "Placeholder")


def load_settings() -> tuple[CheckOutcome, Settings | None]:
    """检查 1：配置加载。

    Returns:
        ``((name, status, detail), settings | None)``。
    """
    try:
        from astra_config import get_settings

        settings = get_settings()
        return ("config", "ok", f"mode={settings.mode}"), settings
    except Exception as exc:  # noqa: BLE001 - doctor 需捕获所有异常并汇报
        return ("config", "fail", f"{type(exc).__name__}: {exc}"), None


def check_database(settings: Settings | None) -> CheckOutcome:
    """检查 2：DB 连通（``SELECT 1``）。"""
    if settings is None:
        return ("database", "skip", "配置未加载，跳过")
    try:
        from sqlalchemy import text
    except Exception as exc:  # noqa: BLE001
        return ("database", "fail", f"sqlalchemy 不可用：{exc}")
    try:
        from astra_database import create_engine_from_settings

        engine = create_engine_from_settings(settings)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        url = getattr(settings, "database_url", "")
        return ("database", "ok", f"connected ({url.split(':', 1)[0]})")
    except Exception as exc:  # noqa: BLE001
        return ("database", "fail", f"{type(exc).__name__}: {exc}")


def check_migrations(settings: Settings | None) -> CheckOutcome:
    """检查 3：迁移版本（``alembic_version`` 或核心表就位）。"""
    if settings is None:
        return ("migrations", "skip", "配置未加载，跳过")
    try:
        from astra_database import create_engine_from_settings
        from sqlalchemy import inspect, text

        engine = create_engine_from_settings(settings)
        try:
            tables = set(inspect(engine).get_table_names())
            if "alembic_version" in tables:
                with engine.connect() as connection:
                    version = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar()
                if version:
                    return ("migrations", "ok", f"revision={version}")
                return ("migrations", "fail", "alembic_version 为空")
            if "user" in tables:
                return ("migrations", "ok", "schema 就位（未版本化）")
            return ("migrations", "fail", "未发现 schema（请先执行 astra init）")
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001
        return ("migrations", "fail", f"{type(exc).__name__}: {exc}")


def check_directories(settings: Settings | None) -> CheckOutcome:
    """检查 4：数据目录可写。"""
    try:
        from astra_cli.paths import resolve_data_dir

        data_dir = resolve_data_dir(getattr(settings, "data_dir", None) if settings else None)
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".doctor-", delete=True):
            pass
        return ("directories", "ok", f"writable: {data_dir}")
    except Exception as exc:  # noqa: BLE001
        return ("directories", "fail", f"{type(exc).__name__}: {exc}")


def check_dependencies() -> CheckOutcome:
    """检查 5：关键依赖版本。"""
    parts: list[str] = []
    try:
        import fastapi
        import sqlalchemy
        import typer as _typer

        parts.append(f"fastapi={fastapi.__version__}")
        parts.append(f"sqlalchemy={sqlalchemy.__version__}")
        parts.append(f"typer={_typer.__version__}")
        return ("dependencies", "ok", ", ".join(parts))
    except Exception as exc:  # noqa: BLE001
        return ("dependencies", "fail", f"{type(exc).__name__}: {exc}")


def _docker_daemon_reachable() -> bool:
    """探测 Docker 守护进程可达性（**仅探测**，不创建 / 运行任何容器）。

    与装配侧（:func:`astra_sandbox.availability.docker_available`）**同源**：以 docker
    **SDK** ``docker.from_env().ping()`` 判定，而非 docker CLI 是否存在——镜像可能仅含
    SDK（无 CLI），旧 CLI 判定会误报（F-2）。
    """
    try:
        from astra_sandbox.availability import docker_available
    except Exception:  # noqa: BLE001 - 探测不可用即视为不可达（doctor 容错）
        return False
    return docker_available()


def check_docker(settings: Settings | None) -> CheckOutcome:
    """检查 6：Sandbox 运行时可探测性（**仅探测**，不触发 Sandbox 执行）。

    判定与装配侧 :func:`astra_sandbox.availability.docker_sdk_status` **同源**（SDK +
    ``ping``，**非** docker CLI），保证「doctor 语义 == capabilities 装配语义」（F-2）。

    语义：
    - 未安装 docker **SDK** → ``skip``（社区 LocalProcess 降级，非错误）；
    - SDK 就位且守护进程可达 → ``ok``；
    - SDK 就位但守护进程不可达：若 ``ASTRA_SANDBOX_PROVIDER=docker``（显式要求 Docker）
      → ``fail``（配置与运行时不符，明确报错）；否则 → ``skip``。
    """
    provider = getattr(settings, "sandbox_provider", "local_process") if settings else None
    try:
        from astra_sandbox.availability import docker_sdk_status
    except Exception as exc:  # noqa: BLE001 - astra_sandbox 不可用按跳过处理
        return ("docker", "skip", f"astra_sandbox 不可用：{type(exc).__name__}: {exc}")
    status = docker_sdk_status()
    if status == "no_sdk":
        if provider == "docker":
            return ("docker", "fail", "ASTRA_SANDBOX_PROVIDER=docker 但未安装 docker SDK")
        return ("docker", "skip", "docker SDK 未安装（社区以 LocalProcess 降级）")
    if status == "reachable":
        return ("docker", "ok", "docker daemon 可达（SDK ping 成功）")
    if provider == "docker":
        return ("docker", "fail", "ASTRA_SANDBOX_PROVIDER=docker 但 docker daemon 不可达")
    return ("docker", "skip", "docker SDK 存在但 daemon 不可达")


def check_provider(settings: Settings | None) -> CheckOutcome:
    """检查 7：Model Provider 配置 / 凭证可达性（**掩码**，不打印明文）。

    - 通过 :class:`~astra_security.EnvSecretProvider` 取主密钥并校验 **≥32B**；
      失败（缺失 / 过短）→ ``fail``，详情仅含**长度**，不含密钥内容；
    - 顺带报告默认 Model Provider（仅名称，非机密）。
    """
    if settings is None:
        return ("provider", "skip", "配置未加载，跳过")
    try:
        from astra_security import EnvSecretProvider
    except Exception as exc:  # noqa: BLE001
        return ("provider", "fail", f"astra_security 不可用：{exc}")

    provider = EnvSecretProvider()
    try:
        value = provider.get_secret_key()
    except Exception as exc:  # noqa: BLE001 - 详情不含明文（仅长度）
        message = getattr(exc, "message", None) or str(exc)
        return ("provider", "fail", message)

    length = len(value.encode("utf-8"))
    model = getattr(settings, "model_default_provider", "") or "未配置"
    return (
        "provider",
        "ok",
        f"master_key=****(len={length} ≥32B); model_default_provider={model}",
    )


def _mask_redis_url(url: str) -> str:
    """掩码 Redis 连接串中的凭证（``redis://user:pass@host`` → ``redis://***@host``）。"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


def check_worker(settings: Settings | None) -> CheckOutcome:
    """检查 8：Worker 可达性（W1 · T2-02；**仅探测**，不触发执行）。

    语义（**仅事实陈述**，CLI 不判断 mode）：

    - 未配置 Redis（``ASTRA_REDIS_URL`` 为空）→ ``ok``：进程内执行体，无需独立进程；
    - 已配置 Redis 但未安装 ``astra-task[redis]`` → ``skip`` + 提示（回落占位，非错误）；
    - 已配置 Redis 且 extra 就位 → 探测 ``RedisTaskQueue`` 可构造性（**不连接**）
      → ``ok`` / ``fail``。

    🔴 本项**只探测**，不触发任何任务执行；详情**绝不包含** Redis 凭证明文（掩码）。
    """
    if settings is None:
        return ("worker", "skip", "配置未加载，跳过")
    redis_url = getattr(settings, "redis_url", "") or ""
    if not redis_url:
        return (
            "worker",
            "ok",
            "queue=inprocess; executor=inprocess（本地进程内执行体，无需独立 worker 进程）",
        )
    try:
        from astra_task.queue.redis import RedisTaskQueue, redis_available
    except Exception as exc:  # noqa: BLE001 - doctor 需捕获所有异常并汇报
        return ("worker", "skip", f"astra_task 不可用：{type(exc).__name__}: {exc}")
    if not redis_available():
        return ("worker", "skip", "已配置 Redis 但未安装 astra-task[redis]（redis + arq）")
    try:
        RedisTaskQueue(redis_url=redis_url)  # 仅构造，不建立连接
    except Exception as exc:  # noqa: BLE001
        return ("worker", "fail", f"{type(exc).__name__}: {exc}")
    return (
        "worker",
        "ok",
        f"queue=redis; executor=worker_process; url={_mask_redis_url(redis_url)}",
    )


def _describe_capabilities(providers: object, settings: Settings | None) -> tuple[list[str], str]:
    """把装配完成的 Provider 容器归类为可读能力描述（T2-54）。

    仅做**事实陈述**（不判断 mode）；同时识别**显式的 ``UnsupportedXxx`` 占位**——
    server 模式**不得**装配成占位（设计 §2.8.1 / T2-54）。

    Args:
        providers: :class:`astra_config.providers.Providers` 实例。
        settings: 生效配置（读 DB dialect）。

    Returns:
        ``(unsupported, detail)``——``unsupported`` 为检测到的占位槽名列表；
        ``detail`` 为面向人的能力描述串。
    """
    from astra_event import UnsupportedEventBus
    from astra_storage import UnsupportedStorage
    from astra_task import (
        UnsupportedBackgroundExecutor,
        UnsupportedScheduler,
        UnsupportedTaskQueue,
    )

    unsupported: list[str] = []
    parts: list[str] = []

    url = getattr(settings, "database_url", "") or ""
    dialect = url.split(":", 1)[0].split("+", 1)[0] or "?"
    parts.append(f"db={dialect}")

    storage = getattr(providers, "storage", None)
    if isinstance(storage, UnsupportedStorage):
        unsupported.append("storage")
        parts.append("storage=unsupported")
    else:
        parts.append(f"storage={type(storage).__name__ if storage is not None else 'none'}")

    event_bus = getattr(providers, "event_bus", None)
    if isinstance(event_bus, UnsupportedEventBus):
        unsupported.append("event_bus")
        parts.append("event_bus=unsupported")
    else:
        parts.append(f"event_bus={type(event_bus).__name__ if event_bus is not None else 'none'}")

    task_queue = getattr(providers, "task_queue", None)
    if isinstance(task_queue, UnsupportedTaskQueue):
        unsupported.append("task_queue")
        parts.append("queue=unsupported")
    else:
        parts.append(f"queue={type(task_queue).__name__ if task_queue is not None else 'none'}")

    scheduler = getattr(providers, "scheduler", None)
    if isinstance(scheduler, UnsupportedScheduler):
        unsupported.append("scheduler")
        parts.append("scheduler=unsupported")
    else:
        parts.append(f"scheduler={type(scheduler).__name__ if scheduler is not None else 'none'}")

    worker = getattr(providers, "worker_executor", None)
    if isinstance(worker, UnsupportedBackgroundExecutor):
        unsupported.append("worker_executor")
        parts.append("worker=unsupported")
    else:
        parts.append(f"worker={type(worker).__name__ if worker is not None else 'none'}")

    sandbox = getattr(providers, "sandbox", None)
    sandbox_kind = getattr(sandbox, "kind", None)
    parts.append(f"sandbox={sandbox_kind or (type(sandbox).__name__ if sandbox else 'none')}")

    return unsupported, "; ".join(parts)


# -- 共享装配（capabilities / registry_wiring 复用一次 build_providers）-------
# 说明：``build_providers`` 属组合根装配，成本较高；``astra doctor`` 内两项自检
# （capabilities / registry_wiring）**共享同一次装配**，避免重复装配拖慢自检。


def build_providers_for_checks(settings: Settings) -> tuple[object | None, str | None]:
    """构建 ``Providers``（供 capabilities / registry_wiring 共享）。

    Args:
        settings: 生效配置。

    Returns:
        ``(providers | None, error | None)``——成功 ``(providers, None)``；
        失败 ``(None, message)``（**不抛异常**，由调用方转自检结论）。
    """
    try:
        from astra_config.providers import build_providers
    except Exception as exc:  # noqa: BLE001 - doctor 需捕获所有异常并汇报
        return None, f"astra_config 不可用：{type(exc).__name__}: {exc}"
    try:
        return build_providers(settings), None
    except Exception as exc:  # noqa: BLE001 - 装配失败即 capability 错误（明确报错）
        return None, f"Provider 装配失败：{type(exc).__name__}: {exc}"


def dispose_providers(providers: object) -> None:
    """释放 ``Providers`` 持有的数据库引擎（**不泄漏连接**；失败不影响自检结论）。"""
    database = getattr(providers, "database", None)
    engine = getattr(database, "engine", None)
    dispose = getattr(engine, "dispose", None)
    if callable(dispose):
        try:
            dispose()
        except Exception:  # noqa: BLE001 - 释放失败不影响自检结论
            pass


def check_capabilities(
    settings: Settings | None, *, providers: object | None = None
) -> CheckOutcome:
    """检查 9：Server Provider 能力闭环（T2-54；设计 §2.8.1）。

    以**实际装配**为准（复用 ``build_providers``），报告 SQLite/PostgreSQL（DB）、
    Storage、Queue、Scheduler、Worker、Sandbox 六项能力，并**显式检出**任何
    ``UnsupportedXxx`` 占位——server 模式**不得**因模式本身装配成占位（延迟到首次请求
    才失败）。检测到占位 → ``fail``（明确配置 / capability 错误）。

    🔴 本项**只装配 + 检视**，不触发任何 Task 执行；详情**不含**任何凭证明文。装配成功
    后立即释放数据库引擎（不泄漏连接）。

    Args:
        settings: 生效配置。

    Returns:
        ``("capabilities", status, detail)``。
    """
    if settings is None:
        return ("capabilities", "skip", "配置未加载，跳过")
    owned = providers is None
    if owned:
        providers, error = build_providers_for_checks(settings)
        if providers is None:
            return ("capabilities", "fail", error or "Provider 装配失败")

    try:
        unsupported, detail = _describe_capabilities(providers, settings)
    finally:
        if owned:
            dispose_providers(providers)

    if unsupported:
        return (
            "capabilities",
            "fail",
            f"检测到 Unsupported 占位（server 不应装配为占位）：{', '.join(unsupported)}；{detail}",
        )
    return ("capabilities", "ok", detail)


# -- J-1 装配可达性（registry_wiring）----------------------------------------


def _registry_size(obj: object) -> int | None:
    """探测注册表**条目数**（结构断言，**非**运行时伪探针）。

    依次尝试 ``names()`` / ``list()`` / ``all()``（注册表公开 API），回退 ``len()``；
    均不可量化 → ``None``（如：该槽位并非集合型注册表）。
    """
    for attr in ("names", "list", "all"):
        member = getattr(obj, attr, None)
        if callable(member):
            try:
                return len(list(member()))
            except Exception:  # noqa: BLE001 - 探测失败即尝试下一 API
                continue
    if hasattr(obj, "__len__"):
        try:
            return len(obj)
        except Exception:  # noqa: BLE001
            return None
    return None


def _is_placeholder(obj: object) -> bool:
    """是否为**占位实现**（``UnsupportedXxx`` / ``PlaceholderXxx`` 型）。"""
    return type(obj).__name__.startswith(_PLACEHOLDER_CLASS_PREFIXES)


def _declares_available(obj: object) -> bool:
    """对象是否**自称可用**（``available`` / ``is_available`` 布尔真）。

    「出口非占位」维度：恒空 / 恒 ``None`` 的实现**不得**报 ``available=true``
    （R5A-02 型：占位恒空却报可用）。此处仅做**结构读取**，不引入运行时探针。
    """
    for attr in ("available", "is_available"):
        if not hasattr(obj, attr):
            continue
        member = getattr(obj, attr, None)
        if callable(member):
            try:
                member = member()
            except Exception:  # noqa: BLE001 - 读取失败视为未声明可用
                return False
        return bool(member)
    return False


def evaluate_registry_wiring(providers: object) -> tuple[list[str], str]:
    """按装配结构评估注册表接线（纯函数，供单测直接构造 ``Providers`` 调用）。

    断言：
    1. **注册表非空**——``model_registry`` / ``tool_registry``（装配期应填充）不得为空；
       ``skill_registry`` / ``mcp_registry`` 结构就位即可（装配期可空的**正常态**）；
    2. **出口非占位**——槽位不得为 ``UnsupportedXxx`` 占位；恒空实现不得自称 ``available``。

    Args:
        providers: :class:`astra_config.providers.Providers`（或同结构桩）。

    Returns:
        ``(problems, detail)``——``problems`` 为问题描述列表（空 = 通过）；
        ``detail`` 为面向人的结构描述串。
    """
    problems: list[str] = []
    parts: list[str] = []
    for name in (*_REQUIRED_NONEMPTY_REGISTRIES, *_OPTIONAL_REGISTRIES):
        required = name in _REQUIRED_NONEMPTY_REGISTRIES
        obj = getattr(providers, name, None)
        if obj is None:
            if required:
                problems.append(f"{name}=未装配")
                parts.append(f"{name}=none")
            else:
                parts.append(f"{name}=none(可选)")
            continue
        if _is_placeholder(obj):
            problems.append(f"{name}=占位({type(obj).__name__})")
            parts.append(f"{name}=placeholder")
            continue
        size = _registry_size(obj)
        if size is None:
            parts.append(f"{name}={type(obj).__name__}")
            continue
        parts.append(f"{name}={size}")
        if size == 0:
            if required:
                problems.append(f"{name}=空注册表")
            if _declares_available(obj):
                problems.append(f"{name}=自称 available 但为空")
    return problems, "; ".join(parts)


def check_registry_wiring(
    settings: Settings | None, *, providers: object | None = None
) -> CheckOutcome:
    """检查 10：注册表接线（J-1；设计 §13.3 防假绿 / R5A-01·R5A-02）。

    以**实际装配**为准（复用 ``build_providers``），断言注册表**非空** + **出口非占位**：

    - ``model_registry`` / ``tool_registry``：装配期应填充 → 为空即 ``fail``；
    - ``skill_registry`` / ``mcp_registry``：启动 / 发现期由组合根填充，**装配期可空**
      （🔴 local 社区模式无 Docker / dist 时为**正常态**，**不得**判 ``fail``）；
    - 任一注册表槽位若为 ``UnsupportedXxx`` 占位、或**恒空却自称** ``available`` → ``fail``。

    🔴 本项**只装配 + 检视结构**，不触发任何 Task 执行；详情**不含**任何凭证明文。
    仅 ``fail`` / ``skip`` 会偏离既有全 ``ok`` 基线；normal-local 下应为 ``ok``。

    Args:
        settings: 生效配置。
        providers: 可选**预装配**的 ``Providers``（由 :func:`commands.doctor._collect_checks`
            与 ``check_capabilities`` **共享同一次装配**；``None`` 时自行装配并释放）。

    Returns:
        ``("registry_wiring", status, detail)``。
    """
    if settings is None:
        return ("registry_wiring", "skip", "配置未加载，跳过")
    owned = providers is None
    if owned:
        providers, error = build_providers_for_checks(settings)
        if providers is None:
            return ("registry_wiring", "fail", error or "Provider 装配失败")

    try:
        problems, detail = evaluate_registry_wiring(providers)
    finally:
        if owned:
            dispose_providers(providers)

    if problems:
        return (
            "registry_wiring",
            "fail",
            f"注册表接线异常：{', '.join(problems)}；{detail}",
        )
    return ("registry_wiring", "ok", detail)
