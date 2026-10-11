"""``astra_skill`` 组合工厂（``build_skill_registry``；W2 裁定 R14）。

- :func:`build_skill_registry`：**config 入口**（``astra_config.providers._build_optional``
  调用），按 ``settings.skill`` 的目录配置装载 **builtin / plugin / workspace** 三类来源；
  目录缺失 / 无 ``skill.yaml`` 时**宽松跳过**（不抛错）；
- :func:`build_skill_resolver`：由已装配的注册表构造 RP-01 解析器（供**组合根**使用，
  不在 ``build_providers`` 内）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .loader import SkillLoader
from .manifest import LoadedSkill
from .registry import SkillRegistry, SkillSource
from .resolver import SkillResolver

__all__ = ["build_skill_registry", "build_skill_resolver"]


def _dirs(settings: Any, name: str) -> list[str]:
    """从 ``settings.skill`` 取目录列表（缺失 / 非配置时返回空）。"""
    skill_settings = getattr(settings, "skill", None)
    raw = getattr(skill_settings, name, None) if skill_settings is not None else None
    return [str(item) for item in (raw or [])]


def build_skill_registry(settings: Any) -> SkillRegistry:
    """按 ``settings.skill`` 装配并填充 :class:`SkillRegistry`（config 入口）。

    装载顺序：``builtin`` → ``plugin`` → ``workspace``（**优先级由注册表按来源判定**，
    与装载顺序无关）。

    Args:
        settings: 生效配置（``settings.skill`` 提供目录）。

    Returns:
        已装载全部来源目录的注册表（目录缺失时为**空**注册表）。
    """
    registry = SkillRegistry()
    loader = SkillLoader()
    plan: tuple[tuple[SkillSource, str], ...] = (
        (SkillSource.BUILTIN, "builtin_dirs"),
        (SkillSource.PLUGIN, "plugin_dirs"),
        (SkillSource.WORKSPACE, "workspace_dirs"),
    )
    for source, field in plan:
        for raw_dir in _dirs(settings, field):
            base = Path(raw_dir).expanduser()
            for loaded in loader.load_dir(base, source=source):
                registry.register(
                    loaded.manifest.name, loaded.manifest.version, loaded, source=source
                )
    return registry


def build_skill_resolver(
    registry: SkillRegistry,
    *,
    max_skills: int = 5,
    bindings_provider: Callable[[str], list[LoadedSkill]] | None = None,
) -> SkillResolver:
    """由已装配注册表构造 RP-01 :class:`SkillResolver`（供组合根注入 runtime）。

    W3 裁定 §19.2.3（T2-09.1）**加性**扩展：``bindings_provider`` 由**组合根**提供
    （``(agent_version_id) -> list[LoadedSkill]``，返回该版本已启用绑定的生效 ``LoadedSkill``）；
    缺省 ``None`` = 注册表全量（向后兼容）。
    """
    return SkillResolver(
        registry=registry,
        max_skills=max_skills,
        bindings_provider=bindings_provider,
    )
