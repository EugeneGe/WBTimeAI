"""``astra_skill`` 领域子模块（实体 / 仓储接口；W2 / T2-07）。

本子模块**零 Web / ORM**（受 ``test_layering.py::test_phase2_domain_submodules_have_no_orm_or_web``
覆盖）。
"""

from __future__ import annotations

from .entities import (
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
    Skill,
    SkillResource,
    SkillStatus,
    SkillVersion,
    SkillVersionStatus,
)
from .repository import (
    AgentSkillRepository,
    SkillRepository,
    SkillResourceRepository,
    SkillVersionRepository,
)

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
    # 实体
    "Skill",
    "SkillVersion",
    "SkillResource",
    # 仓储接口
    "SkillRepository",
    "SkillVersionRepository",
    "SkillResourceRepository",
    "AgentSkillRepository",
]
