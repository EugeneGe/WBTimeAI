"""``SkillRegistry`` 单测（W2 / T2-08）。

覆盖：来源优先级 ``workspace > plugin > builtin``；同源同名版本高者胜；
``override=False`` → ``CONFLICT``；后注册覆盖。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_skill import LoadedSkill, SkillManifest, SkillRegistry, SkillSource


def _loaded(name: str, version: str, *, description: str = "") -> LoadedSkill:
    """构造一个测试用 LoadedSkill。"""
    return LoadedSkill(
        manifest=SkillManifest(name=name, version=version, description=description),
        instructions=f"{name}@{version} 指令",
        source="builtin",
    )


def test_source_priority_workspace_wins() -> None:
    """``workspace > plugin > builtin``：同名取 workspace。"""
    registry = SkillRegistry()
    registry.register("demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.BUILTIN)
    registry.register("demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.PLUGIN)
    registry.register("demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.WORKSPACE)
    resolved = registry.resolve("demo")
    assert resolved is not None
    assert resolved.source == "builtin"  # LoadedSkill.source 字段本身不参与判定
    entry = registry.resolve_entry("demo")
    assert entry is not None
    assert entry.source is SkillSource.WORKSPACE


def test_plugin_beats_builtin() -> None:
    """plugin 覆盖 builtin（workpace 缺席时 plugin 生效）。"""
    registry = SkillRegistry()
    registry.register("demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.BUILTIN)
    registry.register("demo", "2.0.0", _loaded("demo", "2.0.0"), source=SkillSource.PLUGIN)
    entry = registry.resolve_entry("demo")
    assert entry is not None
    assert entry.source is SkillSource.PLUGIN


def test_same_source_higher_version_wins() -> None:
    """同来源同名：语义化版本高者优先。"""
    registry = SkillRegistry()
    registry.register("demo", "1.2.0", _loaded("demo", "1.2.0"), source=SkillSource.BUILTIN)
    registry.register("demo", "1.10.0", _loaded("demo", "1.10.0"), source=SkillSource.BUILTIN)
    entry = registry.resolve_entry("demo")
    assert entry is not None
    assert entry.version == "1.10.0"


def test_same_source_same_version_last_registration_wins() -> None:
    """同来源同名同版本：后注册覆盖（``override=True`` 默认）。"""
    registry = SkillRegistry()
    registry.register(
        "demo", "1.0.0", _loaded("demo", "1.0.0", description="first"), source=SkillSource.BUILTIN
    )
    registry.register(
        "demo", "1.0.0", _loaded("demo", "1.0.0", description="second"), source=SkillSource.BUILTIN
    )
    resolved = registry.resolve("demo")
    assert resolved is not None
    assert resolved.manifest.description == "second"


def test_override_false_raises_conflict() -> None:
    """``override=False`` 且同来源同名同版本 → ``CONFLICT``。"""
    registry = SkillRegistry()
    registry.register("demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.BUILTIN)
    with pytest.raises(DomainError) as excinfo:
        registry.register(
            "demo", "1.0.0", _loaded("demo", "1.0.0"), source=SkillSource.BUILTIN, override=False
        )
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_resolve_missing_returns_none() -> None:
    """无匹配返回 ``None``。"""
    registry = SkillRegistry()
    assert registry.resolve("nope") is None


def test_names_and_versions() -> None:
    """``names`` / ``versions`` 稳定排序。"""
    registry = SkillRegistry()
    registry.register("b", "1.0.0", _loaded("b", "1.0.0"), source=SkillSource.BUILTIN)
    registry.register("a", "2.0.0", _loaded("a", "2.0.0"), source=SkillSource.BUILTIN)
    registry.register("a", "1.0.0", _loaded("a", "1.0.0"), source=SkillSource.BUILTIN)
    assert registry.names() == ["a", "b"]
    assert registry.versions("a") == ["1.0.0", "2.0.0"]
