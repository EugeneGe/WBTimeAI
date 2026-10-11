"""``WorkflowService``——Workflow 用例编排器（W4 / T2-25；设计 §2.5 / §2.12 / §2.16）。

**应用/用例层（第三类）**：编排「Workflow 定义 / 版本发布 / 运行驱动 / 事件回放 +
持久化副作用」，**不**承载实体持久化、**不**提供被 Runtime 消费的 Protocol、**零**
Web / ORM（``test_application_import_boundary`` 强制）。

仿 :class:`~astra_application.services.agent_run_service.AgentRunService`：

- :meth:`open_run`：预建 ``WorkflowRun(PENDING, workflow_version_id 固定)``（**不执行**）；
- :meth:`execute`：经注入的 :class:`~astra_workflow.run.InlineRunner` 同步驱动引擎至
  终态 / ``WAITING_APPROVAL``；
- :meth:`cancel` / :meth:`list_events` / :meth:`status`：SSE 执行侧四回调（``StreamDeps``）；
- :meth:`create` / :meth:`publish` / :meth:`get` / :meth:`list_versions`：定义与版本管理。

🔴 **SSE 复用**（W4 裁定 R9 / §3 T2-24）：本服务仅提供 ``execute`` / ``list_events`` /
   ``cancel`` / ``status`` 四回调，流核心（``apps/api/src/astra_api/sse/stream.py``）由
   **API 层组合根**装配——``encoder.py`` 不改（``workflow.*`` 通道已随 T2-16 冻结）。

🔴 **审批续跑（T2-26 占位）**：:meth:`resume` 仅委派 ``InlineRunner.resume``（自
   ``WAITING_APPROVAL`` 续跑），**不实现**任何审批机制（挂起 / 决议 / 过期归 T2-26）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_workflow import (
    WORKFLOW_RUN_STATUS_PENDING,
    WORKFLOW_STATUS_ACTIVE,
    WORKFLOW_STATUS_DRAFT,
    WORKFLOW_TRIGGER_USER,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    Workflow,
    WorkflowNodeRunRepository,
    WorkflowRepository,
    WorkflowRun,
    WorkflowRunRepository,
    WorkflowVersion,
    WorkflowVersionRepository,
    build_definition,
)
from astra_workflow.run import (
    EXECUTION_MODE_INLINE,
    EXECUTION_MODE_QUEUED,
    InlineRunner,
    QueuedRunner,
    ReplayService,
)

from ..dto.run import RunEventDTO
from ..dto.workflow import (
    WorkflowDTO,
    WorkflowRunDTO,
    WorkflowVersionDTO,
)
from .base import ApplicationService

__all__ = ["WorkflowService"]


class WorkflowService(ApplicationService):
    """Workflow 用例编排器（DI 注入仓储 + 运行形态 + 可重建服务）。"""

    workflows: WorkflowRepository
    versions: WorkflowVersionRepository
    runs: WorkflowRunRepository
    node_runs: WorkflowNodeRunRepository | None
    inline: InlineRunner | None
    queued: QueuedRunner | None
    replay_service: ReplayService | None

    def __init__(
        self,
        *,
        workflows: WorkflowRepository,
        versions: WorkflowVersionRepository,
        runs: WorkflowRunRepository,
        node_runs: WorkflowNodeRunRepository | None = None,
        inline: InlineRunner | None = None,
        queued: QueuedRunner | None = None,
        replay_service: ReplayService | None = None,
    ) -> None:
        """装配用例编排器（全部依赖由**组合根**注入；零 ORM）。

        Args:
            workflows: Workflow 聚合仓储（领域 Protocol）。
            versions: WorkflowVersion 仓储（不可变快照）。
            runs: WorkflowRun 仓储。
            node_runs: WorkflowNodeRun 仓储（可空；供运行详情 / 重放）。
            inline: ``INLINE`` 运行形态（同步 / SSE 内联；可空则 ``execute`` 报错）。
            queued: ``QUEUED`` 运行形态（异步 ``TaskQueue``；可空则 ``mode=QUEUED`` 报错）。
            replay_service: 可重建服务（运行详情 / 审计；可空则 :meth:`replay` 报错）。
        """
        super().__init__(
            workflows=workflows,
            versions=versions,
            runs=runs,
            node_runs=node_runs,
            inline=inline,
            queued=queued,
            replay_service=replay_service,
        )

    # -- 定义（CRUD） -------------------------------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        name: str,
        created_by: str,
        description: str | None = None,
        workspace_id: str | None = None,
    ) -> WorkflowDTO:
        """创建 Workflow（``DRAFT``，无当前版本）。

        Args:
            tenant_id: 租户标识。
            name: 租户内唯一的流程名（``(tenant_id, name)`` 唯一）。
            created_by: 创建者用户标识。
            description: 描述（可空）。
            workspace_id: 归属工作空间（可空）。

        Returns:
            :class:`~astra_application.dto.workflow.WorkflowDTO`。

        Raises:
            DomainError: 同租户同名已存在（``CONFLICT``）。
        """
        if self.workflows.get_by_name(tenant_id, name) is not None:
            raise DomainError(
                "Workflow 名称已存在",
                code=ErrorCode.CONFLICT,
                data={"reason": "duplicate_name", "name": name},
            )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=name,
            description=description,
            workspace_id=workspace_id,
            created_by=created_by,
            status=WORKFLOW_STATUS_DRAFT,
        )
        return WorkflowDTO.from_entity(self.workflows.add(workflow))

    def get(self, workflow_id: str, *, tenant_id: str) -> WorkflowDTO:
        """返回某 Workflow 的 DTO（跨租户 / 不存在 → ``NOT_FOUND``）。"""
        return WorkflowDTO.from_entity(self._require_workflow(workflow_id, tenant_id))

    def list_workflows(self, *, tenant_id: str) -> list[WorkflowDTO]:
        """列出某租户下的全部 Workflow。"""
        return [WorkflowDTO.from_entity(item) for item in self.workflows.list_by_tenant(tenant_id)]

    def update(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> WorkflowDTO:
        """更新 Workflow 名称 / 描述 / 状态（缺省字段不变）。"""
        workflow = self._require_workflow(workflow_id, tenant_id)
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if status is not None:
            workflow.status = status
        workflow.touch()
        return WorkflowDTO.from_entity(self.workflows.update(workflow))

    def delete(self, workflow_id: str, *, tenant_id: str) -> None:
        """删除 Workflow（跨租户 / 不存在 → ``NOT_FOUND``）。"""
        workflow = self._require_workflow(workflow_id, tenant_id)
        self.workflows.delete(workflow)

    # -- 版本 / 发布 --------------------------------------------------------

    def publish(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        created_by: str,
        definition: dict[str, Any] | None = None,
        nodes: list[Any] | None = None,
        edges: list[Any] | None = None,
        entry: str | None = None,
        version: str | None = None,
    ) -> WorkflowVersionDTO:
        """发布一个新 ``workflow_version``（**发布即冻结**），并把 Workflow 置 ``ACTIVE``。

        一次发布**恒产出一个新版本**；``definition`` 为**完整图快照**（未显式传入时由
        ``nodes`` / ``edges`` 经 :func:`~astra_workflow.build_definition` 构造）。

        Args:
            workflow_id: 目标 Workflow 标识。
            tenant_id: 租户标识（隔离不变量）。
            created_by: 发布者用户标识。
            definition: 完整图快照（形如 ``{"nodes": [...], "edges": [...], "entry": ...}``）。
            nodes: 节点实体（``definition`` 缺省时用于构造快照）。
            edges: 连边实体（``definition`` 缺省时用于构造快照）。
            entry: 入口 ``node_key``（可空）。
            version: 版本号（缺省自动 ``v{n}``）。

        Returns:
            :class:`~astra_application.dto.workflow.WorkflowVersionDTO`。

        Raises:
            DomainError: Workflow 不存在（``NOT_FOUND``）/ 版本号已存在（``CONFLICT``）。
        """
        workflow = self._require_workflow(workflow_id, tenant_id)
        snapshot = self._resolve_definition(definition, nodes, edges, entry)
        resolved_version = str(version or "") or self._next_version(workflow.id)
        if self.versions.get_by_version(workflow.id, resolved_version) is not None:
            raise DomainError(
                "Workflow 版本已存在",
                code=ErrorCode.CONFLICT,
                data={"reason": "duplicate_version", "version": resolved_version},
            )
        new_version = self.versions.add(
            _new_version(
                workflow_id=workflow.id,
                version=resolved_version,
                definition=snapshot,
                created_by=created_by,
            )
        )
        workflow.current_version_id = new_version.id
        workflow.status = WORKFLOW_STATUS_ACTIVE
        workflow.touch()
        self.workflows.update(workflow)
        return WorkflowVersionDTO.from_entity(new_version)

    def list_versions(self, workflow_id: str, *, tenant_id: str) -> list[WorkflowVersionDTO]:
        """列出某 Workflow 的全部版本（**不可变快照**，按创建顺序）。"""
        workflow = self._require_workflow(workflow_id, tenant_id)
        return [
            WorkflowVersionDTO.from_entity(item)
            for item in self.versions.list_by_workflow(workflow.id)
        ]

    # -- 运行（open_run / execute / resume / cancel） ------------------------

    def open_run(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        execution_mode: str = EXECUTION_MODE_INLINE,
        run_input: dict[str, Any] | None = None,
        trigger: str = WORKFLOW_TRIGGER_USER,
        user_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowRunDTO:
        """预建 ``WorkflowRun``（``PENDING``，**固定引用**版本）并返回 DTO（**不执行**）。

        ``QUEUED`` 形态下**仅入队**（建 ``task(PENDING, workflow.run)`` 挂到运行），
        执行由 Worker 侧经 Application 完成（执行体与队列正交，R-23）。

        Args:
            workflow_id: 目标 Workflow 标识。
            tenant_id: 租户标识。
            execution_mode: 运行形态（``INLINE`` / ``QUEUED``）。
            run_input: 运行入参（``${input.xxx}`` 可见）。
            trigger: 触发来源（``user`` / ``schedule`` / ``event`` / ``api``）。
            user_id: 触发用户标识（可空）。
            version_id: 指定版本（缺省取 ``workflow.current_version_id``）。

        Returns:
            :class:`~astra_application.dto.workflow.WorkflowRunDTO`（``status=PENDING``）。

        Raises:
            DomainError: Workflow / 版本不存在（``NOT_FOUND``）/ 版本未发布
                （``VALIDATION_ERROR``）/ ``QUEUED`` 未装配队列（``CONFIGURATION_ERROR``）。
        """
        workflow = self._require_workflow(workflow_id, tenant_id)
        version = self._resolve_run_version(workflow, version_id)
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_version_id=version.id,
            trigger=trigger,
            status=WORKFLOW_RUN_STATUS_PENDING,
            input=dict(run_input or {}),
        )
        run = self.runs.add(run)
        if execution_mode == EXECUTION_MODE_QUEUED:
            run = self._enqueue(run, workflow, tenant_id=tenant_id)
        return WorkflowRunDTO.from_entity(run)

    def run(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        execution_mode: str = EXECUTION_MODE_INLINE,
        run_input: dict[str, Any] | None = None,
        trigger: str = WORKFLOW_TRIGGER_USER,
        user_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowRunDTO:
        """``open_run`` + 依形态执行（``INLINE`` 同步至终态；``QUEUED`` 仅入队）。"""
        created = self.open_run(
            workflow_id,
            tenant_id=tenant_id,
            execution_mode=execution_mode,
            run_input=run_input,
            trigger=trigger,
            user_id=user_id,
            version_id=version_id,
        )
        if execution_mode == EXECUTION_MODE_QUEUED:
            return self.get_run(created.id)
        return self.execute(created.id)

    def execute(self, run_id: str) -> WorkflowRunDTO:
        """同步执行一次运行至终态 / ``WAITING_APPROVAL``（阻塞）。

        Args:
            run_id: 目标运行标识。

        Returns:
            执行后的 :class:`~astra_application.dto.workflow.WorkflowRunDTO`。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 未装配 ``INLINE`` 运行形态
                （``CONFIGURATION_ERROR``）。
        """
        run = self._require_inline().execute(run_id)
        return WorkflowRunDTO.from_entity(run)

    def resume(self, run_id: str) -> WorkflowRunDTO:
        """自 ``WAITING_APPROVAL`` 续跑（审批决议后；**T2-26 占位，仅委派**）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 非 ``WAITING_APPROVAL``
                （``VALIDATION_ERROR``）/ 未装配 ``INLINE`` 运行形态（``CONFIGURATION_ERROR``）。
        """
        run = self._require_inline().resume(run_id)
        return WorkflowRunDTO.from_entity(run)

    def cancel(self, run_id: str) -> WorkflowRunDTO:
        """取消一次运行（``→ CANCELLED``；供 SSE 断连清理 / 显式取消）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 未装配 ``INLINE`` 运行形态
                （``CONFIGURATION_ERROR``）。
        """
        run = self._require_inline().cancel(run_id)
        return WorkflowRunDTO.from_entity(run)

    # -- 只读辅助（供 SSE / 事件端点，Router 不感知仓储） --------------------

    def get_run(self, run_id: str) -> WorkflowRunDTO:
        """返回某运行的 DTO（不存在 → ``NOT_FOUND``）。"""
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                "WorkflowRun 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        return WorkflowRunDTO.from_entity(run)

    def list_runs(self, workflow_id: str, *, tenant_id: str) -> list[WorkflowRunDTO]:
        """列出某 Workflow 全部版本下的运行（按版本 / 运行顺序）。"""
        workflow = self._require_workflow(workflow_id, tenant_id)
        collected: list[WorkflowRunDTO] = []
        for version in self.versions.list_by_workflow(workflow.id):
            collected.extend(
                WorkflowRunDTO.from_entity(item) for item in self.runs.list_by_version(version.id)
            )
        return collected

    def status(self, run_id: str) -> str | None:
        """返回某运行当前状态（不存在 → ``None``；供 SSE 判断是否接续实时通道）。"""
        if self.inline is not None:
            return self.inline.run_status(run_id)
        run = self.runs.get(run_id)
        return None if run is None else str(run.status or "")

    def list_events(self, run_id: str, last_event_id: int | None = None) -> list[RunEventDTO]:
        """返回 ``seq > last_event_id`` 的事件 DTO（``seq`` 升序，供 SSE 回放 / 续传）。

        Args:
            run_id: 目标运行标识。
            last_event_id: 续传起点（``None`` = 从头）。

        Returns:
            :class:`~astra_application.dto.run.RunEventDTO` 列表（未装配读取器 → 空，**不伪造**）。
        """
        if self.inline is None:
            return []
        raw = self.inline.list_events(run_id, last_event_id)
        return [
            RunEventDTO(
                seq=int(getattr(event, "seq", 0) or 0),
                type=str(getattr(event, "type", "") or ""),
                payload=dict(getattr(event, "payload", {}) or {}),
            )
            for event in raw
        ]

    def replay(self, run_id: str) -> dict[str, Any]:
        """重放一次运行（``workflow_run`` + ``workflow_node_run``，``I-P2-06``）。

        Returns:
            可序列化的重放快照字典（``WorkflowReplay.to_dict()``）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 未装配重放服务（``CONFIGURATION_ERROR``）。
        """
        if self.replay_service is None:
            raise DomainError(
                "未装配 ReplayService（无法重放运行）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "replay_service_missing", "workflow_run_id": run_id},
            )
        return self.replay_service.replay(run_id).to_dict()

    # -- 内部 ---------------------------------------------------------------

    def _require_workflow(self, workflow_id: str, tenant_id: str | None) -> Workflow:
        """加载 Workflow 并校验租户归属（不存在 / 跨租户 → ``NOT_FOUND``）。"""
        workflow = self.workflows.get(workflow_id)
        if workflow is None or (tenant_id and workflow.tenant_id != tenant_id):
            raise DomainError(
                "Workflow 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_not_found", "workflow_id": workflow_id},
            )
        return workflow

    def _require_inline(self) -> InlineRunner:
        """返回 ``INLINE`` 运行形态（未装配 → ``CONFIGURATION_ERROR``）。"""
        if self.inline is None:
            raise DomainError(
                "未装配 INLINE 运行形态（InlineRunner）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "inline_runner_missing"},
            )
        return self.inline

    def _resolve_run_version(self, workflow: Workflow, version_id: str | None) -> Any:
        """解析本次运行**固定引用**的已发布版本快照。

        Raises:
            DomainError: 无当前版本 / 版本不存在（``NOT_FOUND``）/ 版本未发布
                （``VALIDATION_ERROR``）。
        """
        target = str(version_id or workflow.current_version_id or "")
        if not target:
            raise DomainError(
                "Workflow 无当前版本，无法运行",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "current_version_missing", "workflow_id": workflow.id},
            )
        version = self.versions.get(target)
        if version is None:
            raise DomainError(
                "Workflow 版本不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_version_not_found", "workflow_version_id": target},
            )
        if version.status != WORKFLOW_VERSION_STATUS_PUBLISHED:
            raise DomainError(
                f"Workflow 版本尚未发布，不可运行：{version.status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={
                    "reason": "version_not_published",
                    "workflow_version_id": version.id,
                    "status": version.status,
                },
            )
        return version

    def _resolve_definition(
        self,
        definition: dict[str, Any] | None,
        nodes: list[Any] | None,
        edges: list[Any] | None,
        entry: str | None,
    ) -> dict[str, Any]:
        """解析完整图快照（显式 ``definition`` 优先，否则由节点 / 连边构造）。"""
        if definition is not None:
            return dict(definition)
        return build_definition(list(nodes or []), list(edges or []), entry=entry)

    def _next_version(self, workflow_id: str) -> str:
        """推导下一个版本号（``v{n}``；基于既有版本数量）。"""
        return f"v{len(self.versions.list_by_workflow(workflow_id)) + 1}"

    def _enqueue(self, run: Any, workflow: Workflow, *, tenant_id: str) -> Any:
        """把一次运行挂到 ``workflow.run`` 任务并入队（``QUEUED`` 形态；**不执行**）。"""
        if self.queued is None:
            raise DomainError(
                "QUEUED 形态需 QueuedRunner（异步 TaskQueue 未装配）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "queued_runner_missing", "workflow_run_id": run.id},
            )
        return self.queued.enqueue(
            str(run.id),
            payload={"tenant_id": tenant_id, "workspace_id": workflow.workspace_id},
        )


def _new_version(
    *,
    workflow_id: str,
    version: str,
    definition: dict[str, Any],
    created_by: str,
) -> WorkflowVersion:
    """构造一个**已发布**的不可变 ``WorkflowVersion``（发布即冻结）。"""
    return WorkflowVersion(
        workflow_id=workflow_id,
        version=version,
        definition=dict(definition),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by=created_by,
    )
