"""``astra_workspace`` 应用用例层（跨层编排；W7 / T2-38；R3 / T2-60 增远程用例）。

与 :mod:`astra_workspace.services`（既有 ``WorkspaceService`` **领域服务**）区分：
``application/`` 承载**跨层编排用例**（加载实体 → 经注入的 ``Storage`` / ``SandboxProvider`` /
``GitService`` / 任务派发 协同），组合根（``factory``）装配其依赖。

``remote_task_service``（R3 / T2-60）承载**远程 Project / Task / Attempt / Event / Log /
Diff / Artifact** 用例、scope 校验与事件游标服务；依赖全部经**注入 Protocol**，
能力包**零** Web / **零** ``astra_runtime`` / **零** ORM（分层 L-2 / L-3）。
"""

from __future__ import annotations

from .project_service import (
    AttemptCheckoutResult,
    CloneResult,
    ProjectService,
    TaskDispatcher,
)
from .remote_task_service import (
    CAPABILITY_ARTIFACT_DOWNLOAD,
    CAPABILITY_GIT_APPLY,
    CAPABILITY_GIT_DIFF,
    CAPABILITY_GIT_PUSH,
    CAPABILITY_PROJECT_CLONE,
    CAPABILITY_PROJECT_READ,
    CAPABILITY_TASK_CANCEL,
    CAPABILITY_TASK_READ,
    CAPABILITY_TASK_SUBMIT,
    ExecutionTaskEventSource,
    RemoteAccessDecision,
    RemoteAttemptView,
    RemoteAuditSink,
    RemoteEventPage,
    RemotePrincipal,
    RemoteProjectStatus,
    RemoteTaskAuthorizer,
    RemoteTaskService,
    RemoteTaskSpec,
    RemoteTaskSubmitter,
    RemoteTaskView,
    TaskEvent,
    TaskEventSource,
    TaskLogView,
)

__all__ = [
    "ProjectService",
    "CloneResult",
    "AttemptCheckoutResult",
    "TaskDispatcher",
    # R3 / T2-60：远程 Task / Project 用例
    "RemoteTaskService",
    "RemotePrincipal",
    "RemoteAccessDecision",
    "RemoteTaskView",
    "RemoteAttemptView",
    "RemoteProjectStatus",
    "TaskEvent",
    "TaskLogView",
    "RemoteEventPage",
    "RemoteTaskSpec",
    "RemoteTaskAuthorizer",
    "RemoteAuditSink",
    "RemoteTaskSubmitter",
    "TaskEventSource",
    "ExecutionTaskEventSource",
    "CAPABILITY_TASK_SUBMIT",
    "CAPABILITY_TASK_READ",
    "CAPABILITY_TASK_CANCEL",
    "CAPABILITY_GIT_DIFF",
    "CAPABILITY_GIT_APPLY",
    "CAPABILITY_GIT_PUSH",
    "CAPABILITY_ARTIFACT_DOWNLOAD",
    "CAPABILITY_PROJECT_READ",
    "CAPABILITY_PROJECT_CLONE",
]
