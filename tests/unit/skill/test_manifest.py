"""``skill.yaml`` schema 单测（W2 / T2-08）。

覆盖：``parse_manifest`` / ``load_skill_package``；``instructions.md`` 定位；
缺 ``name`` / ``version`` → ``VALIDATION_ERROR``；资源目录扫描。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_skill import load_skill_package, parse_manifest


def _write_package(root: Path, *, name: str = "demo-skill", version: str = "1.0.0") -> None:
    """在 ``root`` 下写一个最小 Skill 包。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "skill.yaml").write_text(
        f"name: {name}\nversion: {version}\ndescription: demo skill\n",
        encoding="utf-8",
    )
    (root / "instructions.md").write_text("你是 demo 助手。\n", encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "examples").mkdir(exist_ok=True)
    (root / "examples" / "sample.md").write_text("示例\n", encoding="utf-8")


def test_parse_manifest_ok(tmp_path: Path) -> None:
    """``parse_manifest`` 读取 name / version / description。"""
    _write_package(tmp_path / "demo")
    manifest = parse_manifest(tmp_path / "demo" / "skill.yaml")
    assert manifest.name == "demo-skill"
    assert manifest.version == "1.0.0"
    assert manifest.description == "demo skill"
    assert manifest.display_name == "demo-skill"  # 缺省回退 name


def test_parse_manifest_missing_name(tmp_path: Path) -> None:
    """缺 ``name`` → ``VALIDATION_ERROR``。"""
    target = tmp_path / "skill.yaml"
    target.write_text("version: 1.0.0\n", encoding="utf-8")
    with pytest.raises(DomainError) as excinfo:
        parse_manifest(target)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_parse_manifest_missing_version(tmp_path: Path) -> None:
    """缺 ``version`` → ``VALIDATION_ERROR``。"""
    target = tmp_path / "skill.yaml"
    target.write_text("name: demo-skill\n", encoding="utf-8")
    with pytest.raises(DomainError) as excinfo:
        parse_manifest(target)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_parse_manifest_invalid_name(tmp_path: Path) -> None:
    """非法 ``name``（大写 / 空格）→ ``VALIDATION_ERROR``。"""
    target = tmp_path / "skill.yaml"
    target.write_text("name: DemoSKill\nversion: 1.0.0\n", encoding="utf-8")
    with pytest.raises(DomainError):
        parse_manifest(target)


def test_load_skill_package_reads_instructions_and_scans_resources(tmp_path: Path) -> None:
    """``load_skill_package`` 读取 ``instructions.md`` 并扫描 scripts / examples。"""
    pkg = tmp_path / "demo"
    _write_package(pkg)
    loaded = load_skill_package(pkg, source="workspace")
    assert loaded.instructions.strip() == "你是 demo 助手。"
    assert loaded.source == "workspace"
    kinds = {spec.kind for spec in loaded.resources}
    assert "script" in kinds
    assert "example" in kinds


def test_load_skill_package_missing_dir(tmp_path: Path) -> None:
    """目录不存在 → ``VALIDATION_ERROR``。"""
    with pytest.raises(DomainError) as excinfo:
        load_skill_package(tmp_path / "nope")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
