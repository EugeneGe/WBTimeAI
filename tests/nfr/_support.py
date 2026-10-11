"""``tests/nfr`` 共享辅助（W8 / T1-38）。

不含 ``test_*`` 用例的纯工具/构造，供各 NFR 测试模块复用：百分位、PG 门控、最小父图种子。
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session, sessionmaker

#: 单 Run 批量写入事件条数（设计 §3-#28：1000）。
EVENT_COUNT = 1000

#: PG 门控（对齐 ``test_postgres_smoke.py``；A17：本机无 PG 运行时 → 标注阻塞）。
PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"

#: NFR 强门禁开关（防假绿，对齐项目 `ASTRA_TEST_REQUIRE_*` 惯例）：
#: 置 ``1`` 时**严格执行**基线断言（超基线即红）；未置时仅**测量 + 报告**（软失败）。
#: 由 ``.github/workflows/nfr.yml``（nightly）设置。
REQUIRE_NFR = os.environ.get("ASTRA_TEST_REQUIRE_NFR") == "1"


def enforce_nfr(label: str, measured_ms: float, baseline_ms: int) -> None:
    """打印 NFR 报告行；在 ``ASTRA_TEST_REQUIRE_NFR=1`` 时**严格**断言未超基线。

    Args:
        label: 基线标签（用例 ID + 指标）。
        measured_ms: 实测值（毫秒）。
        baseline_ms: 基线阈值（毫秒）。

    Raises:
        AssertionError: 强门禁开启且超基线（超基线即红，nightly 不设 ``continue-on-error``）。
    """
    verdict = "PASS" if measured_ms < baseline_ms else "OVER-BASELINE"
    mode = "strict/nightly" if REQUIRE_NFR else "report/local"
    print(
        f"[NFR {label}] measured={measured_ms:.1f}ms baseline={baseline_ms}ms "
        f"mode={mode} -> {verdict}"
    )
    if REQUIRE_NFR:
        assert measured_ms < baseline_ms, (
            f"[NFR {label}] {measured_ms:.1f}ms 超基线 {baseline_ms}ms"
            "（ASTRA_TEST_REQUIRE_NFR=1）"
        )


def percentile(values: Sequence[float], rank: float) -> float:
    """最近秩（nearest-rank）百分位；``rank`` ∈ [0, 100]。空序列报错。"""
    if not values:
        raise ValueError("percentile 需要非空序列")
    ordered = sorted(values)
    if rank <= 0:
        return ordered[0]
    if rank >= 100:
        return ordered[-1]
    index = int(round((rank / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def bulk_write_1000(factory: sessionmaker[Session], run_id: str) -> float:
    """向 ``run_id`` **批量**写入 1000 条 ``agent_event``，返回耗时（毫秒）。

    断言写入后 ``seq`` 连续唯一（``1..1000``）——批量写入（非逐条）+ 无丢失 / 无重复。

    Args:
        factory: 目标会话工厂。
        run_id: 目标 Run 标识。

    Returns:
        批量写入耗时（毫秒）。
    """
    from astra_conversation import SqlAgentEventRepository
    from astra_domain import AgentEvent

    repo = SqlAgentEventRepository(factory)
    events = [
        AgentEvent(run_id=run_id, type="agent.thinking", payload={"i": i})
        for i in range(EVENT_COUNT)
    ]
    start = time.perf_counter()
    repo.add_many(events)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    stored = repo.list_by_run(run_id)
    assert len(stored) == EVENT_COUNT, len(stored)
    assert [event.seq for event in stored] == list(range(1, EVENT_COUNT + 1))
    return elapsed_ms


def with_connect_timeout(url: str) -> str:
    """为 PG 连接串注入 ``connect_timeout``（幂等，防探测挂起）。"""
    if not url.startswith(("postgresql", "postgres")):
        return url
    if "connect_timeout" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}connect_timeout=10"


def resolve_pg_url() -> str:
    """返回 PG 连接串；缺失时按门控语义 skip / fail（防假绿）。"""
    if not PG_URL:
        if REQUIRE_PG:
            pytest.fail(
                "ASTRA_TEST_REQUIRE_PG=1 但未设置 ASTRA_TEST_PG_URL —— "
                "PostgreSQL NFR 基线不得被跳过（防假绿）。"
            )
        pytest.skip(
            "未设置 ASTRA_TEST_PG_URL（A17：本机无 PG 运行时）；PG 侧基线经 CI nightly 实跑。"
        )
    return PG_URL


@dataclass(frozen=True)
class ParentGraph:
    """``seed_parent_graph`` 建成的父图**主键集合**（真实 UUID，供 PG 用例引用）。

    🔴 供 PG 用例构造 ``AgentRun`` 时**复用已 seed 的父行主键**——禁止各自造一套；
    非 UUID 占位串（如 ``"a1"`` / ``"v1"`` / ``""``）在真实 PG 的 ``uuid`` 列上会
    ``psycopg.errors.InvalidTextRepresentation``（SQLite 的 GUID 以文本存储而被容忍）。

    Attributes:
        tenant_id / user_id / workspace_id / agent_id / agent_version_id / conversation_id:
            已 seed 的父行主键（均为 ``astra_core.generate_id()`` 生成的真实 UUID）。
        run_id: ``create_run=True`` 时新建的 ``agent_run`` 主键，否则 ``None``。
    """

    tenant_id: str
    user_id: str
    workspace_id: str
    agent_id: str
    agent_version_id: str
    conversation_id: str
    run_id: str | None


def seed_parent_graph(factory: sessionmaker[Session], *, create_run: bool = False) -> ParentGraph:
    """建最小父图（tenant/user/workspace/agent/agent_version/conversation，**FK 完整**）。

    供 **PostgreSQL** 用例使用（PG 强制 FK；SQLite 默认不强制，故 perf 的 SQLite 侧可直接
    建裸 Run）。``create_run=True`` 时额外建一条 ``RUNNING`` 的 ``agent_run``。

    🔴 **分阶段 ``flush``（F3）**：全仓 ORM **零 ``relationship()``**（全裸 FK）；SQLAlchemy
    **2.1.x** 的 unit-of-work 对**无 relationship 的裸 FK** **不再**按表依赖排序 INSERT，
    同一 flush 内可能先发子表 → PG 上 ``IntegrityError ForeignKeyViolation``。故按 **FK 拓扑
    分阶段 ``session.flush()``**（``tenant → user → workspace → agent → agent_version →
    conversation → [run]``）显式钉死 INSERT 顺序；末尾 ``commit()`` 保留事务原子性。

    Args:
        factory: 目标会话工厂（PG）。
        create_run: 是否同时建一条 ``agent_run``。

    Returns:
        :class:`ParentGraph`（含全部父行主键 + 可选 ``run_id``）。
    """
    from astra_common.time import utcnow
    from astra_core import generate_id
    from astra_database.models.agent import Agent as OrmAgent
    from astra_database.models.agent import AgentVersion as OrmAgentVersion
    from astra_database.models.conversation import AgentRun as OrmAgentRun
    from astra_database.models.conversation import Conversation as OrmConversation
    from astra_database.models.identity import Tenant as OrmTenant
    from astra_database.models.identity import User as OrmUser
    from astra_database.models.workspace import Workspace as OrmWorkspace

    tenant_id, user_id, workspace_id = generate_id(), generate_id(), generate_id()
    agent_id, version_id, conversation_id = generate_id(), generate_id(), generate_id()
    run_id: str | None = None
    with factory() as session:
        # 阶段 1：tenant（无 FK 依赖）先行——显式 flush 钉死 INSERT 顺序。
        session.add(OrmTenant(id=tenant_id, slug=f"nfr-{tenant_id[:8]}", name="NFR"))
        session.flush()
        # 阶段 2：user 依赖 tenant。
        session.add(
            OrmUser(
                id=user_id,
                tenant_id=tenant_id,
                username=f"nfr-{user_id[:8]}",
                email=f"{user_id[:8]}@example.com",
                password_hash="x",
            )
        )
        session.flush()
        # 阶段 3：workspace 依赖 tenant / user。
        session.add(
            OrmWorkspace(
                id=workspace_id,
                tenant_id=tenant_id,
                owner_id=user_id,
                name="NFR WS",
                workspace_type="personal",
            )
        )
        session.flush()
        # 阶段 4：agent 依赖 tenant / workspace / user。
        session.add(
            OrmAgent(
                id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name="NFR Agent",
                type="PRIMARY",
                status="ACTIVE",
                created_by=user_id,
            )
        )
        session.flush()
        # 阶段 5：agent_version 依赖 agent / user。
        session.add(
            OrmAgentVersion(
                id=version_id,
                agent_id=agent_id,
                version="1",
                system_prompt="x",
                model_config={"provider": "nfr", "model": "nfr-1"},
                runtime_config={},
                status="PUBLISHED",
                created_by=user_id,
            )
        )
        session.flush()
        # 阶段 6：conversation 依赖 tenant / workspace / agent / user。
        session.add(
            OrmConversation(
                id=conversation_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                title="nfr",
                status="ACTIVE",
            )
        )
        session.flush()
        if create_run:
            from astra_domain import (
                COST_STATUS_UNPRICED,
                RUN_MODE_INLINE,
                RUN_STATUS_RUNNING,
                RUN_TRIGGER_USER,
            )

            run_id = generate_id()
            # 阶段 7：agent_run 依赖 tenant / agent / agent_version / conversation / user。
            session.add(
                OrmAgentRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    agent_version_id=version_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    status=RUN_STATUS_RUNNING,
                    run_mode=RUN_MODE_INLINE,
                    trigger=RUN_TRIGGER_USER,
                    cost_status=COST_STATUS_UNPRICED,
                    started_at=utcnow(),
                )
            )
            session.flush()
        session.commit()
    return ParentGraph(
        tenant_id=tenant_id,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_version_id=version_id,
        conversation_id=conversation_id,
        run_id=run_id,
    )
