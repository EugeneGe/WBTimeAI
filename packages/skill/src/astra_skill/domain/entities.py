"""``astra_skill`` 领域实体（设计 §2.3；W2 裁定 R4）。

- :class:`Skill`：Skill **身份与生命周期**（聚合根；Skill ≠ Agent：提供「知识与指令
  + 资源」，**不直接执行动作**）；
- :class:`SkillVersion`：**不可变**版本快照（发布即冻结；``instructions`` / ``manifest``
  构造后不可变，状态机 ``DRAFT → PUBLISHED → DEPRECATED`` 单向）——``frozen=True``
  dataclass（W2 裁定 R4 §4.1）；
- :class:`SkillResource`：版本内资源（``file`` / ``example`` / ``script`` / ``template``），
  ``storage_key`` 对接 Phase 0 ``astra_storage.base.Storage``（键约定
  ``skills/{skill_id}/{version}/{path}``，裁定 R4 §4.2）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode, generate_id
from astra_domain import AggregateRoot

__all__ = [
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
    "SkillStatus",
    "SkillVersionStatus",
    "Skill",
    "SkillVersion",
    "SkillResource",
]

# -- 常量（复用 ASTRA 风格字面值） ------------------------------------------

#: Skill 生命周期状态。
SKILL_STATUS_DRAFT = "DRAFT"
SKILL_STATUS_ACTIVE = "ACTIVE"
SKILL_STATUS_ARCHIVED = "ARCHIVED"

#: SkillVersion 状态。
SKILL_VERSION_STATUS_DRAFT = "DRAFT"
SKILL_VERSION_STATUS_PUBLISHED = "PUBLISHED"
SKILL_VERSION_STATUS_DEPRECATED = "DEPRECATED"

#: SkillResource 种类。
SKILL_RESOURCE_KIND_FILE = "file"
SKILL_RESOURCE_KIND_EXAMPLE = "example"
SKILL_RESOURCE_KIND_SCRIPT = "script"
SKILL_RESOURCE_KIND_TEMPLATE = "template"


class SkillStatus(StrEnum):
    """Skill 生命周期状态（设计 §2.3）。"""

    DRAFT = SKILL_STATUS_DRAFT
    ACTIVE = SKILL_STATUS_ACTIVE
    ARCHIVED = SKILL_STATUS_ARCHIVED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class SkillVersionStatus(StrEnum):
    """SkillVersion 状态（单向：``DRAFT → PUBLISHED → DEPRECATED``）。"""

    DRAFT = SKILL_VERSION_STATUS_DRAFT
    PUBLISHED = SKILL_VERSION_STATUS_PUBLISHED
    DEPRECATED = SKILL_VERSION_STATUS_DEPRECATED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


#: 允许的状态迁移（单向）。
_ALLOWED_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    SKILL_VERSION_STATUS_DRAFT: (
        SKILL_VERSION_STATUS_PUBLISHED,
        SKILL_VERSION_STATUS_DEPRECATED,
    ),
    SKILL_VERSION_STATUS_PUBLISHED: (SKILL_VERSION_STATUS_DEPRECATED,),
    SKILL_VERSION_STATUS_DEPRECATED: (),
}


@dataclass
class Skill(AggregateRoot):
    """Skill 聚合根（数据驱动的「知识与指令 + 资源」单元）。

    Attributes:
        name: 唯一键（租户内唯一；``^[a-z0-9][a-z0-9._-]{1,63}$``）。
        display_name: 展示名（缺省 = ``name``）。
        description: 描述。
        category: 分类。
        status: 生命周期状态（``SkillStatus`` 字面值）。
        current_version_id: 当前生效版本标识（可空）。
        created_by: 创建者用户标识。
    """

    name: str = ""
    display_name: str = ""
    description: str | None = None
    category: str = ""
    status: str = SKILL_STATUS_DRAFT
    current_version_id: str | None = None
    created_by: str = ""


@dataclass(frozen=True)
class SkillVersion:
    """SkillVersion（**不可变**版本快照；发布即冻结）。

    🔴 ``frozen=True``：``instructions`` / ``manifest`` 构造后**不可变**。需变更时经
       :meth:`with_instructions`（仅 ``DRAFT`` 允许）或 :meth:`with_status`（单向迁移）
       产生**新实例**（``dataclasses.replace``）。
    """

    id: str = field(default_factory=generate_id)
    skill_id: str = ""
    version: str = ""
    instructions: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)
    status: str = SKILL_VERSION_STATUS_DRAFT
    created_by: str = ""
    created_at: datetime = field(default_factory=utcnow)

    @property
    def is_published(self) -> bool:
        """是否已发布（发布即冻结）。"""
        return self.status == SKILL_VERSION_STATUS_PUBLISHED

    def with_status(self, status: str | SkillVersionStatus) -> SkillVersion:
        """返回状态迁移后的**新**实例（单向迁移，非法迁移 → ``CONFLICT``）。

        Args:
            status: 目标状态（``SkillVersionStatus`` 字面值 / 枚举）。

        Returns:
            迁移后的新 :class:`SkillVersion`。

        Raises:
            DomainError: 非法状态迁移（``CONFLICT``）。
        """
        target = status.value if isinstance(status, SkillVersionStatus) else str(status)
        allowed = _ALLOWED_STATUS_TRANSITIONS.get(self.status, ())
        if target not in allowed:
            raise DomainError(
                f"SkillVersion 状态迁移非法：{self.status} → {target}",
                code=ErrorCode.CONFLICT,
                data={"reason": "invalid_status_transition", "from": self.status, "to": target},
            )
        return replace(self, status=target)

    def publish(self) -> SkillVersion:
        """发布（``DRAFT`` → ``PUBLISHED``；发布即冻结）。"""
        return self.with_status(SKILL_VERSION_STATUS_PUBLISHED)

    def deprecate(self) -> SkillVersion:
        """弃用（``DRAFT`` / ``PUBLISHED`` → ``DEPRECATED``）。"""
        return self.with_status(SKILL_VERSION_STATUS_DEPRECATED)

    def with_instructions(self, instructions: str) -> SkillVersion:
        """返回替换 ``instructions`` 后的**新**实例（**仅 ``DRAFT`` 允许**）。

        Raises:
            DomainError: 版本已发布 / 已弃用（``CONFLICT``，``published_immutable``）。
        """
        if self.status != SKILL_VERSION_STATUS_DRAFT:
            raise DomainError(
                "已发布 / 已弃用的 SkillVersion 不可变更 instructions",
                code=ErrorCode.CONFLICT,
                data={"reason": "published_immutable", "status": self.status},
            )
        return replace(self, instructions=instructions)

    def with_manifest(self, manifest: dict[str, Any]) -> SkillVersion:
        """返回替换 ``manifest`` 后的**新**实例（**仅 ``DRAFT`` 允许**）。

        Raises:
            DomainError: 版本已发布 / 已弃用（``CONFLICT``，``published_immutable``）。
        """
        if self.status != SKILL_VERSION_STATUS_DRAFT:
            raise DomainError(
                "已发布 / 已弃用的 SkillVersion 不可变更 manifest",
                code=ErrorCode.CONFLICT,
                data={"reason": "published_immutable", "status": self.status},
            )
        return replace(self, manifest=dict(manifest))


@dataclass
class SkillResource(AggregateRoot):
    """SkillResource（版本内资源；``storage_key`` 对接 ``Storage``）。

    Attributes:
        skill_version_id: 归属的 SkillVersion 标识。
        path: 包内相对路径（如 ``scripts/run.py``）。
        kind: 资源种类（``file`` / ``example`` / ``script`` / ``template``）。
        storage_key: ``Storage`` 对象键（``skills/{skill_id}/{version}/{path}``，可空）。
        checksum: 内容摘要（``StoredObject.etag``，可空）。
        size: 字节数（可空）。
    """

    skill_version_id: str = ""
    path: str = ""
    kind: str = SKILL_RESOURCE_KIND_FILE
    storage_key: str | None = None
    checksum: str | None = None
    size: int | None = None
