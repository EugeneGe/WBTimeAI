"""Skill 指令组装 golden 测试（W2 / T2-09 / Erratum-8 / R5）。

**验收口径**（T2-09）：

1. Runtime 组装上下文**含 Skill 指令**（``I-P2-02``）；
2. **不改 Runtime 接口签名**（只加实现，总纲 §12.1）；
3. AgentVersion 绑定变更可回滚；
4. 同一 Skill 多 Agent 复用可证。

本文件用真实 ``ExecutionManager``（经 ``AgentRuntime.build(skill_resolver=...)`` 装配），
在**模型 Provider 侧**录制实际投递的 messages，断言首条 system 消息 = Agent ``system_prompt``
为主 + Skill 指令按绑定顺序追加（冻结序列见 ``W2-开工前架构裁定.md`` §5.2）。
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from astra_core import DomainError, ErrorCode
from astra_domain import ResolvedSkill, SkillQuery
from astra_event import LocalEventBus
from astra_model import ChatResult, TokenCount
from astra_runtime import AgentRuntime, ContextManager, RunContext
from astra_skill import (
    LoadedSkill,
    SkillManifest,
    SkillRegistry,
    SkillResolver,
)
from astra_tool import ToolRegistry

from tests.unit.runtime_stubs import (
    StubModelProvider,
    build_model_router,
    build_session_factory,
    make_agent_version,
)

SKILL_MARKER = "SKILL-INSTRUCTIONS-MARKER"


class RecordingProvider(StubModelProvider):
    """录制每次 ``chat`` 收到的 messages（供断言 system 上下文）。"""

    def __init__(self, responses: Sequence[str], *, model: str = "stub-1") -> None:
        super().__init__(responses, model=model)
        self.seen: list[list[Any]] = []

    def chat(self, messages: Sequence[Any], **options: Any) -> ChatResult:
        """录制 messages 后返回脚本下一条。"""
        self.seen.append(list(messages))
        return super().chat(messages, **options)

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """零计数（不影响预算裁剪断言）。"""
        return TokenCount(count=0, model="stub-1")


def _loaded_skill(
    name: str,
    version: str,
    instructions: str,
    *,
    description: str = "",
    category: str = "",
) -> LoadedSkill:
    """构造一个内存 :class:`LoadedSkill`。"""
    manifest = SkillManifest(
        name=name,
        version=version,
        description=description,
        category=category,
    )
    return LoadedSkill(manifest=manifest, instructions=instructions, source="builtin")


def _registry(*skills: LoadedSkill) -> SkillRegistry:
    """把若干 Skill 注册进一个 :class:`SkillRegistry`。"""
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill.name, skill.version, skill)
    return registry


def _build(
    factory,  # noqa: ANN001
    *,
    responses: Sequence[str],
    skill_resolver: Any = None,
    mcp_executor: Any = None,
) -> tuple[AgentRuntime, RecordingProvider]:
    """装配一个注入了 ``skill_resolver`` / ``mcp_executor`` 的 ``AgentRuntime``。"""
    provider = RecordingProvider(responses)
    runtime = AgentRuntime.build(
        run_repository=SqlAgentRunRepository(factory),
        message_repository=SqlMessageRepository(factory),
        tool_call_repository=SqlToolCallRepository(factory),
        event_bus=LocalEventBus(),
        model_router=build_model_router(provider),
        tool_registry=ToolRegistry(),
        event_repository=SqlAgentEventRepository(factory),
        skill_resolver=skill_resolver,
        mcp_executor=mcp_executor,
    )
    return runtime, provider


def _run(runtime: AgentRuntime, version, *, message: str):  # noqa: ANN001, ANN202
    """执行一次 Run（返回结果）。"""
    return runtime.run(
        RunContext(
            conversation_id="conv-skill-1",
            agent_id="agent-1",
            agent_version=version,
            tenant_id="tenant-1",
            user_message=message,
        )
    )


def _system_content(provider: RecordingProvider) -> str:
    """取模型首次收到的首条 system 消息内容。"""
    assert provider.seen, "模型未被调用（无录制 messages）"
    first = provider.seen[0][0]
    assert first.role == "system"
    return first.content


# -- ① Runtime 组装上下文含 Skill 指令（golden） -------------------------------


def test_skill_instructions_reach_system_context(tmp_path: Path) -> None:
    """golden：命中的 Skill 指令**必须**出现在投递给模型的 system 消息中。"""
    factory, engine = build_session_factory(tmp_path / "skill_ctx.db")
    try:
        skill = _loaded_skill(
            "pdf-expert",
            "1.0.0",
            instructions=SKILL_MARKER,
            description="pdf workflows",
        )
        resolver = SkillResolver(registry=_registry(skill))
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        result = _run(runtime, version, message="pdf")
        assert result.success is True

        system_content = _system_content(provider)
        assert "AGENT-PROMPT" in system_content
        assert SKILL_MARKER in system_content
        # 默认合成：Agent ``system_prompt`` 为主 + Skill 指令**追加**于后（separator="\n\n"）。
        assert system_content == f"AGENT-PROMPT\n\n{SKILL_MARKER}"
    finally:
        engine.dispose()


def test_no_skill_resolver_keeps_phase1_behavior(tmp_path: Path) -> None:
    """未注入 ``skill_resolver`` → system 消息 = Agent ``system_prompt``（向后兼容）。"""
    factory, engine = build_session_factory(tmp_path / "skill_off.db")
    try:
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=None)

        result = _run(runtime, version, message="pdf")
        assert result.success is True
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()


def test_no_match_falls_back_to_agent_prompt(tmp_path: Path) -> None:
    """无命中 Skill → 原样返回 Agent ``system_prompt``。"""
    factory, engine = build_session_factory(tmp_path / "skill_nomatch.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", instructions=SKILL_MARKER)
        resolver = SkillResolver(registry=_registry(skill))
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        result = _run(runtime, version, message="完全无关的输入")
        assert result.success is True
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()


# -- 合成策略数据驱动（PromptMergeConfig） ------------------------------------


def test_skill_order_before(tmp_path: Path) -> None:
    """``runtime_config.prompt.skill_order="before"`` → Skill 指令**前置**。"""
    factory, engine = build_session_factory(tmp_path / "skill_before.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", instructions=SKILL_MARKER, description="pdf")
        resolver = SkillResolver(registry=_registry(skill))
        version = make_agent_version(
            system_prompt="AGENT-PROMPT",
            runtime_overrides={"prompt": {"skill_order": "before"}},
        )
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        _run(runtime, version, message="pdf")
        assert _system_content(provider) == f"{SKILL_MARKER}\n\nAGENT-PROMPT"
    finally:
        engine.dispose()


def test_custom_separator(tmp_path: Path) -> None:
    """``runtime_config.prompt.skill_separator`` 生效。"""
    factory, engine = build_session_factory(tmp_path / "skill_sep.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", instructions=SKILL_MARKER, description="pdf")
        resolver = SkillResolver(registry=_registry(skill))
        version = make_agent_version(
            system_prompt="AGENT-PROMPT",
            runtime_overrides={"prompt": {"skill_separator": " || "}},
        )
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        _run(runtime, version, message="pdf")
        assert _system_content(provider) == f"AGENT-PROMPT || {SKILL_MARKER}"
    finally:
        engine.dispose()


def test_multi_skill_binding_order_preserved(tmp_path: Path) -> None:
    """多 Skill 命中 → 指令按解析顺序（``name`` 升序）依次追加。"""
    factory, engine = build_session_factory(tmp_path / "skill_multi.db")
    try:
        first = _loaded_skill("pdf-a", "1.0.0", instructions="SKILL-A", description="pdf doc")
        second = _loaded_skill("pdf-b", "1.0.0", instructions="SKILL-B", description="pdf doc")
        resolver = SkillResolver(registry=_registry(second, first))
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        _run(runtime, version, message="pdf")
        assert _system_content(provider) == "AGENT-PROMPT\n\nSKILL-A\n\nSKILL-B"
    finally:
        engine.dispose()


# -- ③ / ④ 可回滚 + 多 Agent 复用 --------------------------------------------


def test_same_skill_reused_across_agents(tmp_path: Path) -> None:
    """④ 同一 Skill（同一注册表）可被多个 Agent 复用（各自运行时均可见指令）。"""
    factory, engine = build_session_factory(tmp_path / "skill_reuse.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", instructions=SKILL_MARKER, description="pdf")
        resolver = SkillResolver(registry=_registry(skill))

        version_a = make_agent_version(system_prompt="AGENT-A")
        version_b = make_agent_version(system_prompt="AGENT-B")
        runtime_a, provider_a = _build(factory, responses=["a"], skill_resolver=resolver)
        runtime_b, provider_b = _build(factory, responses=["b"], skill_resolver=resolver)

        _run(runtime_a, version_a, message="pdf")
        _run(runtime_b, version_b, message="pdf")

        assert _system_content(provider_a) == f"AGENT-A\n\n{SKILL_MARKER}"
        assert _system_content(provider_b) == f"AGENT-B\n\n{SKILL_MARKER}"
    finally:
        engine.dispose()


def test_agent_without_bound_skill_unchanged(tmp_path: Path) -> None:
    """③ 绑定可回滚：Agent 不命中 Skill 时行为与 Phase 1 一致（不受其他 Agent 影响）。"""
    factory, engine = build_session_factory(tmp_path / "skill_rollback.db")
    try:
        resolver = SkillResolver(registry=_registry())
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        _run(runtime, version, message="pdf")
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()


# -- ② 不改 Runtime 接口签名 --------------------------------------------------


def test_context_manager_build_signature_unchanged() -> None:
    """② ``ContextManager.build(*, system_prompt, history)`` 签名（含参数名与默认值）不变。"""
    params = inspect.signature(ContextManager.build).parameters
    assert list(params) == ["self", "system_prompt", "history"]
    assert params["system_prompt"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["history"].kind is inspect.Parameter.KEYWORD_ONLY
    for name in ("system_prompt", "history"):
        assert params[name].default is inspect.Parameter.empty


def test_agent_runtime_build_accepts_optional_skill_params() -> None:
    """② ``AgentRuntime.build`` **仅新增可选关键字形参**（向后兼容，不破坏既有调用）。"""
    params = inspect.signature(AgentRuntime.build).parameters
    for name in ("skill_resolver", "mcp_executor"):
        assert name in params
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is None


def test_mcp_executor_injection_is_optional(tmp_path: Path) -> None:
    """② 注入可选 ``mcp_executor`` 不改变 Skill 组装行为（本波次仅接线占位）。"""
    factory, engine = build_session_factory(tmp_path / "mcp_placeholder.db")
    try:
        skill = _loaded_skill("pdf-expert", "1.0.0", instructions=SKILL_MARKER, description="pdf")
        resolver = SkillResolver(registry=_registry(skill))
        version = make_agent_version(system_prompt="AGENT-PROMPT")

        class _StubMCPExecutor:
            """占位 MCP 执行器（本波次不产出具名行为）。"""

            def call(self, request: object) -> object:  # noqa: ANN401
                raise AssertionError("T2-09 不应触发 MCP 调用")

        runtime, provider = _build(
            factory,
            responses=["done"],
            skill_resolver=resolver,
            mcp_executor=_StubMCPExecutor(),
        )
        result = _run(runtime, version, message="pdf")
        assert result.success is True
        assert _system_content(provider) == f"AGENT-PROMPT\n\n{SKILL_MARKER}"
    finally:
        engine.dispose()


# -- 安全降级：解析器异常不中断 Run -------------------------------------------


def test_resolver_error_degrades_gracefully(tmp_path: Path) -> None:
    """解析器抛 ``DomainError`` → 回退为空技能集，Run 仍成功（不因 Skill 故障中断）。"""

    class _BrokenResolver:
        def resolve(self, query: SkillQuery) -> list[ResolvedSkill]:
            raise DomainError("skill backend down", code=ErrorCode.INTERNAL_ERROR)

    factory, engine = build_session_factory(tmp_path / "skill_broken.db")
    try:
        version = make_agent_version(system_prompt="AGENT-PROMPT")
        runtime, provider = _build(factory, responses=["done"], skill_resolver=_BrokenResolver())

        result = _run(runtime, version, message="pdf")
        assert result.success is True
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()


# -- W3 / T2-09.1：绑定驱动（闭合 QA-W2 Observation-1） ------------------------


def test_bound_skill_injected_for_multiword_input(tmp_path: Path) -> None:
    """⑦ 绑定驱动：真 ``ExecutionManager`` + 多词输入 → **绑定** Skill 内容进 system。

    闭合 QA-W2 Observation-1：真实多词输入 ``"please use the pdf skill"`` 亦触发命中
    （经 ``bindings_provider`` 门 + 分词 / 整词匹配）。
    """
    factory, engine = build_session_factory(tmp_path / "skill_bound.db")
    try:
        bound = _loaded_skill(
            "pdf-expert", "1.0.0", instructions=SKILL_MARKER, description="pdf workflows"
        )
        unbound = _loaded_skill(
            "email-expert", "1.0.0", instructions="EMAIL-MARKER", description="email workflows"
        )
        registry = _registry(bound, unbound)
        version = make_agent_version(system_prompt="AGENT-PROMPT")

        def _provider(agent_version_id: str):  # noqa: ANN202
            return [bound] if agent_version_id == version.id else []

        resolver = SkillResolver(registry=registry, bindings_provider=_provider)
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        result = _run(runtime, version, message="please use the pdf skill")
        assert result.success is True

        system_content = _system_content(provider)
        assert "AGENT-PROMPT" in system_content
        assert SKILL_MARKER in system_content
        assert "EMAIL-MARKER" not in system_content  # 未绑定 → 不注入
    finally:
        engine.dispose()


def test_unbound_registered_skill_not_injected(tmp_path: Path) -> None:
    """⑧ 未绑定但已注册的 Skill **不注入**（绑定门生效；即便输入命中其 token）。"""
    factory, engine = build_session_factory(tmp_path / "skill_unbound.db")
    try:
        unbound = _loaded_skill(
            "email-expert", "1.0.0", instructions="EMAIL-MARKER", description="email workflows"
        )
        registry = _registry(unbound)
        version = make_agent_version(system_prompt="AGENT-PROMPT")

        def _provider(agent_version_id: str):  # noqa: ANN202, ARG001
            return []  # 该版本无绑定

        resolver = SkillResolver(registry=registry, bindings_provider=_provider)
        runtime, provider = _build(factory, responses=["done"], skill_resolver=resolver)

        result = _run(runtime, version, message="email please")
        assert result.success is True
        assert _system_content(provider) == "AGENT-PROMPT"
    finally:
        engine.dispose()
