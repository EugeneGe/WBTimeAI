"""``UnsupportedStorage``（server / S3 占位，抛 ``NotImplementedYetError``）。"""

from __future__ import annotations

from typing import BinaryIO, NoReturn

from astra_core import NotImplementedYetError

from .base import StoredObject

__all__ = ["UnsupportedStorage"]


class UnsupportedStorage:
    """server 模式存储占位（S3 / MinIO / COS 目标）。"""

    def __init__(self, *, feature: str, available_in: str) -> None:
        self.feature = feature
        self.available_in = available_in

    def _raise(self, operation: str) -> NoReturn:
        raise NotImplementedYetError(
            f"存储能力「{self.feature}」尚未实现（目标阶段：{self.available_in}）；"
            f"当前调用：{operation}。请使用 ASTRA_MODE=local 以获得本地文件存储。",
            data={"feature": self.feature, "available_in": self.available_in},
        )

    def put(
        self, key: str, data: bytes | BinaryIO, content_type: str | None = None
    ) -> StoredObject:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("put")

    def get(self, key: str) -> bytes:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("get")

    def open(self, key: str) -> BinaryIO:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("open")

    def delete(self, key: str) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("delete")

    def list(self, prefix: str | None = None) -> list[StoredObject]:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("list")

    def exists(self, key: str) -> bool:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("exists")

    def url(self, key: str) -> str:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("url")
