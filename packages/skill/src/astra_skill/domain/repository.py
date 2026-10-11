"""``astra_skill`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.3 / W2 裁定 R6）。

- :class:`SkillRepository` / :class:`SkillVersionRepository` / :class:`SkillResourceRepository`：
  Skill 聚合仓储接口；
- :class:`AgentSkillRepository`：Skill↔AgentVersion 绑定仓储接口（**re-export 自
  ``astra_domain``**，与 ``AgentToolRepository`` 同层，避免 ``agent→skill`` 硬依赖）。

SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import AgentSkillRepository, Repository

from .entities import Skill, SkillResource, SkillVersion

__all__ = [
    "AgentSkillRepository",
    "SkillRepository",
    "SkillVersionRepository",
    "SkillResourceRepository",
]


@runtime_checkable
class SkillRepository(Repository[Skill], Protocol):
    """Skill 仓储接口（多租户隔离；``(tenant_id, name)`` 唯一）。"""

    def get_by_name(self, tenant_id: str, name: str) -> Skill | None:
        """按 ``(tenant_id, name)`` 获取 Skill，不存在返回 ``None``。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[Skill]:
        """列出某租户下的全部 Skill。"""
        ...


@runtime_checkable
class SkillVersionRepository(Repository[SkillVersion], Protocol):
    """SkillVersion 仓储接口（不可变版本快照；``(skill_id, version)`` 唯一）。"""

    def list_by_skill(self, skill_id: str) -> list[SkillVersion]:
        """列出某 Skill 的全部版本。"""
        ...

    def get_by_version(self, skill_id: str, version: str) -> SkillVersion | None:
        """按 ``(skill_id, version)`` 获取版本，不存在返回 ``None``。"""
        ...


@runtime_checkable
class SkillResourceRepository(Repository[SkillResource], Protocol):
    """SkillResource 仓储接口。"""

    def list_by_version(self, skill_version_id: str) -> list[SkillResource]:
        """列出某 SkillVersion 的全部资源。"""
        ...
