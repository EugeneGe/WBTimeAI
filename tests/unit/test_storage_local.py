"""``LocalFileStorage`` 往返与元数据单测（含「构造不建目录」约束）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_core import DomainError
from astra_storage import LocalFileStorage, create_local_file_storage


def test_constructor_does_not_create_dir(tmp_path: Path) -> None:
    base = tmp_path / "not-created-yet" / "storage"
    LocalFileStorage(base)
    assert not base.exists()


def test_put_get_delete_list_roundtrip(tmp_path: Path) -> None:
    storage = create_local_file_storage(tmp_path / "storage")
    obj = storage.put("docs/a.txt", b"hello", content_type="text/plain")
    assert obj.key == "docs/a.txt"
    assert obj.size == 5
    assert obj.content_type == "text/plain"
    assert obj.etag
    assert obj.created_at is not None

    assert storage.exists("docs/a.txt") is True
    assert storage.get("docs/a.txt") == b"hello"
    assert [o.key for o in storage.list()] == ["docs/a.txt"]
    assert [o.key for o in storage.list(prefix="docs/")] == ["docs/a.txt"]
    assert [o.key for o in storage.list(prefix="other/")] == []

    storage.delete("docs/a.txt")
    assert storage.exists("docs/a.txt") is False


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "s")
    storage.delete("missing.txt")  # 不应抛错


def test_get_missing_raises(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "s")
    with pytest.raises(DomainError):
        storage.get("missing.txt")


def test_url_is_file_scheme(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "s")
    storage.put("x.txt", b"x")
    assert storage.url("x.txt").startswith("file://")


def test_rejects_path_escape(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "s")
    with pytest.raises(DomainError):
        storage.put("../escape.txt", b"x")
    with pytest.raises(DomainError):
        storage.put("/abs/path.txt", b"x")


def test_open_stream(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "s")
    storage.put("stream.bin", b"abc")
    with storage.open("stream.bin") as handle:
        assert handle.read() == b"abc"
