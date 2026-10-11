"""SQLAlchemy 方言适配类型。

将数据库方言差异**集中隔离**在本模块，上层与业务模型无需感知：

- :class:`GUID`：UUIDv7 主键/外键的存储类型（PostgreSQL ``UUID`` / 其它 ``CHAR(36)``）。
- :class:`JSONType`：JSON 列（PostgreSQL ``JSONB`` / 其它 ``JSON``）。
- :class:`VectorType`：向量列（PostgreSQL ``vector(d)`` / 其它 ``JSON``；``pgvector`` 延迟导入）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import CHAR, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

__all__ = ["GUID", "JSONType", "VectorType"]

_logger = logging.getLogger("astra_database.types")

#: ``pgvector`` 缺失告警是否已发出（进程级只告警一次，防日志刷屏）。
_pgvector_warned = False


class GUID(TypeDecorator):
    """跨方言的 GUID/UUID 字符串类型。

    - PostgreSQL：原生 ``UUID``（``as_uuid=False``，以字符串读写）；
    - 其它（如 SQLite）：``CHAR(36)``。

    读写时统一以 ``str`` 表示 UUIDv7（由 :func:`astra_core.id.generate_id` 产出）。
    """

    impl = CHAR
    cache_ok = True

    def __init__(self, length: int = 36) -> None:  # noqa: D107
        super().__init__(length)

    def load_dialect_impl(self, dialect: Dialect) -> Any:  # noqa: D102
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:  # noqa: D102
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:  # noqa: D102
        if value is None:
            return None
        return str(value)


class JSONType(TypeDecorator):
    """跨方言的 JSON 列类型。

    - PostgreSQL：``JSONB``；
    - 其它（如 SQLite）：``JSON``。
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:  # noqa: D102
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def _load_pgvector_vector() -> type[Any] | None:
    """函数级延迟导入 ``pgvector.sqlalchemy.Vector``（缺包返回 ``None``）。

    🔴 ``pgvector`` **不写入必需 deps**（W5 裁定 B4 / §7）：仅 PG 部署方需要安装；
    导入失败时由调用方**显式 WARN** 并退化为 JSON（非静默）。
    """
    try:
        from pgvector.sqlalchemy import Vector
    except ImportError:  # pragma: no cover - 取决于部署方是否安装 pgvector
        return None
    return Vector


def _warn_pgvector_missing() -> None:
    """发出一次 ``pgvector`` 缺失告警（进程级去重）。"""
    global _pgvector_warned
    if not _pgvector_warned:
        _pgvector_warned = True
        _logger.warning(
            "pgvector Python 包不可用：VectorType 在 PostgreSQL 上退化为 JSON，"
            "向量语义检索将不可用；请安装 pgvector（见部署说明）。"
        )


class VectorType(TypeDecorator):
    """跨方言的向量列类型（设计 §2.6.2 / C-05；W5 裁定 B4）。

    - PostgreSQL 且 ``pgvector`` Python 包可用：原生 ``vector(dimensions)``；
    - 其它方言 / ``pgvector`` 缺失：退化为 ``JSON`` / ``JSONB``。

    业务 / 模型层**零方言感知**：仅以 ``list[float]`` 读写向量。

    🔴 ``pgvector`` **函数级延迟导入**；缺失时**显式 WARN**（非静默），以保证社区
       SQLite 路径**零额外依赖**可用。
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:  # noqa: D107
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect) -> Any:  # noqa: D102
        if dialect.name == "postgresql":
            vector_cls = _load_pgvector_vector()
            if vector_cls is not None:
                return dialect.type_descriptor(vector_cls(self.dimensions))
            _warn_pgvector_missing()
        return dialect.type_descriptor(JSON())
