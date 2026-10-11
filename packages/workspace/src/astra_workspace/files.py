"""Workspace Files 用例（经 Phase 0 ``Storage`` 抽象；W7 / T2-38）。

Files 用例把工作区相对路径映射为 ``Storage`` 对象键（``workspaces/{workspace_id}/{path}``），
全部读写**经注入的** :class:`~astra_storage.Storage`（``put`` / ``get`` / ``open`` /
``delete`` / ``list`` / ``exists`` / ``url``）——**不直连文件系统**（存储后端可平滑切换
``Local → S3 / MinIO / COS``）。

🔴 ``Storage`` 经**构造注入**（Protocol）；本模块**不 import** ``astra_storage`` 运行时对象
   （仅 ``TYPE_CHECKING`` 引类型），保持能力包零硬依赖（对齐 ``astra_tool`` 先例）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from astra_core import DomainError, ErrorCode

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_storage import Storage, StoredObject

__all__ = ["FileService", "WORKSPACE_KEY_PREFIX"]

#: 工作区文件对象键前缀（`workspaces/{workspace_id}/...`）。
WORKSPACE_KEY_PREFIX = "workspaces"


class FileService:
    """工作区文件用例（对象键按工作区隔离，全部经 ``Storage``）。"""

    def __init__(self, storage: Storage) -> None:
        """构造。

        Args:
            storage: 注入的 ``Storage`` 实现（Protocol）。
        """
        self._storage = storage

    @property
    def storage(self) -> Storage:
        """返回底层 ``Storage``（供组合根 / 测试检视）。"""
        return self._storage

    @staticmethod
    def build_key(workspace_id: str, path: str) -> str:
        """把工作区相对路径映射为存储对象键。

        Args:
            workspace_id: 工作区标识。
            path: 工作区内相对路径（**禁**绝对路径 / ``..`` 逃逸）。

        Returns:
            ``workspaces/{workspace_id}/{path}``。

        Raises:
            DomainError: ``workspace_id`` 或 ``path`` 为空、``path`` 为绝对路径或含 ``..``
                （``VALIDATION_ERROR``）。
        """
        normalized = FileService._normalize(workspace_id, path)
        return f"{WORKSPACE_KEY_PREFIX}/{workspace_id.strip()}/{normalized}"

    @staticmethod
    def _normalize(workspace_id: str, path: str) -> str:
        """校验工作区标识与相对路径（防越界）。"""
        wid = (workspace_id or "").strip()
        rel = (path or "").strip().replace("\\", "/")
        if not wid:
            raise DomainError(
                "工作区标识不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "workspace_id"},
            )
        if not rel:
            raise DomainError(
                "文件路径不能为空", code=ErrorCode.VALIDATION_ERROR, data={"field": "path"}
            )
        if rel.startswith("/"):
            raise DomainError(
                "文件路径不能为绝对路径",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "path", "value": path},
            )
        parts = [segment for segment in rel.split("/") if segment not in ("", ".")]
        if any(segment == ".." for segment in parts):
            raise DomainError(
                "文件路径不得包含 .. 逃逸",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "path", "value": path},
            )
        return "/".join(parts)

    def put(
        self,
        *,
        workspace_id: str,
        path: str,
        data: bytes | BinaryIO,
        content_type: str | None = None,
    ) -> StoredObject:
        """写入工作区文件，返回对象元数据。"""
        key = self.build_key(workspace_id, path)
        return self._storage.put(key, data, content_type)

    def get(self, *, workspace_id: str, path: str) -> bytes:
        """读取工作区文件内容。"""
        return self._storage.get(self.build_key(workspace_id, path))

    def open(self, *, workspace_id: str, path: str) -> BinaryIO:
        """以二进制流打开工作区文件。"""
        return self._storage.open(self.build_key(workspace_id, path))

    def delete(self, *, workspace_id: str, path: str) -> None:
        """删除工作区文件（不存在时幂等）。"""
        self._storage.delete(self.build_key(workspace_id, path))

    def exists(self, *, workspace_id: str, path: str) -> bool:
        """判断工作区文件是否存在。"""
        return self._storage.exists(self.build_key(workspace_id, path))

    def url(self, *, workspace_id: str, path: str) -> str:
        """返回工作区文件的访问 URL。"""
        return self._storage.url(self.build_key(workspace_id, path))

    def list(  # noqa: A003 - 与 Storage 接口语义一致
        self, *, workspace_id: str, prefix: str | None = None
    ) -> list[StoredObject]:
        """列出某工作区下的文件（可按工作区内子前缀过滤）。"""
        base = f"{WORKSPACE_KEY_PREFIX}/{(workspace_id or '').strip()}/"
        if not (workspace_id or "").strip():
            raise DomainError(
                "工作区标识不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "workspace_id"},
            )
        full_prefix = base
        if prefix:
            rel = self._normalize(workspace_id, prefix)
            full_prefix = f"{base}{rel}"
        return self._storage.list(full_prefix)
