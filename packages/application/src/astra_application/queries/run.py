"""Run 查询（Query / QueryHandler）——设计 §2.6 / §2.9（回放 / 续传）。"""

from __future__ import annotations

from dataclasses import dataclass

from astra_core import DomainError, ErrorCode
from astra_domain import AgentEventRepository, AgentRunRepository

from ..dto.run import RunDTO, RunEventDTO
from .base import Query

__all__ = [
    "GetRunQuery",
    "GetRunHandler",
    "ListRunEventsQuery",
    "ListRunEventsHandler",
]


@dataclass
class GetRunQuery(Query):
    """获取单个 Run 详情。"""

    run_id: str = ""


class GetRunHandler:
    """获取 Run 详情查询处理器（经领域 ``AgentRunRepository``）。"""

    def __init__(self, run_repository: AgentRunRepository) -> None:
        self._runs = run_repository

    def handle(self, query: GetRunQuery) -> RunDTO:
        """返回 Run DTO（不存在 → ``NOT_FOUND``）。"""
        run = self._runs.get(query.run_id)
        if run is None:
            raise DomainError(
                "Run 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"run_id": query.run_id},
            )
        return RunDTO.from_entity(run)


@dataclass
class ListRunEventsQuery(Query):
    """列出某 Run 的事件（``seq > last_event_id``，供回放 / ``Last-Event-ID`` 续传）。"""

    run_id: str = ""
    last_event_id: int | None = None


class ListRunEventsHandler:
    """列出 Run 事件查询处理器（经领域 ``AgentEventRepository``）。"""

    def __init__(self, event_repository: AgentEventRepository) -> None:
        self._events = event_repository

    def handle(self, query: ListRunEventsQuery) -> list[RunEventDTO]:
        """返回 ``seq > last_event_id`` 的事件 DTO（``{{seq}}`` 升序，无重复无遗漏）。"""
        return [
            RunEventDTO.from_entity(event)
            for event in self._events.list_after_seq(query.run_id, query.last_event_id)
        ]
