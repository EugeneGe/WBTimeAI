"""``SkillResolver`` 绑定驱动 + 分词 / 整词匹配单测（W3 / T2-09.1；裁定 §19.2.5）。

覆盖：

- ① 绑定驱动：版本绑定 ``{A,B}`` 时 ``resolve`` **只**返回 A/B（注册表内未绑定的 C 不返回）；
- ② ``enabled=False`` 绑定被排除（经**真实** ``build_skill_bindings_provider``）；
- ③ 分词：多词输入命中（``"please use the pdf skill"`` → ``pdf-expert``）；
- ④ 整词：``"pdfx"`` **不**命中 ``pdf``；
- ⑤ ``agent_version_id=None`` 或未注入 provider → 回落注册表全量（向后兼容）；
- ⑥ 空 ``text`` + 绑定 → 返回全部绑定候选。
"""

from __future__ import annotations

from astra_api.dependencies.services import build_skill_bindings_provider
from astra_domain import AgentSkill, SkillQuery
from astra_skill import LoadedSkill, Skill, SkillManifest, SkillRegistry, SkillResolver

# -- 构造辅助 ---------------------------------------------------------------


def _loaded(
    name: str,
    version: str = "1.0.0",
    *,
    instructions: str = "",
    description: str = "",
    category: str = "",
) -> LoadedSkill:
    """构造内存 :class:`LoadedSkill`。"""
    return LoadedSkill(
        manifest=SkillManifest(
            name=name, version=version, description=description, category=category
        ),
        instructions=instructions or f"INST:{name}",
        source="builtin",
    )


def _registry(*skills: LoadedSkill) -> SkillRegistry:
    """把若干 Skill 注册进一个 :class:`SkillRegistry`。"""
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill.name, skill.version, skill)
    return registry


class _FakeSkillRepository:
    """伪 Skill 仓储（``skill_id`` → 领域 ``Skill``）。"""

    def __init__(self, by_id: dict[str, Skill]) -> None:
        self._by_id = by_id

    def get(self, skill_id: str) -> Skill | None:  # noqa: D102 - 伪实现
        return self._by_id.get(skill_id)


class _FakeAgentSkillRepository:
    """伪 ``agent_skill`` 绑定仓储（``agent_version_id`` → 绑定列表）。"""

    def __init__(self, by_version: dict[str, list[AgentSkill]]) -> None:
        self._by_version = by_version

    def list_by_agent_version(self, agent_version_id: str) -> list[AgentSkill]:  # noqa: D102
        return list(self._by_version.get(agent_version_id, []))


def _make_provider(bindings: dict[str, list[AgentSkill]], skills: dict[str, Skill], registry):
    """用**真实** ``build_skill_bindings_provider`` 组装绑定回调。"""
    return build_skill_bindings_provider(
        skill_repository=_FakeSkillRepository(skills),
        agent_skill_repository=_FakeAgentSkillRepository(bindings),
        skill_registry=registry,
    )


# -- ① 绑定驱动（版本绑定 {A,B} → 只返回 A/B） -------------------------------


def test_resolve_only_returns_bound_skills() -> None:
    """① 版本绑定 ``{A,B}`` 时只返回 A/B；注册表内未绑定的 C **不**返回。"""
    skills = {
        "sA": Skill(id="sA", name="alpha"),
        "sB": Skill(id="sB", name="beta"),
    }
    bindings = {
        "v1": [
            AgentSkill(agent_version_id="v1", skill_id="sA"),
            AgentSkill(agent_version_id="v1", skill_id="sB"),
        ]
    }
    registry = _registry(_loaded("alpha"), _loaded("beta"), _loaded("gamma"))
    provider = _make_provider(bindings, skills, registry)
    resolver = SkillResolver(registry=registry, bindings_provider=provider)

    resolved = resolver.resolve(SkillQuery(text="", agent_version_id="v1"))

    assert [item.name for item in resolved] == ["alpha", "beta"]
    assert "gamma" not in {item.name for item in resolved}


# -- ② enabled=False 绑定被排除 ------------------------------------------------


