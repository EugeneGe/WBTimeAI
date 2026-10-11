"""Workspace Git 用例（**仅经 Sandbox**；W7 / T2-38；R2 / T2-58 增 Attempt 供给）。

🔴 **Git 操作只在 Sandbox 内执行**（Phase 1 §2.5.2 已定，验收②）：所有 git 命令一律
   经注入的 :class:`~astra_sandbox.SandboxProvider.exec` 在沙箱会话内运行——**禁**在 Host
   直连 git（本模块**不 import** ``subprocess`` / ``os.system`` 等）。

🔴 ``SandboxProvider`` 经**构造注入**（Protocol）；本模块**不 import** ``astra_sandbox``
   运行时对象（仅 ``TYPE_CHECKING`` 引类型）。

🔴 **R2 / T2-58（C-4 单写者链头）**：Project Clone / Fetch / status / Attempt checkout 一律
   **委派** :class:`GitService` 的 Sandbox 用例（本模块**唯一**执行出口）；新增
   :meth:`GitService.provision_attempt_checkout`（独立 ``git clone`` + 解析 ``base_commit``）——
   Router / Application Service / Worker **不得**直接启动宿主 Git Shell。单写者链 =
   **T2-58 → T2-61**（T2-61 在本模块追加 Apply / Push 受限实现）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra_core import DomainError, ErrorCode

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import ExecResult, SandboxProvider, SandboxSession

__all__ = ["GitService", "AttemptCheckout"]

#: 默认命令超时（毫秒）。
DEFAULT_GIT_TIMEOUT_MS = 120_000


@dataclass
class AttemptCheckout:
    """Attempt 独立工作副本的 Git 供给结果（T2-58）。

    Attributes:
        clone: ``git clone`` 的执行结果。
        base_commit: 解析到的 Attempt 起始提交（Git OID；``git rev-parse`` 失败为 ``None``）。
    """

    clone: ExecResult
    base_commit: str | None = None


class GitService:
    """工作区 Git 用例（克隆 / 分支 / 提交 / 推送…），**全部经 Sandbox 执行**。"""

    def __init__(
        self, sandbox: SandboxProvider, *, default_timeout_ms: int = DEFAULT_GIT_TIMEOUT_MS
    ) -> None:
        """构造。

        Args:
            sandbox: 注入的 ``SandboxProvider``（**唯一执行出口**）。
            default_timeout_ms: 默认命令超时（毫秒）。
        """
        self._sandbox = sandbox
        self._default_timeout_ms = int(default_timeout_ms)

    @property
    def sandbox(self) -> SandboxProvider:
        """返回注入的 ``SandboxProvider``（供组合根 / 测试检视）。"""
        return self._sandbox

    # -- 常用 git 操作 -------------------------------------------------------

    def clone(
        self,
        session: SandboxSession,
        repo_url: str,
        dest: str | None = None,
        *,
        base_ref: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内克隆仓库（可选检出 ``base_ref``）。

        Raises:
            DomainError: ``repo_url`` 为空（``VALIDATION_ERROR``）。
        """
        if not (repo_url or "").strip():
            raise DomainError(
                "仓库地址不能为空", code=ErrorCode.VALIDATION_ERROR, data={"field": "repo_url"}
            )
        args: list[str] = ["clone", repo_url.strip()]
        if dest:
            args.append(dest.strip())
        result = self._git(session, args, timeout_ms=timeout_ms, env=env)
        if result.ok and base_ref:
            workdir = dest.strip() if dest else None
            result = self.checkout(session, base_ref, cwd=workdir, timeout_ms=timeout_ms, env=env)
        return result

    def fetch(
        self,
        session: SandboxSession,
        *,
        remote: str = "origin",
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git fetch``（默认 ``origin``）。"""
        return self._git(session, ["fetch", remote], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def checkout(
        self,
        session: SandboxSession,
        ref: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内检出引用（分支 / 提交 / tag）。"""
        return self._git(session, ["checkout", ref], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def branch(
        self,
        session: SandboxSession,
        name: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内创建并切换到新分支。"""
        return self._git(session, ["checkout", "-b", name], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def status(
        self,
        session: SandboxSession,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git status --porcelain``。"""
        return self._git(
            session, ["status", "--porcelain"], cwd=cwd, timeout_ms=timeout_ms, env=env
        )

    def commit(
        self,
        session: SandboxSession,
        message: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内提交（``git commit -m <message>``）。"""
        return self._git(
            session, ["commit", "-m", message], cwd=cwd, timeout_ms=timeout_ms, env=env
        )

    def push(
        self,
        session: SandboxSession,
        *,
        remote: str = "origin",
        ref: str | None = None,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内推送（默认 ``origin``）。"""
        args: list[str] = ["push", remote]
        if ref:
            args.append(ref)
        return self._git(session, args, cwd=cwd, timeout_ms=timeout_ms, env=env)

    def rev_parse(
        self,
        session: SandboxSession,
        ref: str = "HEAD",
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git rev-parse <ref>``（取提交哈希）。"""
        return self._git(session, ["rev-parse", ref], cwd=cwd, timeout_ms=timeout_ms, env=env)

    # -- Attempt 独立副本供给（T2-58） --------------------------------------

    def resolve_commit(
        self,
        session: SandboxSession,
        ref: str = "HEAD",
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str | None:
        """在沙箱内解析 ``ref`` 的提交哈希（``git rev-parse``）；失败 / 空返回 ``None``。"""
        result = self.rev_parse(session, ref, cwd=cwd, timeout_ms=timeout_ms, env=env)
        if not result.ok:
            return None
        first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        return first or None

    def provision_attempt_checkout(
        self,
        session: SandboxSession,
        *,
        repo_url: str,
        base_ref: str | None = None,
        dest: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> AttemptCheckout:
        """为一次 Attempt 供给**独立**工作副本：``git clone`` 后解析 ``base_commit``。

        🔴 **独立副本**：使用 ``git clone``（**非** ``git worktree`` / 共享 ``.git`` / refs /
           index）——每个 Attempt 各自拥有 ``.git`` / refs / index，互不共享（设计 §2.8.1）。
        🔴 **仅经 Sandbox**：本方法**不**在 Host 直连 git（所有命令经 :meth:`_git`）。

        Args:
            session: 沙箱会话。
            repo_url: 仓库地址（**禁**含用户名 / Token / 密码）。
            base_ref: 基准引用（分支 / tag / 提交；可空）。
            dest: 目标目录（沙箱内相对路径；可空 = 会话默认工作目录）。
            timeout_ms: 命令超时（毫秒）。
            env: 附加环境变量（**不得**含 Secret 明文；Git 凭证由服务端短时注入）。

        Returns:
            :class:`AttemptCheckout`（含 ``base_commit``）。

        Raises:
            DomainError: ``repo_url`` 为空（``VALIDATION_ERROR``）或克隆失败（``INTERNAL_ERROR``）。
        """
        clone = self.clone(
            session, repo_url, dest=dest, base_ref=base_ref, timeout_ms=timeout_ms, env=env
        )
        if not clone.ok:
            raise DomainError(
                "Attempt 克隆失败（仅经 Sandbox）",
                code=ErrorCode.INTERNAL_ERROR,
                data={"field": "repo_url"},
            )
        base_commit = self.resolve_commit(
            session, base_ref or "HEAD", cwd=dest, timeout_ms=timeout_ms, env=env
        )
        return AttemptCheckout(clone=clone, base_commit=base_commit)

    # -- 唯一执行出口 --------------------------------------------------------

    def _git(
        self,
        session: SandboxSession,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内执行 ``git <args>``（**唯一出口**：一律经 ``SandboxProvider.exec``）。"""
        command = ["git", *args]
        return self._sandbox.exec(
            session,
            command,
            timeout_ms=self._default_timeout_ms if timeout_ms is None else int(timeout_ms),
            env=env,
            cwd=cwd,
        )
