"""Marketplace 包格式往返与静态校验（W8 / T2-42；``I-P2-18`` / ``D13`` / R7 / R12 / R13）。

断言：

- ``export → import → export`` 规范化后 ``diff == 空``（三类资源，含 Unicode / 嵌套）；
- 负向对照：改动字段 → ``diff != 空``（防假绿）；
- 确定性序列化口径（键序升序 / LF / 恰好一个尾换行 / 中文不转义）；
- 版本不可覆盖：同名同版本**异摘要拒绝**（``CONFLICT``）；
- 导入前静态校验：schema + 依赖 + 敏感扫描。
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_plugin.marketplace import (
    PACKAGE_MANIFEST_FILE,
    build_manifest,
    content_digest,
    export_manifest_text,
    export_package,
    import_package,
    inspect,
    load_resource,
    normalize,
    normalize_resource,
    scan_sensitive,
    validate_dependencies,
)
from astra_plugin.marketplace.serialize import canonical_dump, load_file

#: 资源种类 → 资源清单文件名。
_MANIFEST_FILES = {"agent": "agent.yaml", "skill": "skill.yaml", "workflow": "workflow.yaml"}


def _agent_resource() -> dict[str, Any]:
    """Agent 资源样例（含 Unicode / 列表 / 布尔）。"""
    return {
        "name": "my-agent",
        "version": "1.2.0",
        "display_name": "我的智能体 → ✓",
        "description": "多行\n描述 with unicode",
        "model": "gpt-4o-mini",
        "system_prompt": "You are helpful.",
        "tools": ["filesystem", "http"],
        "skills": ["summarize"],
        "knowledge": [],
        "memory": True,
        "permissions": ["tool:filesystem"],
    }


def _skill_resource() -> dict[str, Any]:
    """Skill 资源样例。"""
    return {
        "name": "summarize",
        "version": "0.1.0",
        "display_name": "摘要",
        "category": "text",
        "dependencies": ["tool:filesystem"],
        "requires": ["llm"],
        "instructions": "instructions.md",
    }


def _workflow_resource() -> dict[str, Any]:
    """Workflow 资源样例（含嵌套结构）。"""
    return {
        "name": "flow",
        "version": "2.0.1",
        "entry": "start",
        "nodes": [
            {"id": "start", "type": "llm", "config": {"temperature": 0.2}},
            {"id": "end", "type": "noop", "config": {}},
        ],
        "edges": [{"from": "start", "to": "end"}],
        "inputs": {"topic": "string"},
        "variables": {"limit": 3},
    }


_SAMPLES: list[tuple[str, dict[str, Any]]] = [
    ("agent", _agent_resource()),
    ("skill", _skill_resource()),
    ("workflow", _workflow_resource()),
]


def _agent_resource_with_nulls() -> dict[str, Any]:
    """Agent 样例（含**显式 null**：``model`` / ``display_name`` / ``tools``）。"""
    return {
        "name": "null-agent",
        "version": "1.0.0",
        "model": None,
        "display_name": None,
        "tools": None,
    }


def _skill_resource_with_null_entry() -> dict[str, Any]:
    """Skill 样例（``entry`` 缺省非必填且 default 为 None → 显式 null 应**省略**）。"""
    return {
        "name": "null-skill",
        "version": "1.0.0",
        "entry": None,
        "instructions": None,
    }


def _workflow_resource_with_nulls() -> dict[str, Any]:
    """Workflow 样例（含**显式 null**：``nodes`` / ``edges`` / ``inputs``）。"""
    return {
        "name": "null-flow",
        "version": "1.0.0",
        "nodes": None,
        "edges": None,
        "inputs": None,
    }


#: 显式 null 样例（回归 QA 第 1 轮发现的「null 往返非对称」缺陷）。
_NULL_SAMPLES: list[tuple[str, dict[str, Any]]] = [
    ("agent", _agent_resource_with_nulls()),
    ("skill", _skill_resource_with_null_entry()),
    ("workflow", _workflow_resource_with_nulls()),
]

_ALL_SAMPLES: list[tuple[str, dict[str, Any]]] = [*_SAMPLES, *_NULL_SAMPLES]


def _diff(left: str, right: str) -> list[str]:
    """返回两段文本的逐行差异（规范化后比较）。"""
    return list(difflib.unified_diff(left.splitlines(), right.splitlines(), lineterm=""))


def _write_package(
    root: Path,
    *,
    kind: str,
    resource: Mapping[str, Any],
    core_compat: str = ">=0.3.0,<0.5.0",
) -> None:
    """把资源落成磁盘包目录（``astra-package.yaml`` + 资源清单，规范化）。"""
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


# -- 往返等价（I-P2-18 / D13） -------------------------------------------------


@pytest.mark.parametrize(("kind", "resource"), _SAMPLES)
def test_export_import_export_is_diff_free(kind: str, resource: dict[str, Any]) -> None:
    """``export → import → export`` 规范化后 ``diff == 空``（且字节相同）。"""
    export_1 = export_package(resource, kind=kind)
    imported = load_resource(export_1, kind=kind)  # import_
    export_2 = export_package(imported, kind=kind)

    assert _diff(normalize(export_1), normalize(export_2)) == []
    # 更强：经同一规范化出口，两次导出**字节一致**。
    assert export_1 == export_2
    # 规范化幂等。
    assert normalize(export_1) == normalize(normalize(export_1))


@pytest.mark.parametrize(("kind", "resource"), _SAMPLES)
def test_field_change_produces_diff(kind: str, resource: dict[str, Any]) -> None:
    """负向对照：改动一处字段 → ``diff != 空``（防假绿）。"""
    export_1 = export_package(resource, kind=kind)
    mutated = dict(resource)
    mutated["version"] = "9.9.9"
    export_2 = export_package(mutated, kind=kind)
    assert _diff(normalize(export_1), normalize(export_2)) != []


# -- 显式 null 往返对称（回归 QA 第 1 轮：I-P2-18 / D13） ----------------------


@pytest.mark.parametrize(("kind", "resource"), _NULL_SAMPLES)
def test_explicit_null_export_import_export_is_diff_free_and_byte_identical(
    kind: str, resource: dict[str, Any]
) -> None:
    """含**显式 null** 的资源：``export → import → export`` 规范 diff==空 **且字节一致**。

    回归缺陷：曾「present-null 丢弃」与「absent 补 default」两条分支不一致，导致
    ``export_1``（丢键）≠ ``export_2``（补默认值）。
    """
    export_1 = export_package(resource, kind=kind)
    imported = load_resource(export_1, kind=kind)  # import_
    export_2 = export_package(imported, kind=kind)

    assert _diff(normalize(export_1), normalize(export_2)) == []
    assert export_1 == export_2


@pytest.mark.parametrize(("kind", "resource"), _ALL_SAMPLES)
def test_normalize_is_idempotent(kind: str, resource: dict[str, Any]) -> None:
    """``normalize(normalize(x)) == normalize(x)`` 恒成立（含 null / 默认值样例）。"""
    once = normalize_resource(kind, resource)
    assert normalize_resource(kind, once) == once


def test_explicit_null_equals_absent_after_normalize() -> None:
    """显式 ``null`` 与「缺席」归一到**同一**规范形（非必填 + default 非 None → 物化默认）。"""
    with_null = normalize_resource("agent", {"name": "a-agent", "version": "1.0.0", "model": None})
    without = normalize_resource("agent", {"name": "a-agent", "version": "1.0.0"})
    assert with_null == without
    assert with_null["model"] == ""


def test_explicit_null_omitted_when_default_is_none() -> None:
    """非必填 + ``default is None``（如 skill ``entry``）→ 显式 null **省略**该键。"""
    normalized = normalize_resource("skill", {"name": "a-skill", "version": "1.0.0", "entry": None})
    assert "entry" not in normalized


def test_raw_yaml_explicit_null_round_trip_is_stable() -> None:
    """裸 YAML 显式 null（``model:`` 空值）→ 规范化后往返字节稳定。"""
    raw = "name: null-agent\nversion: 1.0.0\nmodel:\n"
    export_1 = export_package(load_resource(raw, kind="agent"), kind="agent")
    export_2 = export_package(load_resource(export_1, kind="agent"), kind="agent")
    assert export_1 == export_2
    assert "model: ''" in export_1


@pytest.mark.parametrize(("kind", "resource"), _ALL_SAMPLES)
def test_content_digest_is_stable_across_import_export(kind: str, resource: dict[str, Any]) -> None:
    """``content_digest`` 在 import↔export 间稳定（同名同版本幂等判定基石）。"""
    digest_before = content_digest(normalize_resource(kind, resource))
    export_1 = export_package(resource, kind=kind)
    reimported = load_resource(export_1, kind=kind)
    digest_after = content_digest(normalize_resource(kind, reimported))
    assert digest_before == digest_after


# -- 确定性序列化口径（R7） ----------------------------------------------------


def test_canonical_dump_key_order_lf_and_single_trailing_newline() -> None:
    """键序升序 / LF / 恰好一个尾换行 / 中文不转义。"""
    text = canonical_dump({"b": 1, "a": 2, "中文": "值"})
    assert text == "a: 2\nb: 1\n中文: 值\n"
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\r" not in text
    assert "我的智能体" in canonical_dump({"title": "我的智能体"})


def test_export_is_deterministic_across_calls() -> None:
    """同一输入多次导出字节一致（跨运行稳定）。"""
    first = export_package(_workflow_resource(), kind="workflow")
    second = export_package(_workflow_resource(), kind="workflow")
    assert first == second


# -- 版本不可覆盖 / 同名同版本异摘要拒绝（R13） --------------------------------


def test_import_rejects_same_name_version_different_digest(tmp_path: Path) -> None:
    """同名同版本**异摘要** → ``CONFLICT``（拒绝，不产生半成品）。"""
    base = _skill_resource()
    changed = dict(base)
    changed["display_name"] = "改名了"

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _write_package(dir_a, kind="skill", resource=base)
    _write_package(dir_b, kind="skill", resource=changed)

    imported = import_package(dir_a, core_version="0.4.0")
    known = {imported.manifest.identity: imported.content_digest}

    # 同摘要 → 通过（等价于幂等导入）。
    same = import_package(dir_a, core_version="0.4.0", known_digests=known)
    assert same.content_digest == imported.content_digest

    # 异摘要 → 拒绝。
    with pytest.raises(DomainError) as excinfo:
        import_package(dir_b, core_version="0.4.0", known_digests=known)
    assert excinfo.value.code == ErrorCode.CONFLICT


def test_import_rejects_incompatible_core_compat(tmp_path: Path) -> None:
    """``core_compat`` 越界 → ``VALIDATION_ERROR``。"""
    directory = tmp_path / "pkg"
    _write_package(directory, kind="agent", resource=_agent_resource())
    with pytest.raises(DomainError) as excinfo:
        import_package(directory, core_version="0.2.0")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


# -- 导入前静态校验（schema + 依赖 + 敏感） ------------------------------------


def test_load_resource_requires_schema_fields() -> None:
    """缺必填字段 → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError) as excinfo:
        load_resource("version: 1.0.0\n", kind="skill")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_validate_dependencies_rejects_blank() -> None:
    """依赖清单含空项 → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError) as excinfo:
        validate_dependencies(("tool:filesystem", "  "))
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_scan_sensitive_detects_token_prefix_and_high_entropy() -> None:
    """敏感扫描：命中 token 前缀 / 高熵串 / 敏感键名明文。"""
    with pytest.raises(DomainError) as excinfo:
        scan_sensitive({"system_prompt": "token=sk-" + "A" * 24})
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR

    with pytest.raises(DomainError):
        scan_sensitive({"api_key": "qZ8vN2mK9pL4xR7tY1wS6bC3dF0gH5j"})

    with pytest.raises(DomainError):
        scan_sensitive({"metadata": {"secret": "aB3dE6gH9jK2mN5p"}})


def test_scan_sensitive_ignores_placeholder_and_plain() -> None:
    """占位符 / 普通文本 / 版本号不误报。"""
    scan_sensitive({"api_key": "change-me", "description": "一个正常的描述文本 with spaces"})
    scan_sensitive({"version": "1.2.0", "name": "my-agent"})


def test_scan_sensitive_error_does_not_leak_plaintext() -> None:
    """错误 data **不含**原文明文（仅路径与原因）。"""
    secret = "sk-" + "B" * 24
    with pytest.raises(DomainError) as excinfo:
        scan_sensitive({"token": secret})
    assert secret not in str(excinfo.value.data)


def test_load_file_rejects_non_utf8(tmp_path: Path) -> None:
    """非 UTF-8 文件 → ``VALIDATION_ERROR``（不抛裸 ``UnicodeDecodeError``）。"""
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"\xff\xfe\x00not-utf8")
    with pytest.raises(DomainError) as excinfo:
        load_file(bad)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_import_rejects_non_utf8_resource_file(tmp_path: Path) -> None:
    """包内资源清单非 UTF-8 → ``VALIDATION_ERROR``（不产生半成品）。"""
    directory = tmp_path / "pkg"
    _write_package(directory, kind="agent", resource=_agent_resource())
    (directory / "agent.yaml").write_bytes(b"\xff\xfe\x00broken")
    with pytest.raises(DomainError) as excinfo:
        import_package(directory, core_version="0.4.0")
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_scan_sensitive_rejects_excessive_nesting() -> None:
    """超深嵌套（> 上限）→ ``VALIDATION_ERROR``（不抛裸 ``RecursionError``）。"""
    root: dict[str, Any] = {}
    cursor = root
    for _ in range(500):
        child: dict[str, Any] = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(DomainError) as excinfo:
        scan_sensitive(root)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


# -- 安装前元数据（inspect） ---------------------------------------------------


def test_inspect_reports_metadata_and_signature_absent(tmp_path: Path) -> None:
    """``inspect`` 返回作者 / 版本 / 兼容 / 依赖 / 摘要 / 签名有无（R11）。"""
    directory = tmp_path / "pkg"
    _write_package(directory, kind="agent", resource=_agent_resource())
    manifest_text = (directory / PACKAGE_MANIFEST_FILE).read_text(encoding="utf-8")
    inspection = inspect(manifest_text, core_version="0.4.0")
    assert inspection.valid
    assert inspection.kind == "agent"
    assert inspection.name == "my-agent"
    assert inspection.version == "1.2.0"
    assert inspection.core_compatible
    assert inspection.signature_present is False
