"""storage 组合工厂（**模式无关**）。"""

from __future__ import annotations

from pathlib import Path

from .local import LocalFileStorage

__all__ = ["create_local_file_storage"]


def create_local_file_storage(base_dir: str | Path) -> LocalFileStorage:
    """创建本地文件存储（模式无关；**不创建目录**）。"""
    return LocalFileStorage(base_dir)
