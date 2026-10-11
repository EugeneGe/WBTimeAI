"""``WorkspaceService``——工作区领域服务（设计 §2.9）。

覆盖创建 / 列表 / 详情（**租户校验**）/ 更新设置 / 更新配置。
``settings`` / ``config`` 以 JSON 落库并往返；``workspace_type`` 仅允许
``personal`` / ``team``（非法 → ``VALIDATION_ERROR``）；**多租户隔离**
（``list_by_tenant`` 仅返回同租户；跨租户 ``get`` 抛 ``WORKSPACE_NOT_FOUND``）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_domain import Workspace, WorkspaceType
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import SqlWorkspaceRepository

__all__ = ["WorkspaceService"]


class WorkspaceService:
    """工作区领域服务（多租户隔离）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        workspace_type: str = WorkspaceType.PERSONAL.value,
        settings: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Workspace:
        """创建工作区。

        Args:
            tenant_id: 所属租户标识。
            owner_id: 拥有者用户标识。
            name: 工作区名称。
            workspace_type: 工作区类型（``personal`` | ``team``）。
            settings: 初始设置（JSON 结构）。
            config: 初始配置（JSON 结构）。

        Returns:
            新建的 :class:`~astra_domain.entities.workspace.Workspace`。

        Raises:
            DomainError: 名称为空（``VALIDATION_ERROR``）或类型非法（``VALIDATION_ERROR``）。
        """
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise DomainError(
                "工作区名称不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        normalized_type = WorkspaceType.ensure(workspace_type)
        with session_scope(self._session_factory) as session:
            return SqlWorkspaceRepository(session).add(
                Workspace(
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    name=normalized_name,
                    workspace_type=normalized_type.value,
                    settings=dict(settings) if settings else {},
                    config=dict(config) if config else {},
                )
            )

    def list_for_tenant(self, tenant_id: str) -> list[Workspace]:
        """列出某租户下的全部工作区（多租户隔离）。"""
        with session_scope(self._session_factory) as session:
            return SqlWorkspaceRepository(session).list_by_tenant(tenant_id)

    def get(self, workspace_id: str, *, tenant_id: str) -> Workspace:
        """按 id 获取工作区（**校验租户归属**）。

        Args:
            workspace_id: 工作区标识。
            tenant_id: 期望的租户标识（须与工作区归属一致）。

        Returns:
            :class:`~astra_domain.entities.workspace.Workspace`。

        Raises:
            DomainError: 不存在或跨租户（``WORKSPACE_NOT_FOUND``）。
        """
        with session_scope(self._session_factory) as session:
            workspace = SqlWorkspaceRepository(session).get(workspace_id)
            if workspace is None or workspace.tenant_id != tenant_id:
                raise DomainError(
                    "工作区不存在",
                    code=ErrorCode.WORKSPACE_NOT_FOUND,
                    data={"workspace_id": workspace_id},
                )
            return workspace

    def update_settings(
        self, workspace_id: str, *, tenant_id: str, settings: dict[str, Any]
    ) -> Workspace:
        """更新工作区设置（JSON 结构，租户校验）。"""
        return self._update_json_field(
            workspace_id, tenant_id=tenant_id, field="settings", value=settings
        )

    def update_config(
        self, workspace_id: str, *, tenant_id: str, config: dict[str, Any]
    ) -> Workspace:
        """更新工作区配置（JSON 结构，租户校验）。"""
        return self._update_json_field(
            workspace_id, tenant_id=tenant_id, field="config", value=config
        )

    def _update_json_field(
        self,
        workspace_id: str,
        *,
        tenant_id: str,
        field: str,
        value: dict[str, Any],
    ) -> Workspace:
        """内部：更新某 JSON 字段并持久化（租户校验 + 时间戳刷新）。"""
        if not isinstance(value, dict):
            raise DomainError(
                f"{field} 必须为对象（字典）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": field},
            )
        with session_scope(self._session_factory) as session:
            repo = SqlWorkspaceRepository(session)
            workspace = repo.get(workspace_id)
            if workspace is None or workspace.tenant_id != tenant_id:
                raise DomainError(
                    "工作区不存在",
                    code=ErrorCode.WORKSPACE_NOT_FOUND,
                    data={"workspace_id": workspace_id},
                )
            setattr(workspace, field, dict(value))
            workspace.touch()
            return repo.update(workspace)
