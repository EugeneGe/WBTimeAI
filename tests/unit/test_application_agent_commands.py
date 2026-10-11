"""Application 用例编排单测（W6 / T1-27；设计 §2.2 / §2.6 / §2.9）。

以 **fake Runtime + 内存仓储** 驱动 :class:`~astra_application.AgentRunService`，
断言「应用/用例层」编排契约（不依赖 DB / Web）：

- :meth:`open_run`：建 ``RUNNING`` Run + 挂靠 ``agent.run`` 任务（**不执行**）；
- :meth:`execute`：组 ``RunContext``（含 ``user_message`` / ``should_cancel`` / 预建 ``run``）
  → 调 Runtime → 同步挂靠 task 终态；
- :meth:`cancel`：置取消信号 + 终态 ``CANCELLED`` + 同步 task；
- 缺失 Agent / Run → ``DomainError(NOT_FOUND)``。

本文件属**纯单测**（``tests/unit``），零 ORM / 零 Web（可用 fake 替换全部协作者）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from astra_application import (
    AgentRunService,
    CancelAgentRunCommand,
    CancelAgentRunHandler,
    CreateAgentTaskCommand,
    CreateAgentTaskHandler,
    ExecuteAgentCommand,
    ExecuteAgentHandler,
)
from astra_core import DomainError, ErrorCode
from astra_domain import (
    RUN_STATUS_CANCELLED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    Agent,
    AgentRun,
    AgentVersion,
)
from astra_runtime import RunResult

# -- 协作者 fake -------------------------------------------------------------


class FakeRunRepository:
    """内存 Run 仓储（实现 ``add`` / ``get`` / ``update`` / ``list``）。"""

    def __init__(self) -> None:
        self.items: dict[str, AgentRun] = {}

    def add(self, entity: AgentRun) -> AgentRun:
        self.items[entity.id] = entity
        return entity

    def get(self, entity_id: str) -> AgentRun | None:
        return self.items.get(entity_id)

    def update(self, entity: AgentRun) -> AgentRun:
        self.items[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[AgentRun]:
        return [
            run
            for run in self.items.values()
            if all(getattr(run, key, None) == value for key, value in filters.items())
        ]


class FakeAgents:
    """伪 Agent 服务（只需 ``get_agent`` / ``load_version``）。"""

    def __init__(self, agent: Agent | None, version: AgentVersion | None) -> None:
        self._agent = agent
        self._version = version

    def get_agent(self, agent_id: str) -> Agent | None:
        if self._agent is not None and self._agent.id == agent_id:
            return self._agent
        return None

    def load_version(self, agent: Agent, version_id: str | None = None) -> AgentVersion:
        assert self._version is not None
        return self._version


class FakeRuntime:
    """伪 Runtime：记录收到的 ``RunContext``，返回脚本化的 ``RunResult``。"""

    def __init__(self) -> None:
        self.contexts: list[Any] = []

    def run(self, context: Any) -> RunResult:
        self.contexts.append(context)
        run_id = context.run.id if context.run is not None else "unknown"
        return RunResult(
            run_id=run_id,
            status=RUN_STATUS_SUCCESS,
            success=True,
            error_type=None,
            duration_ms=3,
            tool_error_count=0,
            iterations=1,
            final_content="done",
        )


class FakeRunService:
    """伪 ``RunService``：记录 ``create_for_run`` / ``finish`` 调用。"""

    def __init__(self) -> None:
        self.created: list[tuple[str, str | None, str | None]] = []
        self.finished: list[tuple[str, str, str | None]] = []
        self._tasks: dict[str, Any] = {}

    def create_for_run(
        self,
        run: AgentRun,
        *,
        request_fingerprint: str | None = None,
        user_message: str | None = None,
    ) -> Any:
        self.created.append((run.id, request_fingerprint, user_message))
        payload: dict[str, Any] = {}
        if request_fingerprint is not None:
            payload["request_fingerprint"] = request_fingerprint
        if user_message is not None:
            payload["user_message"] = user_message
        task = SimpleNamespace(task_id=f"task-{run.id}", payload=payload)
        self._tasks[run.id] = task
        run.task_id = task.task_id
        return task

    def get_for_run(self, run: AgentRun) -> Any:
        return self._tasks.get(run.id)

    def finish(
        self,
        run: AgentRun,
        run_status: str,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Any:
        self.finished.append((run.id, run_status, error))
        return None


class Harness:
    """测试夹具：持有 fake 协作者 + 装配好的 ``AgentRunService``（保留强类型引用）。"""

    def __init__(self, agent: Agent | None, version: AgentVersion | None) -> None:
        self.agents = FakeAgents(agent, version)
        self.runs = FakeRunRepository()
        self.runtime = FakeRuntime()
        self.run_service = FakeRunService()
        self.service = AgentRunService(
            agents=cast(Any, self.agents),
            runs=cast(Any, self.runs),
            runtime=cast(Any, self.runtime),
            run_service=cast(Any, self.run_service),
        )


def _agent() -> Agent:
    return Agent(id="a1", tenant_id="t1", current_version_id="v1")


def _version() -> AgentVersion:
    return AgentVersion(id="v1", agent_id="a1", system_prompt="SYS")


# -- open_run ----------------------------------------------------------------


def test_open_run_creates_running_run_and_links_task() -> None:
    """``open_run`` 建 ``RUNNING`` Run（``task_id`` 已挂）+ 透传 ``user_message``（不执行）。"""
    harness = Harness(_agent(), _version())
    dto = CreateAgentTaskHandler(harness.service).handle(
        CreateAgentTaskCommand(
            tenant_id="t1",
            agent_id="a1",
            conversation_id="c1",
            user_id="u1",
            user_message="hello",
        )
    )
    assert dto.status == RUN_STATUS_RUNNING
    assert dto.task_id == f"task-{dto.id}"
    assert harness.runtime.contexts == []  # 未执行
    assert harness.run_service.created == [(dto.id, None, "hello")]


def test_open_run_missing_agent_raises_not_found() -> None:
    """Agent 不存在 / 跨租户 → ``DomainError(NOT_FOUND)``。"""
    harness = Harness(_agent(), _version())
    with pytest.raises(DomainError) as excinfo:
        CreateAgentTaskHandler(harness.service).handle(
            CreateAgentTaskCommand(tenant_id="t1", agent_id="ghost", conversation_id="c1")
        )
    assert excinfo.value.code == ErrorCode.NOT_FOUND


# -- execute -----------------------------------------------------------------


def test_execute_builds_context_and_syncs_task_terminal() -> None:
    """``execute`` 组上下文（user_message / 预建 run / should_cancel）→ 调 Runtime → 同步 task。"""
    harness = Harness(_agent(), _version())
    dto = CreateAgentTaskHandler(harness.service).handle(
        CreateAgentTaskCommand(
            tenant_id="t1",
            agent_id="a1",
            conversation_id="c1",
            user_id="u1",
            user_message="hello world",
        )
    )
    result = ExecuteAgentHandler(harness.service).handle(ExecuteAgentCommand(run_id=dto.id))

    assert result.status == RUN_STATUS_SUCCESS
    context = harness.runtime.contexts[0]
    assert context.user_message == "hello world"
    assert context.run is not None and context.run.id == dto.id
    assert callable(context.should_cancel)
    assert context.should_cancel() is False
    assert harness.run_service.finished[-1] == (dto.id, RUN_STATUS_SUCCESS, None)


def test_execute_missing_run_raises_not_found() -> None:
    """Run 不存在 → ``DomainError(NOT_FOUND)``。"""
    harness = Harness(_agent(), _version())
    with pytest.raises(DomainError) as excinfo:
        ExecuteAgentHandler(harness.service).handle(ExecuteAgentCommand(run_id="nope"))
    assert excinfo.value.code == ErrorCode.NOT_FOUND


# -- cancel ------------------------------------------------------------------


def test_cancel_sets_cancelled_and_syncs_task() -> None:
    """``cancel`` 置取消信号 + 终态 ``CANCELLED`` + 同步 task 终态。"""
    harness = Harness(_agent(), _version())
    dto = CreateAgentTaskHandler(harness.service).handle(
        CreateAgentTaskCommand(
            tenant_id="t1", agent_id="a1", conversation_id="c1", user_id="u1", user_message="hi"
        )
    )
    cancelled = CancelAgentRunHandler(harness.service).handle(
        CancelAgentRunCommand(run_id=dto.id, tenant_id="t1")
    )
    assert cancelled.status == RUN_STATUS_CANCELLED
    assert cancelled.success is False
    assert cancelled.error_type == "CANCELLED"
    assert harness.run_service.finished[-1] == (dto.id, RUN_STATUS_CANCELLED, None)


def test_cancel_missing_run_raises_not_found() -> None:
    """取消不存在的 Run → ``DomainError(NOT_FOUND)``。"""
    harness = Harness(_agent(), _version())
    with pytest.raises(DomainError) as excinfo:
        CancelAgentRunHandler(harness.service).handle(
            CancelAgentRunCommand(run_id="nope", tenant_id="t1")
        )
    assert excinfo.value.code == ErrorCode.NOT_FOUND


# -- 只读辅助 ----------------------------------------------------------------


def test_get_run_and_status_contract() -> None:
    """``get_run`` / ``status`` 的读契约（含不存在路径）。"""
    harness = Harness(_agent(), _version())
    dto = CreateAgentTaskHandler(harness.service).handle(
        CreateAgentTaskCommand(tenant_id="t1", agent_id="a1", conversation_id="c1")
    )
    assert harness.service.get_run(dto.id).id == dto.id
    assert harness.service.status(dto.id) == RUN_STATUS_RUNNING
    assert harness.service.status("nope") is None
    with pytest.raises(DomainError) as excinfo:
        harness.service.get_run("nope")
    assert excinfo.value.code == ErrorCode.NOT_FOUND
    # 无事件仓储时返回空列表（Router / SSE 回放安全降级）。
    assert harness.service.list_events(dto.id) == []
