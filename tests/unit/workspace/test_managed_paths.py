"""受管工作区路径单测（R1 / T2-55；设计 §2.8.1 / §2.19；验收 ``I-P2-36`` / ``N-P2-10``）。

覆盖：

- **UUID 派生布局**：``projects/<id>/repo`` 与 ``executions/<id>/attempt-<n>``；
- **路径穿越 / 绝对路径 / 分隔符**全拒；
- **符号链接逃逸**全拒（canonical containment）；
- **跨 Project 隔离**（不同 Project 目录互不嵌套、互不覆盖）；
- **不透明 checkout_ref**（不含宿主绝对路径，可服务端还原）；
- **ProjectStorage 生命周期**与**清理守卫**（禁止删 Project 根 / 配置根）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_workspace import (
    ManagedWorkspacePaths,
    ProjectStorage,
    is_safe_path_segment,
    resolve_workspace_root,
)

# -- 安全片段白名单 ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["proj-1", "018f2a", "a.b_c", "ABC123", "a" * 40],
)
def test_safe_segment_accepts_single_identifiers(value: str) -> None:
    assert is_safe_path_segment(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "../etc",
        "a/b",
        "a\\b",
        "/etc/passwd",
        "C:\\Windows",
        "..\\..",
        "-leading-dash",
        ".hidden",
        "a\x00b",
        None,
        123,
    ],
)
def test_safe_segment_rejects_traversal_and_absolute(value: object) -> None:
    assert is_safe_path_segment(value) is False


def test_resolve_workspace_root_rejects_empty() -> None:
    with pytest.raises(DomainError) as excinfo:
        resolve_workspace_root("   ")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# -- UUID 派生布局 -----------------------------------------------------------


def test_uuid_derived_layout(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    project_repo = paths.project_repo_dir("11111111-1111-1111-1111-111111111111")
    attempt = paths.attempt_dir("22222222-2222-2222-2222-222222222222", 1)
    # 位于配置根内，段名与结构符合设计（projects/<id>/repo、executions/<id>/attempt-<n>）。
    assert project_repo.is_relative_to(paths.root)
    assert project_repo.parts[-3:] == ("projects", "11111111-1111-1111-1111-111111111111", "repo")
    assert attempt.parts[-2:] == ("22222222-2222-2222-2222-222222222222", "attempt-1")


@pytest.mark.parametrize("bad", ["../evil", "/etc", "a/b", "", ".."])
def test_project_id_must_be_safe_segment(tmp_path: Path, bad: str) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    with pytest.raises(DomainError) as excinfo:
        paths.project_dir(bad)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize("bad_attempt", [-1, 1.5, True, "1"])
def test_attempt_must_be_non_negative_int(tmp_path: Path, bad_attempt: object) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    with pytest.raises(DomainError) as excinfo:
        paths.attempt_dir("exec-1", bad_attempt)  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# -- containment（穿越 / 绝对路径 / 符号链接逃逸） ---------------------------


def test_resolve_within_root_rejects_traversal(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    with pytest.raises(DomainError) as excinfo:
        paths.resolve_within_root("projects", "..", "..", "etc")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_assert_within_root_rejects_absolute_outside(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    outside = (tmp_path.parent / "outside-abs").resolve()
    with pytest.raises(DomainError) as excinfo:
        paths.assert_within_root(outside)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """根内符号链接指向根外 → canonical containment 拒绝。"""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - 平台无符号链接权限
        pytest.skip("当前平台不支持创建符号链接（需开发者模式 / 权限）")

    paths = ManagedWorkspacePaths(root)
    with pytest.raises(DomainError) as excinfo:
        paths.resolve_within_root("escape")
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_symlink_within_root_is_allowed(tmp_path: Path) -> None:
    """根内符号链接仍指向根内 → 放行（证明拒绝是 containment 而非一概拒绝链接）。"""
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    link = root / "alias"
    try:
        os.symlink(root / "real", link, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover
        pytest.skip("当前平台不支持创建符号链接")

    paths = ManagedWorkspacePaths(root)
    resolved = paths.resolve_within_root("alias")
    assert resolved.is_relative_to(paths.root)


# -- 跨 Project 隔离 ---------------------------------------------------------


def test_cross_project_isolation(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    p1 = paths.project_repo_dir("project-a")
    p2 = paths.project_repo_dir("project-b")
    assert p1 != p2
    assert not p1.is_relative_to(p2)
    assert not p2.is_relative_to(p1)
    # 跨 Project 引用（把 b 挂到 a 下）不成立：a 的仓库目录不是 b 的前缀。
    assert not (p1 / ".." / "project-b").resolve().is_relative_to(p1)


# -- 不透明 checkout_ref ------------------------------------------------------


def test_checkout_ref_is_opaque_and_roundtrips(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    ref = paths.checkout_ref("exec-42", 3)
    # 不含宿主绝对路径（不透明）。
    assert str(tmp_path) not in ref
    assert os.sep not in ref
    assert "exec-42" not in ref  # 原值不直接出现
    execution_id, attempt = paths.parse_checkout_ref(ref)
    assert (execution_id, attempt) == ("exec-42", 3)
    assert paths.path_for_checkout_ref(ref) == paths.attempt_dir("exec-42", 3)


def test_checkout_ref_unique_per_attempt(tmp_path: Path) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    assert paths.checkout_ref("exec-1", 1) != paths.checkout_ref("exec-1", 2)
    assert paths.checkout_ref("exec-1", 1) != paths.checkout_ref("exec-2", 1)


@pytest.mark.parametrize("bad_ref", ["", "nope", "wr_!!!!", "wr_"])
def test_parse_checkout_ref_rejects_invalid(tmp_path: Path, bad_ref: str) -> None:
    paths = ManagedWorkspacePaths(tmp_path)
    with pytest.raises(DomainError) as excinfo:
        paths.parse_checkout_ref(bad_ref)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# -- ProjectStorage 生命周期与清理守卫 --------------------------------------


def test_project_storage_ensure_and_create(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path)
    repo = storage.ensure_project_root("project-a")
    assert repo.is_dir()
    assert repo == storage.project_repo_dir("project-a")

    attempt = storage.create_attempt_dir("exec-1", 1)
    assert attempt.is_dir()
    assert storage.resolve_checkout_ref(storage.checkout_ref("exec-1", 1)) == attempt


def test_create_attempt_dir_rejects_existing(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path)
    storage.create_attempt_dir("exec-1", 1)
    with pytest.raises(DomainError) as excinfo:
        storage.create_attempt_dir("exec-1", 1)
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_remove_attempt_dir_only_removes_attempt(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path)
    repo = storage.ensure_project_root("project-a")
    attempt = storage.create_attempt_dir("exec-1", 1)
    (attempt / "file.txt").write_text("x", encoding="utf-8")

    storage.remove_attempt_dir("exec-1", 1)
    assert not attempt.exists()
    # Project 根仓库与配置根**不得**被删。
    assert repo.is_dir()
    assert storage.root.is_dir()


def test_remove_attempt_dir_guards_project_root(tmp_path: Path) -> None:
    """清理守卫：即便构造指向 Project 根，也不得删除（越出 executions/ 即拒）。"""
    storage = ProjectStorage(tmp_path)
    storage.ensure_project_root("project-a")
    # 直接对不存在的 execution 调用不越界；守卫以「目标须在 executions/ 之下」为准。
    # 这里验证：attempt 目录名无法伪装为 projects/ 下的路径（片段校验）。
    with pytest.raises(DomainError) as excinfo:
        storage.remove_attempt_dir("../projects/project-a", 0)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_cleanup_does_not_follow_symlink(tmp_path: Path) -> None:
    """Attempt 目录本身若为符号链接 → **只删链接**，不删其指向目标。"""
    storage = ProjectStorage(tmp_path)
    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    execution_dir = storage.paths.execution_dir("exec-1")
    execution_dir.mkdir(parents=True)
    link = execution_dir / "attempt-1"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover
        pytest.skip("当前平台不支持创建符号链接")

    storage.remove_attempt_dir("exec-1", 1)
    assert not link.exists()
    # 指向目标（根外）**未**被跟随删除。
    assert (outside / "keep.txt").is_file()