def test_disabled_binding_excluded() -> None:
    """② ``enabled=False`` 的绑定被 ``bindings_provider`` 排除。"""
    skills = {
        "sA": Skill(id="sA", name="alpha"),
        "sB": Skill(id="sB", name="beta"),
    }
    bindings = {
        "v1": [
            AgentSkill(agent_version_id="v1", skill_id="sA", enabled=True),
            AgentSkill(agent_version_id="v1", skill_id="sB", enabled=False),
        ]
    }
    registry = _registry(_loaded("alpha"), _loaded("beta"))
    provider = _make_provider(bindings, skills, registry)
    resolver = SkillResolver(registry=registry, bindings_provider=provider)

    resolved = resolver.resolve(SkillQuery(text="", agent_version_id="v1"))

    assert [item.name for item in resolved] == ["alpha"]


# -- ③ 分词：多词输入命中 -----------------------------------------------------


def test_multiword_input_matches_skill() -> None:
    """③ 多词输入按 token 命中（真实对话输入可触发）。"""
    skill = _loaded("pdf-expert", description="pdf workflows")
    resolver = SkillResolver(registry=_registry(skill))

    for text in ("please use the pdf skill", "help me with a pdf"):
        resolved = resolver.resolve(SkillQuery(text=text))
        assert [item.name for item in resolved] == ["pdf-expert"], text


# -- ④ 整词：pdfx 不命中 pdf --------------------------------------------------


def test_whole_word_does_not_match_substring() -> None:
    """④ 整词判定：``pdfx`` **不**命中 ``pdf-expert``；``pdf`` 命中（防误命中）。"""
    skill = _loaded("pdf-expert", description="pdf workflows")
    resolver = SkillResolver(registry=_registry(skill))

    assert [item.name for item in resolver.resolve(SkillQuery(text="pdf"))] == ["pdf-expert"]
    assert resolver.resolve(SkillQuery(text="pdfx")) == []


def test_pdfx_not_matching_plain_name() -> None:
    """④ 显式：名为 ``pdf`` 的 Skill 不被 ``pdfx`` 命中。"""
    skill = _loaded("pdf", description="pdf")
    resolver = SkillResolver(registry=_registry(skill))

    assert resolver.resolve(SkillQuery(text="pdfx")) == []
    assert [item.name for item in resolver.resolve(SkillQuery(text="pdf"))] == ["pdf"]


# -- ⑤ 回落注册表全量（向后兼容） --------------------------------------------


def test_fallback_to_registry_when_no_agent_version() -> None:
    """⑤ ``agent_version_id=None`` → 回落注册表全量（未绑定的 C 亦可见）。"""
    skills = {"sA": Skill(id="sA", name="alpha")}
    bindings = {"v1": [AgentSkill(agent_version_id="v1", skill_id="sA")]}
    registry = _registry(_loaded("alpha"), _loaded("gamma"))
    provider = _make_provider(bindings, skills, registry)
    resolver = SkillResolver(registry=registry, bindings_provider=provider)

    resolved = resolver.resolve(SkillQuery(text="", agent_version_id=None))

    assert {item.name for item in resolved} == {"alpha", "gamma"}


def test_fallback_when_provider_not_injected() -> None:
    """⑤ 未注入 ``bindings_provider`` → 即便传入 ``agent_version_id`` 亦回落注册表全量。"""
    registry = _registry(_loaded("alpha"), _loaded("gamma"))
    resolver = SkillResolver(registry=registry, bindings_provider=None)

    resolved = resolver.resolve(SkillQuery(text="", agent_version_id="v1"))

    assert {item.name for item in resolved} == {"alpha", "gamma"}


# -- ⑥ 空 text + 绑定 → 全部绑定候选 -----------------------------------------


def test_empty_text_returns_all_bound_candidates() -> None:
    """⑥ 空 ``text`` + 绑定 → 返回全部绑定候选。"""
    skills = {
        "sA": Skill(id="sA", name="alpha"),
        "sB": Skill(id="sB", name="beta"),
    }
    bindings = {
        "v1": [
            AgentSkill(agent_version_id="v1", skill_id="sA"),
            AgentSkill(agent_version_id="v1", skill_id="sB"),
        ]
    }
    registry = _registry(_loaded("alpha"), _loaded("beta"), _loaded("gamma"))
    provider = _make_provider(bindings, skills, registry)
    resolver = SkillResolver(registry=registry, bindings_provider=provider)

    resolved = resolver.resolve(SkillQuery(text="", agent_version_id="v1"))

    assert {item.name for item in resolved} == {"alpha", "beta"}
