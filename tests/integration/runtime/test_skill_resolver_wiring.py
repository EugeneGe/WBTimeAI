"""Skill 解析组合根接线测试（W3 / T2-09.1；裁定 §19.2.5 ⑨）。

断言：组合根（``build_app_services``）经 ``build_skill_resolver`` + ``bindings_provider``
接入后，``AgentRuntime.build`` 的 runtime **实际注入** ``SkillResolver``（非 Null）——
补 F28「生产恒走 ``NullSkillResolver``」缺口。
"""

from __future__ import annotations

from typing import Any

from astra_skill import SkillResolver


def test_runtime_has_skill_resolver_injected(client: Any) -> None:
    """⑨ 生产组合根装配的 runtime **注入** ``SkillResolver``（非 ``None``）。"""
    runtime = client.app.state.services.runtime
    resolver = runtime.execution_manager._skill_resolver  # noqa: SLF001 - 装配接线断言
    assert resolver is not None, "组合根应注入 SkillResolver（补 F28）"
    assert isinstance(resolver, SkillResolver)
    assert resolver.has_bindings_provider is True


def test_skill_registry_available_for_resolution(client: Any) -> None:
    """⑨ 组合根注册表可解析（空目录时为空注册表，但对象非空且可调用）。"""
    services = client.app.state.services
    resolver = services.runtime.execution_manager._skill_resolver  # noqa: SLF001
    # 解析一个不存在的版本绑定不应抛错（宽松回落）。
    assert resolver.resolve(_query()) == []


def _query():  # noqa: ANN202
    """构造一个空查询（无绑定 / 无注册 Skill → 空结果）。"""
    from astra_domain import SkillQuery

    return SkillQuery(text="", agent_version_id="no-such-version")
