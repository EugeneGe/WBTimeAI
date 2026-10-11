"""会话撤销集成测试（登出 / 强退后旧 refresh 失效）——设计 §3-#12。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from astra_core import DomainError, ErrorCode
from astra_database import Base, create_session_factory
from astra_security import SessionService, TokenService


@pytest.fixture()
def session_factory(tmp_path: Path):
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    db_file = tmp_path / "session_revocation.db"
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture()
def service(session_factory) -> SessionService:
    tokens = TokenService(
        "test-secret-key-0123456789abcdef", access_ttl_seconds=900, refresh_ttl_seconds=3600
    )
    return SessionService(session_factory, tokens)


def test_logout_revokes_refresh(service: SessionService) -> None:
    tokens = service.create_session(tenant_id="t1", user_id="u1", device="laptop")
    assert service.authenticate_refresh(tokens.refresh_token) is not None
    service.revoke_session(tokens.session_id)
    with pytest.raises(DomainError) as excinfo:
        service.authenticate_refresh(tokens.refresh_token)
    assert excinfo.value.code is ErrorCode.AUTH_TOKEN_REVOKED


def test_revoke_all_sessions(service: SessionService) -> None:
    first = service.create_session(tenant_id="t1", user_id="u2", device="a")
    second = service.create_session(tenant_id="t1", user_id="u2", device="b")
    assert len(service.list_devices("u2")) == 2
    count = service.revoke_all_sessions("u2")
    assert count >= 2
    for tokens in (first, second):
        with pytest.raises(DomainError) as excinfo:
            service.authenticate_refresh(tokens.refresh_token)
        assert excinfo.value.code is ErrorCode.AUTH_TOKEN_REVOKED


def test_list_devices_returns_metadata(service: SessionService) -> None:
    service.create_session(tenant_id="t1", user_id="u3", device="phone", ip_address="127.0.0.1")
    devices = service.list_devices("u3")
    assert len(devices) == 1
    assert devices[0].device == "phone"
    assert devices[0].ip_address == "127.0.0.1"


def test_access_token_still_decodes(service: SessionService) -> None:
    tokens = service.create_session(tenant_id="t1", user_id="u4")
    claims = service._tokens.decode(tokens.access_token)  # noqa: SLF001 - 测试内部校验
    assert claims.sub == "u4"
