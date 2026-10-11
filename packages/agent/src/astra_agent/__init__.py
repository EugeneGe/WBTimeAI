"""Astra AI Agent 组**能力包**（``astra_agent``，W5 / T1-22）。

设计 §2.15.1 Agent 组 / §2.4：

- ``repositories/``：Agent / AgentVersion / AgentTool 的 **SQL 仓储**（实现领域 Protocol）；
- ``mappers.py``：ORM 行 ↔ 领域实体映射；
- ``services/``：Agent 领域服务（创建 / 版本发布 / 工具绑定 / 加载明确版本）；
- ``factory.py``：``build_agent_services(session_factory)``。

🔴 能力包纪律（W5 架构裁定 Q1 = 方案 B）：SQL 仓储留**本包**；Runtime **不 import** 本包。
"""

from __future__ import annotations

from .factory import AgentServices, build_agent_services
from .mappers import (
    agent_to_domain,
    agent_to_orm,
    agent_tool_to_domain,
    agent_tool_to_orm,
    version_to_domain,
    version_to_orm,
)
from .planning import (
    DEFAULT_PLAN_MAX_STEPS,
    SENTENCE_SPLIT_PATTERN,
    SimplePlanner,
    build_simple_planner,
)
from .repositories import (
    SqlAgentRepository,
    SqlAgentToolRepository,
    SqlAgentVersionRepository,
)
from .services import AgentService

__all__ = [
    # RP-05 起步 Planner（W4 / T2-21；落能力包，不落 runtime；W4 暂不接线 → C2-18）
    "SimplePlanner",
    "build_simple_planner",
    "DEFAULT_PLAN_MAX_STEPS",
    "SENTENCE_SPLIT_PATTERN",
    "SqlAgentRepository",
    "SqlAgentVersionRepository",
    "SqlAgentToolRepository",
    "AgentService",
    "AgentServices",
    "build_agent_services",
    "agent_to_domain",
    "agent_to_orm",
    "version_to_domain",
    "version_to_orm",
    "agent_tool_to_domain",
    "agent_tool_to_orm",
]
