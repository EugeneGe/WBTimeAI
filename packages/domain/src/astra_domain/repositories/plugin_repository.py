"""``PluginRepository`` 接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``plugin``（随迁移 ``0010_phase2_permission_plugin`` 落地）。
SQLAlchemy 实现位于 ``astra_database.repositories``。

W3 / T2-17：``/plugins`` 已装 / 安装 / 卸载 的读写入口（Router 经 ``AppServices`` 取用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from astra_common.time import utcnow
from astra_core import generate_id

__all__ = ["PluginRecord", "PluginRepository"]

#: 插件安装初态。
PLUGIN_STATUS_INSTALLED = "installed"
#: 插件卸载态。
PLUGIN_STATUS_UNINSTALLED = "uninstalled"


@dataclass
class PluginRecord:
    """插件记录（仅持久化字段）。

    Attributes:
        id: 插件唯一标识（UUIDv7）。
        name: 插件名（全局唯一）。
        version: 版本。
        kind: 种类（如 ``connector`` / ``tool``）。
        entry_point: 入口点（可空）。
        permissions: 声明权限（字面值列表）。
        manifest: 清单（JSON）。
        status: 状态（``installed`` / ``uninstalled``）。
        installed_at: 安装时间（UTC）。
    """

    id: str = field(default_factory=generate_id)
    name: str = ""
    version: str = ""
    kind: str = ""
    entry_point: str | None = None
    permissions: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    status: str = PLUGIN_STATUS_INSTALLED
    installed_at: datetime = field(default_factory=utcnow)


@runtime_checkable
class PluginRepository(Protocol):
    """插件仓储接口。"""

    def add(self, record: PluginRecord) -> PluginRecord:
        """新增（安装）插件并返回。"""
        ...

    def get(self, plugin_id: str) -> PluginRecord | None:
        """按 id 获取插件，不存在返回 ``None``。"""
        ...

    def get_by_name(self, name: str) -> PluginRecord | None:
        """按 ``name`` 获取插件，不存在返回 ``None``。"""
        ...

    def list_all(self) -> list[PluginRecord]:
        """列出全部插件（按 ``name`` 升序）。"""
        ...

    def delete(self, plugin_id: str) -> None:
        """删除（卸载）插件。"""
        ...
