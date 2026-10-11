"""``astra_workspace`` 应用用例层（跨层编排；W7 / T2-38）。

与 :mod:`astra_workspace.services`（既有 ``WorkspaceService`` **领域服务**）区分：
``application/`` 承载**跨层编排用例**（加载实体 → 经注入的 ``Storage`` / ``SandboxProvider`` /
``GitService`` / 任务派发 协同），组合根（``factory``）装配其依赖。
"""

from __future__ import annotations

from .project_service import (
    AttemptCheckoutResult,
    CloneResult,
    ProjectService,
    TaskDispatcher,
)

__all__ = ["ProjectService", "CloneResult", "AttemptCheckoutResult", "TaskDispatcher"]
