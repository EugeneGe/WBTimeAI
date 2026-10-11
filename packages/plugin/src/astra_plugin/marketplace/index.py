"""静态 ``index.json`` 注册表读写与**幂等 merge**（W8 / T2-43；裁定 R9 / §4）。

- :class:`IndexEntry`：单条包元数据（kind / name / version / core_compat /
  artifact_sha256 / download / author / license）；**只存元数据 / 版本 / 下载位置 /
  摘要**，不含资源正文（设计 §2.13.1 L697）；
- :class:`RegistryIndexData`：``{schema_version, packages[]}``（**按 (kind,name,version)
  升序稳定排序**）；
- :class:`RegistryIndex`：读 / 写（**原子替换**）/ ``find`` / ``merge``（**同版本异摘要
  拒绝、同摘要跳过**，§4.2）、``is_idempotent``。

🔴 零 Web / ORM：仅依赖标准库 + ``astra_core`` + 同子包 ``package`` / ``serialize``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

from astra_plugin.marketplace.package import version_key
from astra_plugin.marketplace.serialize import atomic_write_bytes

__all__ = [
    "INDEX_FILE_NAME",
    "SCHEMA_VERSION",
    "IndexEntry",
    "RegistryIndexData",
    "RegistryIndex",
]

#: 索引文件名（冻结）。
INDEX_FILE_NAME = "index.json"

#: 索引 schema 版本。
SCHEMA_VERSION = 1


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def _conflict_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``CONFLICT``。"""
    return DomainError(message, code=ErrorCode.CONFLICT, data=dict(data))


