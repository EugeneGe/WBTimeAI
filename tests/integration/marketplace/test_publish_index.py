"""Marketplace 发布与静态注册表（W8 / T2-43；``I-P2-29`` / R3 / R8 / R9 / §4.2）。

断言：

- ``publish`` 产出**可校验的版本化静态注册表**（``index.json`` + ``packs/...`` 归档
  + 旁挂 ``astra-package.yaml``），``artifact_sha256`` 与归档字节一致；
- 同版本异摘要 / ``core_compat`` 越界 / 非法 yaml **均拒绝且不产生半成品**；
- **不上传**托管服务（远程 registry 拒绝）；
- 索引同步**幂等**（重复执行字节一致）；
- 经 **D5** 注册（``astra marketplace publish``），``init/run/doctor`` 未改。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from astra_cli.main import app
from astra_core import DomainError, ErrorCode
from astra_plugin.marketplace import (
    PACKAGE_MANIFEST_FILE,
    RegistryIndex,
    build_manifest,
    export_manifest_text,
    export_package,
    publish_package,
)
from astra_plugin.marketplace.index import INDEX_FILE_NAME, IndexEntry, RegistryIndexData
from astra_plugin.marketplace.package import parse_manifest
from astra_plugin.marketplace.publish import PACKS_DIR
from typer.testing import CliRunner

_MANIFEST_FILES = {"agent": "agent.yaml", "skill": "skill.yaml", "workflow": "workflow.yaml"}


def _agent_resource() -> dict[str, Any]:
    """Agent 资源样例。"""
    return {
        "name": "my-agent",
        "version": "1.2.0",
        "display_name": "我的智能体",
        "model": "gpt-4o-mini",
        "tools": ["filesystem"],
    }


def _write_package(
    root: Path,
    *,
    kind: str = "agent",
    resource: Mapping[str, Any] | None = None,
    core_compat: str = ">=0.3.0,<0.5.0",
) -> Path:
    """把资源落成磁盘包目录（``astra-package.yaml`` + 资源清单，规范化）。"""
    resource = resource if resource is not None else _agent_resource()
    root.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        kind=kind,
        name=str(resource["name"]),
        version=str(resource["version"]),
        manifest_path=_MANIFEST_FILES[kind],
        core_compat=core_compat,
        author="tester",
        license="MIT",
    )
    (root / PACKAGE_MANIFEST_FILE).write_text(
        export_manifest_text(manifest), encoding="utf-8", newline="\n"
    )
    (root / manifest.manifest_path).write_text(
        export_package(resource, kind=kind), encoding="utf-8", newline="\n"
    )
    return root


def _snapshot(registry: Path) -> dict[str, bytes]:
    """注册表全量文件快照（相对路径 → 字节）。"""
    return {
        path.relative_to(registry).as_posix(): path.read_bytes()
        for path in sorted(registry.rglob("*"))
        if path.is_file()
    }


# -- 版本化静态注册表（I-P2-29） ----------------------------------------------


def test_publish_creates_versioned_static_registry(tmp_path: Path) -> None:
    """``publish`` 产出注册表：``index.json`` + 归档 + 旁挂清单。"""
    pkg_dir = _write_package(tmp_path / "pkg")
    registry = tmp_path / "registry"

    summary = publish_package(pkg_dir, registry, core_version="0.4.0")
    assert summary.changed and summary.outcome == "added"

    # index.json 落盘且登记条目。
    index_path = registry / INDEX_FILE_NAME
    assert index_path.is_file()
    data = RegistryIndex(registry).load()
    entry = data.get("agent", "my-agent", "1.2.0")
    assert entry is not None
    assert entry.artifact_sha256 == summary.artifact_sha256
    assert entry.core_compat == ">=0.3.0,<0.5.0"
    assert entry.author == "tester"
    assert entry.license == "MIT"

    # 归档 + 旁挂清单落盘。
    archive_path = registry / summary.download
    assert archive_path.is_file()
    sidecar = registry / PACKS_DIR / "agent" / "my-agent" / "1.2.0" / PACKAGE_MANIFEST_FILE
    assert sidecar.is_file()
    assert summary.download == f"{PACKS_DIR}/agent/my-agent/1.2.0/my-agent-1.2.0.tgz"


def test_artifact_sha256_matches_archive_bytes_and_sidecar(tmp_path: Path) -> None:
    """``artifact_sha256`` == sha256(归档字节) == 旁挂清单摘要（R8）。"""
    pkg_dir = _write_package(tmp_path / "pkg")
    registry = tmp_path / "registry"
    summary = publish_package(pkg_dir, registry, core_version="0.4.0")

    archive_bytes = (registry / summary.download).read_bytes()
    assert hashlib.sha256(archive_bytes).hexdigest() == summary.artifact_sha256

    sidecar = registry / PACKS_DIR / "agent" / "my-agent" / "1.2.0" / PACKAGE_MANIFEST_FILE
    assert parse_manifest(sidecar).artifact_sha256 == summary.artifact_sha256

    entry = RegistryIndex(registry).load().get("agent", "my-agent", "1.2.0")
    assert entry is not None and entry.artifact_sha256 == summary.artifact_sha256


# -- 幂等（R9 / §4.2） --------------------------------------------------------


def test_publish_is_idempotent(tmp_path: Path) -> None:
    """重复 ``publish`` → 幂等跳过，文件与 ``index.json`` **字节一致**。"""
    pkg_dir = _write_package(tmp_path / "pkg")
    registry = tmp_path / "registry"

    first = publish_package(pkg_dir, registry, core_version="0.4.0")
    assert first.changed
    snapshot = _snapshot(registry)

    second = publish_package(pkg_dir, registry, core_version="0.4.0")
    assert second.skipped and second.outcome == "skipped"
    assert second.artifact_sha256 == first.artifact_sha256
    assert _snapshot(registry) == snapshot


def test_index_serialization_is_stable(tmp_path: Path) -> None:
    """``RegistryIndexData`` 序列化**稳定键序**（跨插入序字节一致）。"""
    entry_a = IndexEntry(
        kind="agent", name="b-agent", version="1.0.0", artifact_sha256="a" * 64, download="d"
    )
    entry_b = IndexEntry(
        kind="agent", name="a-agent", version="2.0.0", artifact_sha256="b" * 64, download="d"
    )
    forward = RegistryIndexData(packages=(entry_a, entry_b)).to_json()
    backward = RegistryIndexData(packages=(entry_b, entry_a)).to_json()
    assert forward == backward
    parsed = json.loads(forward)
    assert [item["name"] for item in parsed["packages"]] == ["a-agent", "b-agent"]


# -- 拒绝且不产生半成品（I-P2-29） --------------------------------------------


def test_publish_rejects_same_version_different_digest(tmp_path: Path) -> None:
    """同版本**改内容**再发布 → ``CONFLICT``，目标目录**零新增/零覆盖**。"""
    registry = tmp_path / "registry"
    pkg_dir = _write_package(tmp_path / "pkg")
    publish_package(pkg_dir, registry, core_version="0.4.0")
    snapshot = _snapshot(registry)

    # 改动资源内容（同 name / version），重写包目录资源文件。
    changed = _agent_resource()
    changed["display_name"] = "改名后的智能体"
    (pkg_dir / "agent.yaml").write_text(
        export_package(changed, kind="agent"), encoding="utf-8", newline="\n"
    )

    with pytest.raises(DomainError) as excinfo:
        publish_package(pkg_dir, registry, core_version="0.4.0")
    assert excinfo.value.code == ErrorCode.CONFLICT
    assert _snapshot(registry) == snapshot


def test_publish_rejects_incompatible_core_compat(tmp_path: Path) -> None:
    """``core_compat`` 越界 → ``VALIDATION_ERROR``，且不产生半成品。"""
    registry = tmp_path / "registry"
    pkg_dir = _write_package(tmp_path / "pkg", core_compat=">=0.3.0,<0.5.0")

    with pytest.raises(DomainError) as excinfo:
        publish_package(pkg_dir, registry, core_version="0.9.0")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert not (registry / INDEX_FILE_NAME).exists()


def test_publish_rejects_invalid_yaml(tmp_path: Path) -> None:
    """资源清单非法 YAML → ``VALIDATION_ERROR``，且不产生半成品。"""
    registry = tmp_path / "registry"
    pkg_dir = _write_package(tmp_path / "pkg")
    (pkg_dir / "agent.yaml").write_text("name: [unterminated\n", encoding="utf-8")

    with pytest.raises(DomainError) as excinfo:
        publish_package(pkg_dir, registry, core_version="0.4.0")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert not (registry / INDEX_FILE_NAME).exists()


def test_publish_rejects_non_utf8_resource_manifest(tmp_path: Path) -> None:
    """资源清单**非 UTF-8** → ``VALIDATION_ERROR``（**不抛裸 ``UnicodeDecodeError``**），
    且不产生半成品（W9 / G3 / R13）。

    覆盖 ``publish_package`` 资源清单读取收敛为 ``serialize.read_text`` 的修复：
    非 UTF-8 字节被收敛为 ``DomainError(VALIDATION_ERROR)``，注册表**零新增**。
    """
    registry = tmp_path / "registry"
    pkg_dir = _write_package(tmp_path / "pkg")
    # 写入非法 UTF-8 字节序列（0xFF 0xFE 非法起始字节）作为资源清单。
    (pkg_dir / "agent.yaml").write_bytes(b"\xff\xfe\x00name: bad\n")

    with pytest.raises(DomainError) as excinfo:
        publish_package(pkg_dir, registry, core_version="0.4.0")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    # 不产生半成品：注册表索引 / 版本包目录均未创建。
    assert not (registry / INDEX_FILE_NAME).exists()
    assert not (registry / PACKS_DIR).exists()


def test_publish_rejects_remote_registry(tmp_path: Path) -> None:
    """**不上传**托管服务：远程 registry → ``CONFIGURATION_ERROR``。"""
    pkg_dir = _write_package(tmp_path / "pkg")
    with pytest.raises(DomainError) as excinfo:
        publish_package(pkg_dir, "https://example.com/marketplace", core_version="0.4.0")
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


# -- D5 核心分组注册（R3） ----------------------------------------------------


def test_cli_publish_registered_via_d5(tmp_path: Path) -> None:
    """``astra marketplace publish`` 经 D5 注册可用；``init/run/doctor`` 未改。"""
    pkg_dir = _write_package(tmp_path / "pkg")
    registry = tmp_path / "registry"

    result = CliRunner().invoke(
        app, ["marketplace", "publish", str(pkg_dir), "--registry", str(registry)]
    )
    assert result.exit_code == 0, result.output
    assert "[added]" in result.output
    assert (registry / INDEX_FILE_NAME).is_file()

    help_result = CliRunner().invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in ("init", "run", "doctor", "marketplace"):
        assert command in help_result.output
