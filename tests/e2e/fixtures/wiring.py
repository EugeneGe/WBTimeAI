"""组合根替身注入辅助（W8 / T1-36）。

Phase 1 e2e 需要**真实 HTTP / TestClient / 路由 / SSE 编码**路径，同时用**确定性替身**
替换两个外部能力（模型 Provider、沙箱 Provider）。

本模块在 lifespan 装配完成后，**就地替换** ``app.state.services`` 中的运行时与沙箱句柄：

- 重建一个 ``AgentRuntime``，模型路由指向脚本化 Provider，工具执行走 Fake 沙箱；
  **不再注入静态放行校验器**——工具放行经**真实权限路径**（``POST /tools/permissions``）
  达成（W8 / A36 裁定 §5.3），由 Application 按 ``agent_id`` per-run 解析授权注入。
- 同步 ``services.runtime`` / ``services.agent_run.runtime`` / ``...sandbox_provider`` 与
  ``services.providers.sandbox``，使 Run 执行、SSE 流、取消回收都命中同一替身。

🔴 **不触碰** Router 注册、SSE 编码器、响应壳与事件总线——路由 / 帧格式仍为**真实实现**。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_model import ModelRegistry, ModelRouter
from astra_runtime import AgentRuntime

from .fake_sandbox import FakeSandboxProvider
from .stub_provider_script import ScriptedModelProvider

__all__ = [
    "InstalledDoubles",
    "install_scripted_runtime",
    "install_scripted_runtime_on_services",
    "seed_builtin_tool",
]


@dataclass
class InstalledDoubles:
    """一次注入后可供断言引用的替身句柄。"""

    provider_name: str
    model_name: str
    provider: ScriptedModelProvider
    sandbox: FakeSandboxProvider
    runtime: AgentRuntime

    @property
    def model_config(self) -> dict[str, Any]:
        """可直接写入 ``AgentVersion.model_config`` 的 provider/model 配置。"""
        return {"provider": self.provider_name, "model": self.model_name}


def install_scripted_runtime(
    client: Any,
    script: Sequence[str],
    *,
    sandbox: FakeSandboxProvider | None = None,
    provider_name: str = "scripted",
    model_name: str = "scripted-1",
) -> InstalledDoubles:
    """把脚本化 Provider + Fake 沙箱注入运行中的 app。

    Args:
        client: 已启动的 ``fastapi.testclient.TestClient``（lifespan 已完成装配）。
        script: 脚本化模型响应序列（见 :class:`ScriptedModelProvider`）。
        sandbox: 可选 Fake 沙箱（缺省新建）。
        provider_name: 注册进路由的 Provider 名（须与发布版本的 ``model_config.provider`` 一致）。
        model_name: 模型名。

    Returns:
        :class:`InstalledDoubles`（含替身句柄与可用 ``model_config``）。
    """
    return install_scripted_runtime_on_services(
        client.app.state.services,
        script,
        sandbox=sandbox,
        provider_name=provider_name,
        model_name=model_name,
    )


def install_scripted_runtime_on_services(
    services: Any,
    script: Sequence[str],
    *,
    sandbox: FakeSandboxProvider | None = None,
    provider_name: str = "scripted",
    model_name: str = "scripted-1",
) -> InstalledDoubles:
    """在已装配的 ``services``（``AppServices``）上就地注入确定性替身。

    与 :func:`install_scripted_runtime` 的唯一区别：直接接收 ``services`` 句柄而非
    ``TestClient``——供 NFR 性能基线（W8 / T1-38）在**真实 uvicorn 服务**（非 TestClient）
    上注入同一套替身。

    🔴 **不注入静态放行校验器**（W8 / A36）：工具放行经**真实权限路径**
    （``POST /tools/permissions`` → ``AgentRunService`` per-run 解析）达成。

    Args:
        services: 组合根产物 ``AppServices``（``app.state.services``）。
        script: 脚本化模型响应序列（见 :class:`ScriptedModelProvider`）。
        sandbox: 可选 Fake 沙箱（缺省新建）。
        provider_name: 注册进路由的 Provider 名（须与发布版本的 ``model_config.provider`` 一致）。
        model_name: 模型名。

    Returns:
        :class:`InstalledDoubles`（含替身句柄与可用 ``model_config``）。
    """
    session_factory = services.providers.database.session_factory

    provider = ScriptedModelProvider(script, model=model_name, name=provider_name)
    registry = ModelRegistry()
    registry.register(provider_name, provider)
    router = ModelRouter(registry)

    fake_sandbox = sandbox if sandbox is not None else FakeSandboxProvider()

    runtime = AgentRuntime.build(
        run_repository=SqlAgentRunRepository(session_factory),
        message_repository=SqlMessageRepository(session_factory),
        tool_call_repository=SqlToolCallRepository(session_factory),
        event_repository=SqlAgentEventRepository(session_factory),
        event_bus=services.providers.event_bus,
        model_router=router,
        tool_registry=services.tool,
        sandbox_provider=fake_sandbox,
    )

    # 就地替换组合根产物：Run 执行 / SSE / 取消回收统一命中替身。
    services.runtime = runtime
    services.agent_run.runtime = runtime
    services.agent_run.sandbox_provider = fake_sandbox
    services.providers.sandbox = fake_sandbox

    return InstalledDoubles(
        provider_name=provider_name,
        model_name=model_name,
        provider=provider,
        sandbox=fake_sandbox,
        runtime=runtime,
    )


def seed_builtin_tool(
    services: Any,
    *,
    name: str = "shell",
    display_name: str = "Shell",
    category: str = "system",
    requires_sandbox: bool = True,
) -> str:
    """把一条**内置工具**目录行落库，返回其**真实 ``tool.id``**（W8 / A36 裁定 §5.3）。

    内置工具仅注册在内存注册表（``build_tool_registry``），**未持久化** ``tool`` 表；而
    ``tool_permission.tool_id`` 为 **FK → ``tool.id``**。真实授权路径须先落一条 ``tool``
    行并以**真实 id** 作 ``tool_id``（勿以工具名 "shell" 直接作 ``tool_id``），方能保证
    **SQLite 与 Postgres 双引擎**下 FK 合法。``PermissionChecker._resolve_tool_names`` 会
    自动把该 id 归一到工具名（``shell``）。

    Args:
        services: 组合根产物 ``AppServices``（``app.state.services``）。
        name: 工具名（须与内存注册表中已注册工具同名，``tool_id→name`` 映射方能命中规则）。
        display_name: 展示名。
        category: 分类。
        requires_sandbox: 是否须经 Sandbox 执行。

    Returns:
        新落库的 ``tool.id``（真实主键）。
    """
    from astra_database import SqlToolRepository
    from astra_domain import Tool

    repository = SqlToolRepository(services.providers.database.session_factory)
    tool = repository.add(
        Tool(
            tenant_id=None,
            name=name,
            display_name=display_name,
            category=category,
            status="ACTIVE",
            requires_sandbox=requires_sandbox,
        )
    )
    return tool.id