@dataclass(frozen=True)
class IndexEntry:
    """静态注册表单条包元数据（§4.1）。

    Attributes:
        kind / name / version: 唯一标识。
        artifact_sha256: 归档字节摘要（字符串引用，不 import）。
        download: 归档相对路径（``packs/<kind>/<name>/<version>/<file>``）。
        core_compat: 兼容区间。
        author / license: 元信息。
    """

    kind: str
    name: str
    version: str
    artifact_sha256: str
    download: str
    core_compat: str = ""
    author: str = ""
    license: str = ""

    @property
    def identity(self) -> tuple[str, str, str]:
        """唯一标识 ``(kind, name, version)``。"""
        return (self.kind, self.name, self.version)

    def sort_key(self) -> tuple[str, str, tuple[int, int, int]]:
        """稳定排序键 ``(kind, name, version_key)``。"""
        return (self.kind, self.name, version_key(self.version))

    def validate(self) -> None:
        """校验必填字段非空。

        Raises:
            DomainError: 字段缺失（``VALIDATION_ERROR``）。
        """
        for field_name in ("kind", "name", "version", "artifact_sha256", "download"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise _validation_error("index entry 字段缺失", field=field_name)

    def to_dict(self) -> dict[str, str]:
        """序列化为字典（**稳定键序**由 :meth:`RegistryIndexData.to_json` 保证）。"""
        return {
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "core_compat": self.core_compat,
            "artifact_sha256": self.artifact_sha256,
            "download": self.download,
            "author": self.author,
            "license": self.license,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IndexEntry:
        """由字典构造并校验 :class:`IndexEntry`。

        Raises:
            DomainError: 顶层非映射或字段缺失（``VALIDATION_ERROR``）。
        """
        if not isinstance(data, Mapping):
            raise _validation_error("index entry 须为对象")
        entry = cls(
            kind=str(data.get("kind") or ""),
            name=str(data.get("name") or ""),
            version=str(data.get("version") or ""),
            artifact_sha256=str(data.get("artifact_sha256") or ""),
            download=str(data.get("download") or ""),
            core_compat=str(data.get("core_compat") or ""),
            author=str(data.get("author") or ""),
            license=str(data.get("license") or ""),
        )
        entry.validate()
        return entry


@dataclass(frozen=True)
class RegistryIndexData:
    """静态注册表数据 ``{schema_version, packages[]}``（§4.1）。"""

    packages: tuple[IndexEntry, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def sorted(self) -> RegistryIndexData:
        """返回**按 ``(kind, name, version)`` 升序**重排的副本。"""
        ordered = tuple(sorted(self.packages, key=lambda entry: entry.sort_key()))
        return RegistryIndexData(packages=ordered, schema_version=self.schema_version)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（``packages`` 稳定排序）。"""
        return {
            "schema_version": self.schema_version,
            "packages": [entry.to_dict() for entry in self.sorted().packages],
        }

    def to_json(self) -> str:
        """序列化为 JSON 文本（``sort_keys`` 稳定键序 + LF + 恰好一个尾换行）。"""
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        return text.rstrip("\n") + "\n"

    @classmethod
    def from_json(cls, text: str) -> RegistryIndexData:
        """由 JSON 文本构造（**校验**）。

        Raises:
            DomainError: JSON 非法或结构非法（``VALIDATION_ERROR``）。
        """
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _validation_error("index.json 非法", reason=str(exc)) from exc
        if not isinstance(raw, Mapping):
            raise _validation_error("index.json 顶层须为对象")
        packages_raw = raw.get("packages")
        if packages_raw is None:
            packages_raw = []
        if not isinstance(packages_raw, list):
            raise _validation_error("index.packages 须为列表")
        entries = tuple(IndexEntry.from_dict(item) for item in packages_raw)
        schema_version = int(raw.get("schema_version") or SCHEMA_VERSION)
        return cls(packages=entries, schema_version=schema_version)

    def get(self, kind: str, name: str, version: str) -> IndexEntry | None:
        """按 ``(kind, name, version)`` 查找条目。"""
        target = (kind, name, version)
        for entry in self.packages:
            if entry.identity == target:
                return entry
        return None

    def with_entry(self, entry: IndexEntry) -> RegistryIndexData:
        """追加条目并稳定重排（不落盘）。"""
        return RegistryIndexData(
            packages=(*self.packages, entry), schema_version=self.schema_version
        ).sorted()


class RegistryIndex:
    """静态 ``index.json`` 读写 + 幂等 merge（§4.2）。"""

    def __init__(self, registry_dir: Path) -> None:
        """构造。

        Args:
            registry_dir: 注册表根目录（``index.json`` 落于此）。
        """
        self._dir = Path(registry_dir)
        self._path = self._dir / INDEX_FILE_NAME

    @property
    def path(self) -> Path:
        """``index.json`` 路径。"""
        return self._path

    def load(self) -> RegistryIndexData:
        """读取索引（不存在 → 空索引）。

        Raises:
            DomainError: 索引非法（``VALIDATION_ERROR``）。
        """
        if not self._path.is_file():
            return RegistryIndexData()
        return RegistryIndexData.from_json(self._path.read_text(encoding="utf-8"))

    def write(self, data: RegistryIndexData) -> None:
        """**原子替换**写入索引（临时文件 + rename；稳定键序）。"""
        atomic_write_bytes(self._path, data.to_json().encode("utf-8"))

    def find(self, kind: str, name: str, version: str) -> IndexEntry | None:
        """查找条目（不存在 → ``None``）。"""
        return self.load().get(kind, name, version)

    @staticmethod
    def is_idempotent(entry: IndexEntry, existing: IndexEntry | None) -> bool:
        """同 ``(kind,name,version)`` 且**摘要相同** → 幂等（应跳过）。"""
        return existing is not None and existing.artifact_sha256 == entry.artifact_sha256

    def merge(self, entry: IndexEntry) -> RegistryIndexData:
        """幂等 merge 单条入口（§4.2 冻结算法）。

        - 命中同 ``(kind,name,version)``：同摘要 → **跳过**（返回原索引，不落盘）；
          异摘要 → ``DomainError(CONFLICT)``（**拒绝，不产生半成品**）；
        - 未命中：追加 + 稳定重排 + **原子替换**写入。

        Returns:
            合并后的 :class:`RegistryIndexData`。

        Raises:
            DomainError: 条目非法（``VALIDATION_ERROR``）或同名同版本异摘要（``CONFLICT``）。
        """
        entry.validate()
        data = self.load()
        existing = data.get(*entry.identity)
        if existing is not None:
            if self.is_idempotent(entry, existing):
                return data
            raise _conflict_error(
                "同名同版本异摘要，拒绝写入索引",
                kind=entry.kind,
                name=entry.name,
                version=entry.version,
            )
        merged = data.with_entry(entry)
        self.write(merged)
        return merged
