"""Astra AI Skill 能力包（``astra_skill``；设计 §2.3）。

- 领域实体 / 仓储接口：``astra_skill.domain``（``Skill`` / ``SkillVersion`` /
  ``SkillResource``；Skill 绑定实体 ``AgentSkill`` 落 ``astra_domain``）；
- SQL 仓储：``astra_skill.repositories``（能力包 ORM 落点）；
- ``Loader`` / ``Registry`` / ``Resolver`` / ``manifest`` / 工厂归 **T2-08**。

包性质：能力包（仅禁 Web；SQL 仓储留本包 ``repositories/``）——W2 裁定 R1/R2。
"""

from __future__ import annotations

from .domain import (
    SKILL_RESOURCE_KIND_EXAMPLE,
    SKILL_RESOURCE_KIND_FILE,
    SKILL_RESOURCE_KIND_SCRIPT,
    SKILL_RESOURCE_KIND_TEMPLATE,
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_ARCHIVED,
    SKILL_STATUS_DRAFT,
    SKILL_VERSION_STATUS_DEPRECATED,
    SKILL_VERSION_STATUS_DRAFT,
    SKILL_VERSION_STATUS_PUBLISHED,
    AgentSkillRepository,
    Skill,
    SkillRepository,
    SkillResource,
    SkillResourceRepository,
    SkillStatus,
    SkillVersion,
    SkillVersionRepository,
    SkillVersionStatus,
)
from .factory import build_skill_registry, build_skill_resolver
from .loader import SkillLoader
from .manifest import (
    DEFAULT_EXAMPLES_DIR,
    DEFAULT_INSTRUCTIONS_FILE,
    DEFAULT_RESOURCES_DIR,
    DEFAULT_SCRIPTS_DIR,
    LoadedSkill,
    SkillManifest,
    SkillResourceSpec,
    load_skill_package,
    parse_manifest,
)
from .registry import SkillRegistry, SkillSource
from .repositories import (
    SqlAgentSkillRepository,
    SqlSkillRepository,
    SqlSkillResourceRepository,
    SqlSkillVersionRepository,
)
from .resolver import SkillResolver

__all__ = [
    # 常量
    "SKILL_STATUS_DRAFT",
    "SKILL_STATUS_ACTIVE",
    "SKILL_STATUS_ARCHIVED",
    "SKILL_VERSION_STATUS_DRAFT",
    "SKILL_VERSION_STATUS_PUBLISHED",
    "SKILL_VERSION_STATUS_DEPRECATED",
    "SKILL_RESOURCE_KIND_FILE",
    "SKILL_RESOURCE_KIND_EXAMPLE",
    "SKILL_RESOURCE_KIND_SCRIPT",
    "SKILL_RESOURCE_KIND_TEMPLATE",
    # 枚举
    "SkillStatus",
    "SkillVersionStatus",
    "SkillSource",
    # 实体
    "Skill",
    "SkillVersion",
    "SkillResource",
    # 仓储接口
    "SkillRepository",
    "SkillVersionRepository",
    "SkillResourceRepository",
    "AgentSkillRepository",
    # SQL 仓储
    "SqlSkillRepository",
    "SqlSkillVersionRepository",
    "SqlSkillResourceRepository",
    "SqlAgentSkillRepository",
    # manifest / loader / registry / resolver
    "DEFAULT_INSTRUCTIONS_FILE",
    "DEFAULT_RESOURCES_DIR",
    "DEFAULT_EXAMPLES_DIR",
    "DEFAULT_SCRIPTS_DIR",
    "SkillManifest",
    "SkillResourceSpec",
    "LoadedSkill",
    "parse_manifest",
    "load_skill_package",
    "SkillLoader",
    "SkillRegistry",
    "SkillResolver",
    # 装配
    "build_skill_registry",
    "build_skill_resolver",
]
