"""资源权限域实体（设计 §2.10；W3 裁定 §1 / Erratum-D）。

:class:`ResourcePermission` 是**权限单一判定链**（§2.10.1 / W3 裁定 §2）的**主体级**载体：
``subject（role/user/agent）× resource_type × resource_id? × action → effect``。

🔴 零框架依赖（纯 dataclass）——受 ``test_layering.py::test_domain_has_no_framework_dependencies``
   覆盖。

- ``effect`` **仅** ``ALLOW`` / ``DENY``（**无 ``APPROVAL``**，Erratum-G）：审批走 ``approval`` 表；
- ``resource_id`` 为 ``None`` ＝**类型级授权**（覆盖该 ``resource_type`` 全部实例）；
- ``scope`` 承载细粒度 ``{capabilities, deny, paths, commands, allow}``（见 §4）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import TOOL_EFFECT_ALLOW
from .base import Entity

__all__ = ["ResourcePermission"]


@dataclass
class ResourcePermission(Entity):
    """资源权限条目（主体级授权；设计 §2.10）。

    Attributes:
        subject_type: 主体类型（``role`` / ``user`` / ``agent``）。
        subject_id: 主体标识（弱引用；服务层校验存在性，不加 FK）。
        resource_type: 资源类型（``AGENT``/``SKILL``/``TOOL``/``MCP``/``MODEL``/
            ``WORKFLOW``/``KNOWLEDGE``/``PROJECT``/``WORKSPACE``/``CONNECTOR``）。
        resource_id: 资源标识；``None`` ＝ 类型级授权（覆盖该类型全部实例）。
        action: 动作（``VIEW``/``USE``/``CREATE``/``EDIT``/``DELETE``/``PUBLISH``/
            ``SHARE``/``EXECUTE``）。
        effect: 效果（``ALLOW`` / ``DENY``；**无 ``APPROVAL``**）。
        scope: 细粒度范围（JSON；``{capabilities, deny, paths, commands, allow}``）。
    """

    subject_type: str = ""
    subject_id: str = ""
    resource_type: str = ""
    resource_id: str | None = None
    action: str = ""
    effect: str = TOOL_EFFECT_ALLOW
    scope: dict[str, Any] = field(default_factory=dict)

    @property
    def is_type_level(self) -> bool:
        """是否为**类型级**授权（``resource_id`` 为空）。"""
        return self.resource_id is None
