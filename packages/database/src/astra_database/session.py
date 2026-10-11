"""会话工厂与作用域工具。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

__all__ = ["create_session_factory", "session_scope", "SessionLocal"]


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """基于引擎创建会话工厂。

    Args:
        engine: SQLAlchemy 引擎。

    Returns:
        绑定到 ``engine`` 的 ``sessionmaker``。
    """
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


#: 未绑定引擎的会话工厂模板；实际使用请通过
#: :func:`create_session_factory` 或配置其 ``bind``。
SessionLocal: sessionmaker[Session] = sessionmaker(
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session],
    *,
    serialize_writes: bool = False,
) -> Iterator[Session]:
    """提供事务性会话作用域。

    正常退出时 ``commit``，异常时 ``rollback``，并始终 ``close``。

    ``serialize_writes=True`` 时，SQLite 以 ``BEGIN IMMEDIATE`` **先取写锁**（RESERVED），
    使事务内「读-判-写」对其他写者**原子可见**——即设计 §2.7.2 的「等价串行化」；其他方言
    （如 PostgreSQL）**no-op**（调用点自行以行锁表达）。默认 ``False`` → 既有调用点行为
    **逐位不变**（只读 / 非竞争路径不受影响）。

    Args:
        session_factory: 会话工厂。
        serialize_writes: 是否以「串行化写」方式开局（仅 SQLite 生效；默认 ``False``）。

    Yields:
        处于事务中的 :class:`~sqlalchemy.orm.Session`。
    """
    session = session_factory()
    try:
        if serialize_writes:
            _begin_serialized_write(session)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _begin_serialized_write(session: Session) -> None:
    """SQLite：``BEGIN IMMEDIATE`` 先取 RESERVED 写锁（等价串行化）；其他方言 no-op。

    SQLAlchemy 2.x + pysqlite 延迟事务语义下，首个语句前**未**发 ``BEGIN``；故此处可自控
    ``BEGIN IMMEDIATE``。取锁失败（另一写者持锁）时由引擎 **busy-timeout** 等待而非立即
    ``database is locked``（见 :mod:`astra_database.engine`）。
    """
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
