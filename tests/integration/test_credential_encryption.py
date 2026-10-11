"""凭证加密集成测试（加密入库往返 + 明文不落库扫描）——设计 §3-#10。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from astra_database import Base, create_session_factory
from astra_database.models.credential import Credential
from astra_security import AesGcmCipher

_PLAINTEXT = "sk-super-secret-api-key-0001"


@pytest.fixture()
def context(tmp_path: Path):
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    db_file = tmp_path / "credential_encryption.db"
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine), db_file, engine
    engine.dispose()


def test_encrypted_roundtrip_and_no_plaintext(context) -> None:
    session_factory, db_file, _engine = context
    cipher = AesGcmCipher.from_secret("test-master-secret-key-0123456789abcdef")

    encrypted = cipher.encrypt(_PLAINTEXT)
    assert _PLAINTEXT not in encrypted

    with session_factory() as session:
        row = Credential(
            tenant_id="t1",
            provider="openai",
            key_type="api_key",
            encrypted_value=encrypted,
        )
        session.add(row)
        session.commit()
        credential_id = row.id

    with session_factory() as session:
        stored = session.get(Credential, credential_id)
        assert stored is not None
        assert stored.encrypted_value == encrypted
        assert _PLAINTEXT not in stored.encrypted_value
        assert cipher.decrypt(stored.encrypted_value) == _PLAINTEXT

    # 明文不落库：直接扫描数据库文件字节。
    assert _PLAINTEXT.encode("utf-8") not in db_file.read_bytes()
