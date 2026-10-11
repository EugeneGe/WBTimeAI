"""Astra AI 文件存储（``astra_storage``）。

- ``base``：``Storage`` Protocol + ``StoredObject``
- ``local``：``LocalFileStorage``（构造不建目录）
- ``placeholder``：``UnsupportedStorage``（server 占位）
- ``factory``：``create_local_file_storage``（模式无关）
"""

from __future__ import annotations

from .base import Storage, StoredObject
from .factory import create_local_file_storage
from .local import LocalFileStorage
from .placeholder import UnsupportedStorage

__all__ = [
    "Storage",
    "StoredObject",
    "LocalFileStorage",
    "UnsupportedStorage",
    "create_local_file_storage",
]
