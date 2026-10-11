"""资源权限仓储接口（**仅 Protocol**，零 ORM，C-03；W3 裁定 §1.1）。

对应 ORM 表：``resource_permission``。SQLAlchemy 实现位于
``astra_database.repositories.permission_repository``。

🔴 **类型级（``resource_id IS NULL``）唯一性由应用层 ``upsert`` 保证**（SQL 唯一约束不判重
   NULL，见 W3 裁定 §1.1）：同 6 键（``tenant_id/subject_type/subject_id/resource_type/
   resource_id/action``）覆盖；实例级由 DB 唯一键保证。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.permission import ResourcePermission

__all__ = ["ResourcePermissionRepository"]


@runtime_checkable
class ResourcePermissionRepository(Protocol):
    """资源权限仓储接口（多租户隔离）。"""

    def get(self, permission_id: str) -> ResourcePermission | None:
        """按主键获取权限条目，不存在返回 ``None``。"""
        ...

    def add(self, permission: ResourcePermission) -> ResourcePermission:
        """新增一条权限条目并返回。"""
        ...

    def upsert(self, permission: ResourcePermission) -> ResourcePermission:
        """按 6 键（``tenant_id/subject_type/subject_id/resource_type/resource_id/action``）
        **幂等**新增或更新（类型级 NULL 亦适用）。"""
        ...

    def list_for_subject(
        self, tenant_id: str, subject_type: str, subject_id: str
    ) -> list[ResourcePermission]:
        """列出某主体在租户下的全部权限条目（主体级 ALLOW/DENY 集合）。"""
        ...

    def list_by_resource(
        self, tenant_id: str, resource_type: str, resource_id: str
    ) -> list[ResourcePermission]:
        """列出某租户下、某 ``resource_type`` × ``resource_id`` 的**全部**权限条目。

        与**主体无关**（跨 subject 聚合），供「按资源」列权使用（如
        ``/mcp/permissions?mcp_tool_id=`` 经 ``mcp_tool_id → tool 行 id`` 映射后按资源列举，
        W3 / T2-13 补丁 · 裁定 §21.4 X1/X2）。``resource_id`` 为**实例级**标识（非空）。
        """
        ...

    def delete(self, permission_id: str) -> None:
        """删除一条权限条目。"""
        ...
