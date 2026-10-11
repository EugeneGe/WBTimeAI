"""登录爆破防护单测（连续失败阈值与锁定）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from astra_core import DomainError, ErrorCode
from astra_database import Base, create_session_factory
from astra_security import LoginGuard


@pytest.fixture()
def session_factory(tmp_path: Path):
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    db_file = tmp_path / "login_guard.db"
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def test_locks_after_threshold(session_factory) -> None:
    guard = LoginGuard(session_factory, max_attempts=3, lock_seconds=900)
    guard.register_failure(username="bob")
    guard.register_failure(username="bob")
    assert guard.is_locked("bob") is False
    guard.register_failure(username="bob")
    assert guard.is_locked("bob") is True
    assert guard.consecutive_failures("bob") == 3


def test_assert_not_locked_raises_auth_account_locked(session_factory) -> None:
    guard = LoginGuard(session_factory, max_attempts=2, lock_seconds=900)
    guard.register_failure(username="eve")
    guard.register_failure(username="eve")
    with pytest.raises(DomainError) as excinfo:
        guard.assert_not_locked("eve")
    assert excinfo.value.code is ErrorCode.AUTH_ACCOUNT_LOCKED


def test_success_resets_failure_streak(session_factory) -> None:
    guard = LoginGuard(session_factory, max_attempts=2, lock_seconds=900)
    guard.register_failure(username="carol")
    guard.register_success(username="carol")
    assert guard.consecutive_failures("carol") == 0
    assert guard.is_locked("carol") is False
