"""``WorkspaceRepository`` 接口。

🔴 仅 Protocol（零 ORM 依赖）；SQLAlchemy 实现位于
``astra_workspace/repositories/workspace_repository.py``。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.workspace import Workspace
from .base import Repository

__all__ = ["WorkspaceRepository"]


@runtime_checkable
class WorkspaceRepository(Repository[Workspace], Protocol):
    """工作区仓储接口（多租户隔离）。"""

    def list_by_tenant(self, tenant_id: str) -> list[Workspace]:
        """列出某租户下的全部工作区。"""
        ...

    def get_by_owner(self, tenant_id: str, owner_id: str) -> list[Workspace]:
        """列出某租户下某拥有者的全部工作区。"""
        ...
