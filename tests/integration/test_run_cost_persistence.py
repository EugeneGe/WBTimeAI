"""``agent_run.cost*`` 落库往返 + 价格版本快照集成测试（T1-13，SQLite）。"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from astra_core import generate_id
from astra_database import Base, create_session_factory, session_scope
from astra_database.models.conversation import AgentRun as OrmAgentRun
from astra_domain import CostStatus, PriceItem
from astra_model import (
    CORE_PRICE_VERSION,
    CostCalculator,
    StaticPriceCatalog,
    build_default_price_catalog,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def run_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    engine = create_engine(f"sqlite:///{(tmp_path / 'run.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


def _persist_run(factory: sessionmaker[Session], run_id: str, result) -> None:
    with session_scope(factory) as session:
        session.add(
            OrmAgentRun(
                id=run_id,
                tenant_id="tenant-aaaa",
                agent_id="agent-1",
                agent_version_id="version-1",
                conversation_id="conv-1",
                trigger="user",
                run_mode="INLINE",
                status="SUCCESS",
                token_usage={"prompt_tokens": 1000, "completion_tokens": 500},
                cost=result.cost,
                cost_currency=result.currency,
                cost_price_version=result.price_version,
                cost_estimated=result.estimated,
                cost_breakdown=result.breakdown_dict(),
                cost_status=str(result.status),
            )
        )
        session.flush()


def test_cost_roundtrip(run_session_factory: sessionmaker[Session]) -> None:
    calculator = CostCalculator(build_default_price_catalog())
    result = calculator.calculate(
        provider="openai",
        model="gpt-4o",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
    )
    run_id = generate_id()
    _persist_run(run_session_factory, run_id, result)

    with session_scope(run_session_factory) as session:
        row = session.get(OrmAgentRun, run_id)

    assert row is not None
    assert row.cost == Decimal("0.012500")
    assert row.cost_currency == "USD"
    assert row.cost_price_version == CORE_PRICE_VERSION
    assert row.cost_estimated is False
    assert row.cost_status == CostStatus.PRICED.value
    assert row.cost_breakdown["total"] == "0.012500"
    assert row.cost_breakdown["currency"] == "USD"
    assert len(row.cost_breakdown["items"]) == 1


def test_unpriced_run_persists_null_cost(run_session_factory: sessionmaker[Session]) -> None:
    calculator = CostCalculator(build_default_price_catalog())
    result = calculator.calculate(
        provider="openai", model="not-in-catalog", usage={"prompt_tokens": 10}
    )
    run_id = generate_id()
    _persist_run(run_session_factory, run_id, result)

    with session_scope(run_session_factory) as session:
        row = session.get(OrmAgentRun, run_id)

    assert row is not None
    assert row.cost is None
    assert row.cost_currency is None
    assert row.cost_status == CostStatus.UNPRICED.value


def test_price_version_snapshot_is_immutable(run_session_factory: sessionmaker[Session]) -> None:
    """价目调整不回写历史 Run：历史 Run 保留记录时的价格版本与金额。"""
    calculator = CostCalculator(build_default_price_catalog())
    original = calculator.calculate(
        provider="openai", model="gpt-4o", usage={"prompt_tokens": 1000, "completion_tokens": 500}
    )
    run_id = generate_id()
    _persist_run(run_session_factory, run_id, original)

    # 发布新版本价目（不同单价），复算产生新结果。
    new_catalog = StaticPriceCatalog(
        [
            PriceItem(
                provider="openai",
                model="gpt-4o",
                currency="USD",
                input_price_per_1k=Decimal("0.010"),
                output_price_per_1k=Decimal("0.030"),
                price_version="core-next",
            )
        ]
    )
    recomputed = CostCalculator(new_catalog).calculate(
        provider="openai",
        model="gpt-4o",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        price_version=original.price_version,
    )
    assert recomputed.status is CostStatus.UNPRICED  # 记录版本在新目录中不存在

    with session_scope(run_session_factory) as session:
        row = session.get(OrmAgentRun, run_id)
    assert row is not None
    assert row.cost_price_version == CORE_PRICE_VERSION
    assert row.cost == Decimal("0.012500")
