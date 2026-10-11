"""Astra AI Conversation 组**能力包**（``astra_conversation``，W5 / T1-21）。

设计 §2.15.1 Conversation 组 / §2.6：

- ``repositories/``：Conversation / Message / AgentRun / ToolCall / AgentEvent 的 **SQL 仓储**
  （实现 ``astra_domain`` 领域 Protocol，ORM 仅在此层）；
- ``mappers.py``：ORM 行 ↔ 领域实体映射；
- ``services/``：会话 / 消息 / 事件服务 + Run↔Task 挂靠（T1-26）；
- ``factory.py``：``build_conversation_services(session_factory)``。

🔴 能力包纪律（W5 架构裁定 Q1 = 方案 B）：承载业务聚合持久化，SQL 仓储留**本包**；
   不承载被 Runtime 跨层消费的抽象 Protocol（Runtime **不 import** 本包）。
"""

from __future__ import annotations

from .factory import ConversationServices, build_conversation_services
from .mappers import (
    conversation_to_domain,
    conversation_to_orm,
    event_to_domain,
    event_to_orm,
    message_to_domain,
    message_to_orm,
    run_to_domain,
    run_to_orm,
    tool_call_to_domain,
    tool_call_to_orm,
)
from .repositories import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlConversationRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from .services import AGENT_RUN_TASK_TYPE, ConversationService, RunService

__all__ = [
    "SqlConversationRepository",
    "SqlAgentRunRepository",
    "SqlMessageRepository",
    "SqlToolCallRepository",
    "SqlAgentEventRepository",
    "ConversationService",
    "RunService",
    "AGENT_RUN_TASK_TYPE",
    "ConversationServices",
    "build_conversation_services",
    "conversation_to_domain",
    "conversation_to_orm",
    "run_to_domain",
    "run_to_orm",
    "message_to_domain",
    "message_to_orm",
    "tool_call_to_domain",
    "tool_call_to_orm",
    "event_to_domain",
    "event_to_orm",
]
