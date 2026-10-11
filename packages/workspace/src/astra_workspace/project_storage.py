"""Project / Attempt 受管目录生命周期（仅应用服务调用；T2-55）。

职责（设计 §2.8.1「每任务独立工作副本」/「服务器持久目录」）：

- **Project 根**：``<workspace_root>/projects/<project_id>/repo`` —— 受管基础仓库（**不删**）；
- **Attempt 独立目录**：``<workspace_root>/executions/<execution_id>/attempt-<n>`` —— 每个 Execution
  Attempt 的独立工作副本（唯一、不复用、完成后按保留策略清理）；
- **清理守卫**：删除**仅**允许删 Attempt 目录；**禁止**删除 Project 根仓库 / 配置根。

🔴 **仅由应用服务调用**（Router / API 层**禁止**直接调用；宿主绝对路径**不进** DB / API / 日志，
   API 只暴露不透明 ``checkout_ref``）。

🔴 本模块为**服务端路径**模块（非 ``domain/``）：仅依赖标准库 + ``astra_core`` + 本包
   :mod:`astra_workspace.paths`；**零** Web / ORM / ``astra_runtime``（分层 L-1 / L-3）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from astra_core import DomainError, ErrorCode

from .paths import ManagedWorkspacePaths

__all__ = ["ProjectStorage"]


class ProjectStorage:
    """Project / Attempt 受管目录生命周期管理器（仅应用服务调用）。

    Attributes:
        paths: 底层 :class:`~astra_workspace.paths.ManagedWorkspacePaths`。
    """

    def __init__(self, root: str | Path) -> None:
        """构造。

        Args:
            root: 配置根（``ASTRA_WORKSPACE_ROOT``）。

        Raises:
            DomainError: 根为空 / 不可解析（``VALIDATION_ERROR``）。
        """
        self._paths = ManagedWorkspacePaths(root)

    @property
    def paths(self) -> ManagedWorkspacePaths:
        """返回底层路径解析器（供应用服务复用，避免重复裁决）。"""
        return self._paths

    @property
    def root(self) -> Path:
        """配置根（绝对规范路径）。"""
        return self._paths.root

    # -- Project 根 ---------------------------------------------------------

    def project_repo_dir(self, project_id: str) -> Path:
        """返回 Project 受管基础仓库目录（**不创建**）。"""
        return self._paths.assert_within_root(self._paths.project_repo_dir(project_id))

    def ensure_project_root(self, project_id: str) -> Path:
        """确保 Project 受管基础仓库目录存在并返回。

        Args:
            project_id: 项目标识（安全片段）。

        Returns:
            ``<root>/projects/<project_id>/repo``（已创建）。

        Raises:
            DomainError: 标识非法（``VALIDATION_ERROR``）或路径越界（``PERMISSION_DENIED``）。
        """
        repo_dir = self._paths.assert_within_root(self._paths.project_repo_dir(project_id))
        repo_dir.mkdir(parents=True, exist_ok=True)
        return repo_dir

    # -- Attempt 独立目录 ---------------------------------------------------

    def attempt_dir(self, execution_id: str, attempt: int) -> Path:
        """返回 Attempt 独立目录（**不创建**）。"""
        return self._paths.assert_within_root(self._paths.attempt_dir(execution_id, attempt))

    def create_attempt_dir(self, execution_id: str, attempt: int) -> Path:
        """**新建** Attempt 独立工作副本目录（已存在即拒绝，防复用）。

        Args:
            execution_id: 执行标识（安全片段）。
            attempt: 尝试序号（非负整数）。

        Returns:
            新建的 ``<root>/executions/<execution_id>/attempt-<n>``。

        Raises:
            DomainError: 标识非法（``VALIDATION_ERROR``）、路径越界（``PERMISSION_DENIED``）
                或目录已存在（``CONFLICT``）。
        """
        attempt_dir = self._paths.assert_within_root(self._paths.attempt_dir(execution_id, attempt))
        if attempt_dir.exists():
            raise DomainError(
                "Attempt 目录已存在（每个 Attempt 使用独立工作副本，不得复用）",
                code=ErrorCode.CONFLICT,
                data={"field": "attempt", "attempt": attempt},
            )
        attempt_dir.mkdir(parents=True, exist_ok=False)
        return attempt_dir

    def checkout_ref(self, execution_id: str, attempt: int) -> str:
        """生成 Attempt 的**不透明** checkout 引用（不含宿主绝对路径）。"""
        return self._paths.checkout_ref(execution_id, attempt)

    def resolve_checkout_ref(self, ref: str) -> Path:
        """由不透明 ``checkout_ref`` 还原 Attempt 目录（containment 校验）。"""
        return self._paths.path_for_checkout_ref(ref)

    def remove_attempt_dir(self, execution_id: str, attempt: int) -> None:
        """清理 Attempt 独立目录（**仅**允许删 Attempt；守卫禁止删 Project 根 / 配置根）。

        🔴 **符号链接安全**：若 Attempt 目录**本身**为符号链接，则**只删链接**（绝不跟随），
           以免误删其指向（可能是根外目标或**另一个** Attempt 目录）；若父目录被符号链接到根外，
           由 canonical containment 校验拒绝。

        🔴 保留期判定（未过期 Attempt 不得删）由**应用服务 / 清理器**依保留策略前置；本方法
           仅执行**受守卫的物理删除**（设计与 R-R1R5-13 V-D 的磁盘对象残留清单一致：
           ``downgrade`` / 清理**不得**删 Project 根仓库）。

        Args:
            execution_id: 执行标识（安全片段）。
            attempt: 尝试序号（非负整数）。

        Raises:
            DomainError: 标识非法（``VALIDATION_ERROR``）、越界（``PERMISSION_DENIED``）
                或目标不在 ``executions/`` 之下（``PERMISSION_DENIED``）。
        """
        lexical = self._paths.attempt_dir(execution_id, attempt)
        executions_lexical = self._paths.executions_dir()
        if lexical == executions_lexical or not lexical.is_relative_to(executions_lexical):
            raise DomainError(
                "清理仅允许删除 executions/<execution_id>/attempt-<n>",
                code=ErrorCode.PERMISSION_DENIED,
                data={"path": str(lexical)},
            )
        if lexical.is_symlink():
            # 链接本身：**只删链接**，绝不跟随（防误删目标 / 另一 Attempt）。
            lexical.unlink(missing_ok=True)
            return
        # 非链接：解析符号链接后仍须位于 executions/ 之下（防父目录被链接到根外）。
        resolved = self._paths.assert_within_root(lexical)
        executions = executions_lexical.resolve()
        if not resolved.is_relative_to(executions):
            raise DomainError(
                "清理仅允许删除 executions/<execution_id>/attempt-<n>",
                code=ErrorCode.PERMISSION_DENIED,
                data={"path": str(resolved)},
            )
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=False)
        elif resolved.exists():
            resolved.unlink()
