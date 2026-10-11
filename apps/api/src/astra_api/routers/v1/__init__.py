"""``/api/v1`` 路由聚合。

Phase 0 完整子集（auth / users / organizations / workspaces / settings）+
**Phase 1 / W6 新增**（agents / runs / models / tools / conversations / tasks）。
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    agents,
    approvals,
    audit,
    auth,
    conversations,
    evaluation,
    knowledge,
    marketplace,
    mcp,
    memory,
    models,
    organizations,
    permissions,
    plugins,
    projects,
    runs,
    schedules,
    settings,
    skills,
    tasks,
    tools,
    users,
    workflows,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(workspaces.router)
api_router.include_router(settings.router)
# -- Phase 1 / W6（T1-28 / T1-29） ------------------------------------------
api_router.include_router(agents.router)
api_router.include_router(runs.router)
api_router.include_router(models.router)
api_router.include_router(tools.router)
api_router.include_router(conversations.router)
api_router.include_router(tasks.router)
# -- Phase 2 / W3（T2-14 / T2-17） ------------------------------------------
api_router.include_router(permissions.router)
api_router.include_router(skills.router)
api_router.include_router(mcp.router)
api_router.include_router(plugins.router)
api_router.include_router(audit.router)
# -- Phase 2 / W4（T2-25） ---------------------------------------------------
api_router.include_router(workflows.router)
# -- Phase 2 / W6（T2-35 · 前端/API 流）：knowledge / memory ------------------
api_router.include_router(knowledge.router)
api_router.include_router(memory.router)
# -- Phase 2 / W7（T2-39 · Task/Scheduler 增强）：schedules -------------------
api_router.include_router(schedules.router)
# -- Phase 2 / W8（T2-44 · Marketplace 收口）：agent-studio/marketplace ---------
api_router.include_router(marketplace.router)
# -- Phase 2 / W9（T2-47 · Evaluation 最小闭环）：evaluation -------------------
api_router.include_router(evaluation.router)
# -- Phase 2 / W10（T2-49 · 2c API 子集）：projects / approvals ----------------
api_router.include_router(projects.router)
api_router.include_router(approvals.router)

__all__ = ["api_router"]
