"""受管工作区路径（``ASTRA_WORKSPACE_ROOT`` · UUID 派生 + canonical containment；T2-55）。

设计 §2.8.1：服务端持有 Project 仓库与 Attempt 独立副本；路径**由服务端 UUID 派生**
（如 ``projects/<project_id>/repo`` 与 ``executions/<task_execution_id>/attempt-<n>``），
数据库 / API **只暴露不透明** ``checkout_ref``，**不暴露**宿主绝对路径。

安全不变量（本模块**唯一**路径裁决点）：

1. **拒绝绝对路径 / ``..`` / 分隔符**——所有路径片段的构造经 :func:`is_safe_path_segment`
   白名单校验（仅 ``[A-Za-z0-9._-]``，首字符须为字母数字）；
2. **canonical containment**——拼接后**解析符号链接**，实际路径必须仍位于配置根目录内；
   拒绝符号链接逃逸（symlink escape）与跨 Project 引用；
3. **不透明 checkout 引用**——``checkout_ref`` 为不含宿主路径的句柄（可服务端还原）。

🔴 本模块为**服务端路径**模块（非 ``domain/``）：仅依赖标准库 + ``astra_core``；**零** Web /
   ORM / ``astra_runtime``（分层 L-1 / L-3）。
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from astra_core import DomainError, ErrorCode

__all__ = [
    "WORKSPACE_PROJECTS_DIRNAME",
    "WORKSPACE_EXECUTIONS_DIRNAME",
    "WORKSPACE_REPO_DIRNAME",
    "WORKSPACE_ATTEMPT_DIR_PREFIX",
    "WORKSPACE_CHECKOUT_REF_PREFIX",
    "is_safe_path_segment",
    "resolve_workspace_root",
    "ManagedWorkspacePaths",
]

#: Project 根目录名（相对 ``ASTRA_WORKSPACE_ROOT``）。
WORKSPACE_PROJECTS_DIRNAME = "projects"

#: Attempt 执行目录名（相对 ``ASTRA_WORKSPACE_ROOT``）。
WORKSPACE_EXECUTIONS_DIRNAME = "executions"

#: 受管基础仓库目录名（相对 Project 根）。
WORKSPACE_REPO_DIRNAME = "repo"

#: Attempt 目录前缀（``attempt-<n>``）。
WORKSPACE_ATTEMPT_DIR_PREFIX = "attempt-"

#: ``checkout_ref`` 不透明句柄前缀。
WORKSPACE_CHECKOUT_REF_PREFIX = "wr_"

#: 合法路径片段：仅 ``[A-Za-z0-9._-]``，**首字符须为字母数字**（天然排除 ``.`` / ``..``）。
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def is_safe_path_segment(value: object) -> bool:
    """判断字符串是否为**合法且安全**的路径片段（拒绝穿越 / 绝对路径 / 分隔符）。

    仅接受 ``[A-Za-z0-9._-]`` 且**首字符为字母数字**的**单段**标识：
    ``..`` / ``.`` / ``a/b`` / ``a\\b`` / ``/etc`` / ``C:\\x`` / 空串 一律拒绝。

    Args:
        value: 待判定值（任意类型，非字符串一律不合法）。

    Returns:
        ``True`` 表示为安全的单段标识。
    """
    if not isinstance(value, str):
        return False
    return bool(_PATH_SEGMENT_RE.match(value))


def resolve_workspace_root(root: str | Path) -> Path:
    """解析配置根为**绝对规范路径**（``expanduser`` + ``resolve``；**不建目录**）。

    Args:
        root: 配置的 ``ASTRA_WORKSPACE_ROOT``（字符串或 ``Path``）。

    Returns:
        解析后的绝对路径（符号链接已展开）。

    Raises:
        DomainError: ``root`` 为空或不可解析（``VALIDATION_ERROR``）。
    """
    text = str(root or "").strip()
    if not text:
        raise DomainError(
            "ASTRA_WORKSPACE_ROOT 未配置",
            code=ErrorCode.VALIDATION_ERROR,
            data={"field": "workspace_root"},
        )
    try:
        return Path(text).expanduser().resolve()
    except OSError as exc:  # pragma: no cover - 极端路径
        raise DomainError(
            "ASTRA_WORKSPACE_ROOT 解析失败",
            code=ErrorCode.VALIDATION_ERROR,
            data={"field": "workspace_root", "root": text},
        ) from exc


class ManagedWorkspacePaths:
    """受管工作区路径解析器（UUID 派生 + canonical containment）。

    所有路径**仅**由配置根 + 安全片段派生；任一构造在解析符号链接后仍须位于根内。
    ``checkout_ref`` 为**不透明**句柄（不含宿主绝对路径），可经服务端还原为 Attempt 目录。

    Attributes:
        root: 配置根（绝对规范路径）。
    """

    def __init__(self, root: str | Path) -> None:
        """构造。

        Args:
            root: 配置根（``ASTRA_WORKSPACE_ROOT``）。

        Raises:
            DomainError: 根为空 / 不可解析（``VALIDATION_ERROR``）。
        """
        self._root = resolve_workspace_root(root)

    @property
    def root(self) -> Path:
        """配置根（绝对规范路径）。"""
        return self._root

    # -- 派生路径 -----------------------------------------------------------

    def projects_dir(self) -> Path:
        """``<root>/projects``。"""
        return self._root / WORKSPACE_PROJECTS_DIRNAME

    def project_dir(self, project_id: str) -> Path:
        """``<root>/projects/<project_id>``（校验 ``project_id`` 为安全片段）。"""
        return self._root / WORKSPACE_PROJECTS_DIRNAME / self._segment("project_id", project_id)

    def project_repo_dir(self, project_id: str) -> Path:
        """``<root>/projects/<project_id>/repo``（Project 受管基础仓库）。"""
        return self.project_dir(project_id) / WORKSPACE_REPO_DIRNAME

    def executions_dir(self) -> Path:
        """``<root>/executions``。"""
        return self._root / WORKSPACE_EXECUTIONS_DIRNAME

    def execution_dir(self, execution_id: str) -> Path:
        """``<root>/executions/<execution_id>``。"""
        return (
            self._root / WORKSPACE_EXECUTIONS_DIRNAME / self._segment("execution_id", execution_id)
        )

    def attempt_dir(self, execution_id: str, attempt: int) -> Path:
        """``<root>/executions/<execution_id>/attempt-<n>``（独立工作副本）。"""
        return self.execution_dir(execution_id) / (
            f"{WORKSPACE_ATTEMPT_DIR_PREFIX}{self._attempt(attempt)}"
        )

    # -- containment（唯一裁决点） -----------------------------------------

    def resolve_within_root(self, *parts: str, must_exist: bool = False) -> Path:
        """把**安全片段**序列拼接到根下并做 canonical containment 校验。

        Args:
            *parts: 安全路径片段（逐段校验；拒绝绝对路径 / ``..`` / 分隔符）。
            must_exist: 是否要求解析后路径已存在。

        Returns:
            位于根内的**绝对规范**路径。

        Raises:
            DomainError: 片段非法（``VALIDATION_ERROR``）或解析后越出根 / 目标不存在
                （``PERMISSION_DENIED`` / ``VALIDATION_ERROR``）。
        """
        candidate = self._root
        for part in parts:
            candidate = candidate / self._segment("path_segment", part)
        return self.assert_within_root(candidate, must_exist=must_exist)

    def assert_within_root(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """断言 ``path``（含符号链接解析后）仍位于配置根内。

        Args:
            path: 待校验路径（可绝对 / 相对）。
            must_exist: 是否要求路径已存在。

        Returns:
            解析后的绝对规范路径。

        Raises:
            DomainError: 解析后越出根（含符号链接逃逸，``PERMISSION_DENIED``）；
                解析失败 / 目标不存在（``VALIDATION_ERROR``）。
        """
        try:
            resolved = Path(path).resolve()
        except OSError as exc:  # pragma: no cover - 极端路径
            raise DomainError(
                "路径解析失败",
                code=ErrorCode.VALIDATION_ERROR,
                data={"path": str(path)},
            ) from exc
        if not resolved.is_relative_to(self._root):
            raise DomainError(
                "路径越出 Workspace 根（含符号链接逃逸）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"path": str(path), "root": str(self._root)},
            )
        if must_exist and not resolved.exists():
            raise DomainError(
                "目标路径不存在",
                code=ErrorCode.VALIDATION_ERROR,
                data={"path": str(resolved)},
            )
        return resolved

    # -- 不透明 checkout 引用 ----------------------------------------------

    def checkout_ref(self, execution_id: str, attempt: int) -> str:
        """生成**不透明**的 Attempt checkout 引用（不含宿主绝对路径）。

        Args:
            execution_id: 执行标识（安全片段）。
            attempt: 尝试序号（非负整数）。

        Returns:
            形如 ``wr_<base64url>`` 的不透明句柄（服务端可还原）。
        """
        self._segment("execution_id", execution_id)
        raw = f"{execution_id}:{self._attempt(attempt)}".encode()
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"{WORKSPACE_CHECKOUT_REF_PREFIX}{token}"

    def parse_checkout_ref(self, ref: str) -> tuple[str, int]:
        """还原 ``checkout_ref`` 为 ``(execution_id, attempt)``。

        Args:
            ref: 由 :meth:`checkout_ref` 生成的句柄。

        Returns:
            ``(execution_id, attempt)``。

        Raises:
            DomainError: 句柄格式非法（``VALIDATION_ERROR``）。
        """
        text = str(ref or "")
        if not text.startswith(WORKSPACE_CHECKOUT_REF_PREFIX):
            raise DomainError(
                "非法 checkout_ref（前缀不匹配）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "checkout_ref"},
            )
        token = text[len(WORKSPACE_CHECKOUT_REF_PREFIX) :]
        padding = "=" * (-len(token) % 4)
        try:
            decoded = base64.urlsafe_b64decode(f"{token}{padding}").decode("utf-8")
            execution_id, _, attempt_text = decoded.rpartition(":")
            attempt = int(attempt_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DomainError(
                "非法 checkout_ref（无法解析）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "checkout_ref"},
            ) from exc
        if not is_safe_path_segment(execution_id) or attempt < 0:
            raise DomainError(
                "非法 checkout_ref（字段不合法）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "checkout_ref"},
            )
        return execution_id, attempt

    def path_for_checkout_ref(self, ref: str) -> Path:
        """由 ``checkout_ref`` 还原 Attempt 目录（canonical containment 校验）。"""
        execution_id, attempt = self.parse_checkout_ref(ref)
        return self.assert_within_root(self.attempt_dir(execution_id, attempt))

    # -- 内部 ---------------------------------------------------------------

    def _segment(self, name: str, value: object) -> str:
        """校验并返回安全路径片段。"""
        if not is_safe_path_segment(value):
            raise DomainError(
                "非法路径片段（拒绝绝对路径 / '..' / 分隔符）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": name, "value": str(value)},
            )
        return str(value)

    @staticmethod
    def _attempt(attempt: int) -> str:
        """校验尝试序号为非负整数并返回其字符串形式。"""
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            raise DomainError(
                "attempt 必须为非负整数",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "attempt", "value": str(attempt)},
            )
        return str(attempt)
