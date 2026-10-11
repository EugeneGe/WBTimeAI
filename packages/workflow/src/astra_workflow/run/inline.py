"""``INLINE`` 运行形态（同步 / SSE 内联；W4 / T2-24；设计 §2.5 / §2.9 / §2.16）。

一次 INLINE 运行 = ``WorkflowService``（Application）预建 ``WorkflowRun``（固定引用
不可变 ``workflow_version``）→ :class:`InlineRunner` **同步**驱动
:class:`~astra_workflow.engine.WorkflowEngine` → 逐节点落 ``workflow_node_run``
+ emit ``Workflow*`` 事件 → 运行终态落 ``workflow_run``。

本模块产出 SSE 流所需的**四个执行侧回调**（``execute`` / ``list_events`` /
``cancel`` / ``run_status``），由**组合根**连同 ``event_bus`` 装配为
``apps/api/src/astra_api/sse/stream.py`` 的 :class:`StreamDeps`——
**SSE 编码 / 通道不改**（``workflow.*`` / ``approval.*`` 已随 T2-16 冻结，F14/R9）。

🔴 ``astra_workflow`` 为能力包（**禁 Web**），故**不 import** ``astra_api`` /
``fastapi`` / ``starlette``；流核心的复用发生在 **API 层组合根**。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from astra_common.time import ensure_utc
from astra_core import DomainError, ErrorCode
from astra_event import (
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowNodeCompleted,
    WorkflowNodeStarted,
    WorkflowStarted,
)

from ..domain import (
    APPROVAL_EXPIRED_ERROR,
    WORKFLOW_RUN_STATUS_CANCELLED,
    WorkflowNodeRun,
    WorkflowNodeRunRepository,
    WorkflowRun,
    WorkflowRunRepository,
    WorkflowVersionRepository,
)
from ..engine import (
    NullNodeRunRecorder,
    WorkflowEngine,
    WorkflowEventSink,
)

# 🔴 必须**晚于** ``..engine`` 导入：``engine.scheduler`` 需从 ``astra_workflow.nodes``
#    取 ``NodeContext``（跨包循环导入的**唯一**安全顺序，见 ``nodes/__init__.py`` 头注）。
from ..nodes import NodeContext

__all__ = [
    "EXECUTION_MODE_INLINE",
    "DEFAULT_ERROR_TYPE",
    "RepositoryNodeRunRecorder",
    "EventBusWorkflowEventSink",
    "InlineRunner",
]


#: 运行形态字面值：内联（同步 / SSE）。
EXECUTION_MODE_INLINE = "INLINE"

#: 运行失败的默认 ``error_type``（``WorkflowFailed`` 事件载荷）。
DEFAULT_ERROR_TYPE = "WORKFLOW_FAILED"


class RepositoryNodeRunRecorder:
    """``NodeRunRecorder`` 适配器（把节点执行记录落在 ``WorkflowNodeRunRepository``）。

    使引擎保持**零 ORM**：持久化经 Protocol 端口外抛，由组合根注入 SQL 实现。
    """

    def __init__(self, repository: WorkflowNodeRunRepository) -> None:
        """初始化。

        Args:
            repository: 节点执行记录仓储（领域实体口径）。
        """
        self._repository = repository

    def add(self, node_run: WorkflowNodeRun) -> WorkflowNodeRun:
        """写入一条节点执行记录并返回。"""
        return self._repository.add(node_run)

    def update(self, node_run: WorkflowNodeRun) -> WorkflowNodeRun:
        """更新一条节点执行记录并返回。"""
        return self._repository.update(node_run)

    def list_by_run(self, workflow_run_id: str) -> list[WorkflowNodeRun]:
        """列出某运行下的全部节点记录（按执行顺序）。"""
        return self._repository.list_by_run(workflow_run_id)


class EventBusWorkflowEventSink:
    """``WorkflowEventSink`` 真实实现（emit 既有 ``astra_event`` Workflow 事件）。

    W4 裁定 §6.4 #3：SSE 通道名已在 ``encoder.py`` 冻结，事件**只构造既有类型**，
    **不新增通道**；``Approval*`` 事件由 :mod:`astra_security.permission.approval`
    发布（T2-26），不在本模块。
    """

    def __init__(
        self,
        bus: Any,
        *,
        workflow_id_resolver: Callable[[WorkflowRun], str] | None = None,
    ) -> None:
        """初始化。

        Args:
            bus: 事件总线（``EventBus`` Protocol：``publish``）。
            workflow_id_resolver: 由运行解析 ``workflow_id``（经固定引用版本回读）；
                缺省返回空串（**不伪造**）。
        """
        self._bus = bus
        self._resolver = workflow_id_resolver

    # -- WorkflowEventSink --------------------------------------------------

    def run_started(self, run: WorkflowRun) -> None:
        """发布 ``workflow.started``。"""
        self._publish(
            WorkflowStarted.create(
                workflow_id=self._workflow_id(run),
                run_id=str(run.id or ""),
                workflow_version_id=str(run.workflow_version_id or ""),
            )
        )

    def node_started(self, run: WorkflowRun, node_run: WorkflowNodeRun) -> None:
        """发布 ``workflow.node.started``。"""
        self._publish(
            WorkflowNodeStarted.create(
                workflow_id=self._workflow_id(run),
                run_id=str(run.id or ""),
                node_id=str(node_run.node_key or ""),
                node_type=self._node_type(run, node_run),
            )
        )

    def node_completed(self, run: WorkflowRun, node_run: WorkflowNodeRun) -> None:
        """发布 ``workflow.node.completed``（完成 / 挂起 / 失败均走此通道）。"""
        self._publish(
            WorkflowNodeCompleted.create(
                workflow_id=self._workflow_id(run),
                run_id=str(run.id or ""),
                node_id=str(node_run.node_key or ""),
                status=str(node_run.status or ""),
                duration_ms=self._duration_ms(node_run),
            )
        )

    def run_completed(self, run: WorkflowRun) -> None:
        """发布 ``workflow.completed``。"""
        self._publish(
            WorkflowCompleted.create(
                workflow_id=self._workflow_id(run),
                run_id=str(run.id or ""),
                duration_ms=self._duration_ms(run),
            )
        )

    def run_failed(self, run: WorkflowRun) -> None:
        """发布 ``workflow.failed``（``error_type`` 由 :attr:`run.error` 取优先字面值）。"""
        self._publish(
            WorkflowFailed.create(
                workflow_id=self._workflow_id(run),
                run_id=str(run.id or ""),
                error_type=self._error_type(run),
                error=run.error,
                duration_ms=self._duration_ms(run),
            )
        )

    # -- 内部 ---------------------------------------------------------------

    def _publish(self, event: Any) -> None:
        """发布事件（无总线 → 静默跳过；总线异常**不静默**，向上抛出）。"""
        if self._bus is None:
            return
        self._bus.publish(event)

    def _workflow_id(self, run: WorkflowRun) -> str:
        """解析 ``workflow_id``。"""
        if self._resolver is not None:
            return str(self._resolver(run) or "")
        return ""

    @staticmethod
    def _node_type(run: WorkflowRun, node_run: WorkflowNodeRun) -> str | None:
        """取节点类型（不可得 → ``None``）。"""
        graph = getattr(run, "graph", None)
        if graph is not None:
            node = graph.get(node_run.node_key) if hasattr(graph, "get") else None
            if node is not None:
                return str(getattr(node, "type", "") or "") or None
        return None

    @staticmethod
    def _error_type(run: WorkflowRun) -> str:
        """由 ``run.error`` 推导 ``error_type``。

        ``APPROVAL_EXPIRED`` 等**已知**字面值优先；否则回落 :data:`DEFAULT_ERROR_TYPE`。
        """
        error = str(run.error or "").strip()
        if error == APPROVAL_EXPIRED_ERROR:
            return APPROVAL_EXPIRED_ERROR
        return DEFAULT_ERROR_TYPE

    @staticmethod
    def _duration_ms(record: Any) -> int | None:
        """计算 ``started_at → completed_at`` 毫秒耗时（不可得 → ``None``）。

        先 ``ensure_utc`` 归一两端——防 naive（SQLite 回读）/ aware（``utcnow()``）混用相减抛
        ``TypeError``（本轮 resume 路径漏洞的**防御层**；根治见 ``repositories/mappers.py``）。
        """
        started: datetime | None = getattr(record, "started_at", None)
        completed: datetime | None = getattr(record, "completed_at", None)
        if started is None or completed is None:
            return None
        return int((ensure_utc(completed) - ensure_utc(started)).total_seconds() * 1000)


class InlineRunner:
    """``INLINE`` 运行形态：**同步**驱动一次 ``workflow_run`` 至终态 / 挂起。

    供 Application ``WorkflowService`` 与 API 层 SSE 组合根复用：

    - :meth:`execute`：加载运行 + **固定引用**的不可变版本 → 驱动引擎 → 落终态；
    - :meth:`list_events`：读持久化事件（供 SSE ``Last-Event-ID`` 续传）；
    - :meth:`cancel`：置 ``CANCELLED`` 终态并落库；
    - :meth:`run_status`：读当前状态（供 SSE 判断是否接续实时通道）。

    Attributes:
        engine: 执行引擎。
        runs: 运行记录仓储。
        node_runs: 节点执行记录仓储（可选，供组合根直取）。
        versions: 版本仓储（回读不可变快照）。
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        runs: WorkflowRunRepository,
        *,
        node_runs: WorkflowNodeRunRepository | None = None,
        versions: WorkflowVersionRepository | None = None,
        sink: WorkflowEventSink | None = None,
        event_reader: Callable[[str, int | None], list[Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """装配内联运行器（全部依赖由**组合根**注入）。

        Args:
            engine: 执行引擎。
            runs: 运行记录仓储。
            node_runs: 节点执行记录仓储（可空；引擎已持有 recorder 时可省略）。
            versions: 版本仓储（``resume`` 回读不可变快照用）。
            sink: 事件出口（缺省不发事件）。
            event_reader: 事件读取器 ``(run_id, last_seq) -> list[Event]``（供
                SSE 回放；缺省返回空列表——**不伪造**事件）。
            clock: 时间源（测试可注入 fake clock）。
        """
        self.engine = engine
        self.runs = runs
        self.node_runs = node_runs
        self.versions = versions
        self._sink = sink
        self._event_reader = event_reader
        self._clock = clock
        # 后期绑定：把节点记录仓储适配为引擎的 ``NodeRunRecorder``（引擎保持零 ORM）。
        # 🔴 仅回填**空实现**——组合根已显式装配 recorder 时**不覆盖**，避免静默改判。
        if node_runs is not None and isinstance(engine.recorder, NullNodeRunRecorder):
            engine.bind_recorder(RepositoryNodeRunRecorder(node_runs))

    # -- SSE 执行侧四回调（组合根装配 ``StreamDeps``） ------------------------

    def execute(self, run_id: str) -> WorkflowRun:
        """同步执行一次运行（阻塞至终态 / ``WAITING_APPROVAL``）。

        Args:
            run_id: 目标运行标识。

        Returns:
            终态或 ``WAITING_APPROVAL`` 的 :class:`WorkflowRun`。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 版本缺失或仓储未装配
                （``CONFIGURATION_ERROR``）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法执行：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        version = self._resolve_version(run)
        context = NodeContext(
            run_id=str(run.id or ""),
            tenant_id=run.tenant_id,
            workflow_run=run,
        )
        executed = self.engine.run(
            version,
            dict(run.input or {}),
            ctx=context,
            run=run,
        )
        return self.runs.update(executed)

    def resume(self, run_id: str) -> WorkflowRun:
        """自 ``WAITING_APPROVAL`` 续跑（审批通过后；引擎自挂起节点继续拓扑）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 非 ``WAITING_APPROVAL``
                （``VALIDATION_ERROR``）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法续跑：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        context = NodeContext(
            run_id=str(run.id or ""),
            tenant_id=run.tenant_id,
            workflow_run=run,
        )
        resumed = self.engine.resume(run, ctx=context)
        return self.runs.update(resumed)

    def list_events(self, run_id: str, last_event_id: int | None = None) -> list[Any]:
        """读 ``seq > last_event_id`` 的持久化事件（``seq`` 升序，供 SSE 回放 / 续传）。"""
        if self._event_reader is None:
            return []
        return list(self._event_reader(run_id, last_event_id))

    def cancel(self, run_id: str) -> WorkflowRun:
        """取消一次运行（``PENDING`` / ``RUNNING`` / ``WAITING_APPROVAL → CANCELLED``）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法取消：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        if run.status != WORKFLOW_RUN_STATUS_CANCELLED:
            run.cancel()
            self.runs.update(run)
        if self._sink is not None:
            self._sink.run_failed(run)
        return run

    def run_status(self, run_id: str) -> str | None:
        """读运行当前状态（不存在 → ``None``）。"""
        run = self.runs.get(run_id)
        if run is None:
            return None
        return str(run.status or "")

    # -- 内部 ---------------------------------------------------------------

    def _resolve_version(self, run: WorkflowRun) -> Any:
        """经 ``workflow_version_id``（**固定引用**）回读不可变版本快照。

        Raises:
            DomainError: 版本仓储未装配（``CONFIGURATION_ERROR``）/ 版本不存在
                （``NOT_FOUND``）。
        """
        if self.versions is None:
            raise DomainError(
                "执行需版本仓储（versions）以回读不可变版本快照",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "versions_repository_missing", "workflow_run_id": run.id},
            )
        version = self.versions.get(str(run.workflow_version_id or ""))
        if version is None:
            raise DomainError(
                f"运行引用的版本不存在：{run.workflow_version_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_version_not_found", "workflow_run_id": run.id},
            )
        return version
