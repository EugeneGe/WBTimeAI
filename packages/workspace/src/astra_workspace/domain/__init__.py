"""``astra_workspace`` 领域子模块（实体 / 仓储接口；W7 / T2-37）。

本子模块**零框架依赖**（不引用 ORM / Web / 校验框架），可纯单测。仿 Phase 2 增量资源
（``skill`` / ``mcp`` / ``knowledge`` / ``memory``）的**能力包自含布局**（W7 裁定 R1）。

- :class:`Project` / :class:`WorkspaceEnvironment`：Workspace 增强实体；
- :class:`ProjectRepository`：Project 仓储 Protocol（SQL 实现落
  ``astra_workspace.repositories.project_repository``）。

🔴 既有 ``Workspace`` 实体 / ``WorkspaceRepository`` Protocol **原地不动**
   （仍在 ``astra_domain``，零破坏，R1）。
"""

from __future__ import annotations

from .project import Project, WorkspaceEnvironment
from .repository import ProjectRepository, WorkspaceEnvironmentRepository

__all__ = [
    "Project",
    "WorkspaceEnvironment",
    "ProjectRepository",
    "WorkspaceEnvironmentRepository",
]
