"""``LocalFileStorage``（本地文件系统存储）。

- 基目录：``{data_dir}/storage/``（由配置派生）；
- 🔴 **构造时不得创建目录**（仅 :meth:`put` 时按需 ``mkdir(parents=True)``），
  避免测试在开发者家目录产生残留；
- 路径安全校验：拒绝绝对路径与 ``..`` 逃逸，确保写入不越出基目录。
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from astra_core import DomainError, ErrorCode

from .base import StoredObject

__all__ = ["LocalFileStorage"]

_CHUNK = 1024 * 1024


class LocalFileStorage:
    """本地文件系统存储实现。"""

    def __init__(self, base_dir: str | Path) -> None:
        """构造（**不创建目录**）。

        Args:
            base_dir: 存储基目录（可为 ``~`` 展开路径）。
        """
        self._base = Path(base_dir).expanduser().resolve()

    @property
    def base_dir(self) -> Path:
        """存储基目录。"""
        return self._base

    # -- 路径处理 -----------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """将 key 解析为受限于基目录内的绝对路径。

        Raises:
            DomainError: key 为空 / 绝对路径 / 越出基目录时（``VALIDATION_ERROR``）。
        """
        if not key or not key.strip():
            raise DomainError("对象 key 不能为空", code=ErrorCode.VALIDATION_ERROR)
        candidate = Path(key)
        if candidate.is_absolute():
            raise DomainError("对象 key 不能为绝对路径", code=ErrorCode.VALIDATION_ERROR)
        resolved = (self._base / candidate).resolve()
        if resolved != self._base and self._base not in resolved.parents:
            raise DomainError("对象 key 越出存储基目录", code=ErrorCode.VALIDATION_ERROR)
        return resolved

    def _to_key(self, path: Path) -> str:
        return path.relative_to(self._base).as_posix()

    # -- 元数据 -------------------------------------------------------------

    def _build_object(self, path: Path, key: str, metadata: dict | None = None) -> StoredObject:
        stat = path.stat()
        content_type, _ = mimetypes.guess_type(key)
        return StoredObject(
            key=key,
            size=stat.st_size,
            content_type=content_type,
            etag=self._sha256(path),
            metadata=metadata or {},
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # -- Storage 接口 -------------------------------------------------------

    def put(
        self, key: str, data: bytes | BinaryIO, content_type: str | None = None
    ) -> StoredObject:
        """写入对象（按需创建父目录）。"""
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            path.write_bytes(bytes(data))
        else:
            with path.open("wb") as handle:
                shutil.copyfileobj(data, handle)

        obj = self._build_object(path, self._to_key(path))
        if content_type is not None:
            obj.content_type = content_type
        return obj

    def get(self, key: str) -> bytes:
        """读取对象内容。"""
        path = self._resolve(key)
        if not path.is_file():
            raise DomainError(f"对象不存在：{key}", code=ErrorCode.NOT_FOUND)
        return path.read_bytes()

    def open(self, key: str) -> BinaryIO:  # noqa: A003 - 与接口语义一致
        """以二进制流打开对象。"""
        path = self._resolve(key)
        if not path.is_file():
            raise DomainError(f"对象不存在：{key}", code=ErrorCode.NOT_FOUND)
        return path.open("rb")

    def delete(self, key: str) -> None:
        """删除对象（不存在时幂等）。"""
        path = self._resolve(key)
        if path.is_file():
            path.unlink()

    def list(self, prefix: str | None = None) -> list[StoredObject]:
        """列出对象（按前缀过滤）。"""
        if not self._base.is_dir():
            return []
        objects: list[StoredObject] = []
        for path in sorted(self._base.rglob("*")):
            if not path.is_file():
                continue
            key = self._to_key(path)
            if prefix is not None and not key.startswith(prefix):
                continue
            objects.append(self._build_object(path, key))
        return objects

    def exists(self, key: str) -> bool:
        """判断对象是否存在。"""
        return self._resolve(key).is_file()

    def url(self, key: str) -> str:
        """返回本地访问 URL（``file://``）。"""
        return f"file://{self._resolve(key).as_posix()}"
