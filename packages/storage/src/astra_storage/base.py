"""``Storage`` 抽象 + ``StoredObject`` 元数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO, Protocol, runtime_checkable

__all__ = ["StoredObject", "Storage"]


@dataclass
class StoredObject:
    """存储对象元数据。

    Attributes:
        key: 对象键（相对路径风格）。
        size: 字节数。
        content_type: 内容类型（MIME）。
        etag: 内容摘要（SHA-256 十六进制）。
        metadata: 附加元数据。
        created_at: 创建时间（UTC）。
    """

    key: str
    size: int = 0
    content_type: str | None = None
    etag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@runtime_checkable
class Storage(Protocol):
    """文件存储接口。

    演进路径（**接口不变**）：``LocalFileStorage → S3 / MinIO / COS``。
    """

    def put(
        self, key: str, data: bytes | BinaryIO, content_type: str | None = None
    ) -> StoredObject:
        """写入对象并返回其元数据。"""
        ...

    def get(self, key: str) -> bytes:
        """读取对象内容。"""
        ...

    def open(self, key: str) -> BinaryIO:
        """以二进制流打开对象。"""
        ...

    def delete(self, key: str) -> None:
        """删除对象（不存在时幂等）。"""
        ...

    def list(self, prefix: str | None = None) -> list[StoredObject]:
        """列出对象（可按前缀过滤）。"""
        ...

    def exists(self, key: str) -> bool:
        """判断对象是否存在。"""
        ...

    def url(self, key: str) -> str:
        """返回对象访问 URL（本地为 ``file://``）。"""
        ...
