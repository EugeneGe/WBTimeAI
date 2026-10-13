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

🔴 **R3 / T2-61（C-4 链第二段）**：追加**受限** Diff / Apply / Push Sandbox 实现——
   :meth:`GitService.diff_name_status` / :meth:`GitService.merge` /
   :meth:`GitService.merge_abort` / :meth:`GitService.update_ref` /
   :meth:`GitService.push_ref`（**永不加** ``--force``；拒删远端分支 / 任意 URL）。
   :func:`parse_name_status` 解析 ``--name-status`` 输出为 ``(change_type, path)``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra_core import DomainError, ErrorCode

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import ExecResult, SandboxProvider, SandboxSession

__all__ = [
    "GitService",
    "AttemptCheckout",
    "CHANGE_TYPE_LABELS",
    "parse_name_status",
    "parse_for_each_ref",
]

#: 默认命令超时（毫秒）。
DEFAULT_GIT_TIMEOUT_MS = 120_000

#: ``git diff --name-status`` 变更类型族字母 → 归一化标签（T2-61）。
CHANGE_TYPE_LABELS: Mapping[str, str] = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "typechange",
    "U": "unmerged",
}


def parse_name_status(output: str) -> list[tuple[str, str]]:
    """解析 ``git diff --name-status`` 输出为 ``(change_type, path)`` 列表。

    行格式（制表符分隔）：``<CODE>\\t<path>``；重命名 / 复制为 ``<CODE>\\t<old>\\t<new>``
    （取**末段**为新路径）。``CODE`` 形如 ``A`` / ``M`` / ``D`` / ``R100``（取首字母族）。
    无法解析的行跳过（容忍空行 / 杂散输出）。

    Args:
        output: ``git diff --name-status`` 的标准输出。

    Returns:
        ``(change_type, path)`` 列表（``change_type`` 为归一化标签，未知 → ``modified``）。
    """
    changes: list[tuple[str, str]] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0].strip()
        path = parts[-1].strip()
        if not code or not path:
            continue
        family = code[0].upper()
        changes.append((CHANGE_TYPE_LABELS.get(family, "modified"), path))
    return changes


def parse_for_each_ref(output: str) -> list[tuple[str, str, str]]:
    """解析 ``git for-each-ref --format=%(refname)|%(objectname)|%(objecttype)`` 输出。

    行格式（``|`` 分隔，**2~3 段**）：``<refname>|<oid>[|<objecttype>]``。仅识别：

    - ``refs/heads/*`` → ``(name, oid, "branch")``（``name`` 为去前缀短名）；
    - ``refs/tags/*``  → ``(name, oid, "tag")``（``name`` 为去前缀短名）；
    - 其余 refname（``refs/remotes/*`` / ``refs/stash`` …）**跳过**。

    无法解析的行跳过（容忍空行 / 杂散输出）。``objecttype`` 段可选（仅透传用途；本解析不使用）。

    Args:
        output: ``git for-each-ref`` 的标准输出。

    Returns:
        ``(name, commit, kind)`` 列表（``kind`` ∈ ``{"branch", "tag"}``）。
    """
    refs: list[tuple[str, str, str]] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        refname = parts[0].strip()
        oid = parts[1].strip()
        if not refname or not oid:
            continue
        if refname.startswith("refs/heads/"):
            name = refname[len("refs/heads/") :]
            kind = "branch"
        elif refname.startswith("refs/tags/"):
            name = refname[len("refs/tags/") :]
            kind = "tag"
        else:
            continue
        if not name:
            continue
        refs.append((name, oid, kind))
    return refs


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

    def for_each_ref(
        self,
        session: SandboxSession,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git for-each-ref`` 列出分支 / 标签（**只读**；F3 / R5A-01b）。

        🔴 **仅经 Sandbox**：与既有方法同构，一律经 :meth:`_git`（唯一执行出口）；**只读**
        （不改变仓库状态）。输出经 :func:`parse_for_each_ref` 解析为 ``(name, commit, kind)``。

        Args:
            session: 沙箱会话。
            cwd: 工作目录（沙箱内路径；通常为 Project 受管仓库目录）。
            timeout_ms: 命令超时（毫秒）。

        Returns:
            ``git for-each-ref --format=%(refname)|%(objectname)|%(objecttype)``
            ``refs/heads refs/tags`` 的执行结果。
        """
        return self._git(
            session,
            [
                "for-each-ref",
                "--format=%(refname)|%(objectname)|%(objecttype)",
                "refs/heads",
                "refs/tags",
            ],
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

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

    # -- 变更审阅：Diff / Apply / Push 受限实现（T2-61 · C-4 链第二段） --------
    #
    # 🔴 **仅经 Sandbox**：全部经 :meth:`_git`（**唯一**执行出口）；**禁**宿主直连 git。
    # 🔴 **限制性 push**：本模块**不提供**强推 / 删远端分支 / 任意 URL 能力——refspec 以
    #    ``:``（删除）或 ``+``（强推）开头、或 remote 疑似 URL，一律拒绝（``PERMISSION_DENIED``）。

    def diff_name_status(
        self,
        session: SandboxSession,
        base: str,
        result: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git diff --name-status <base> <result>``（变更文件摘要）。"""
        return self._git(
            session,
            ["diff", "--name-status", base, result],
            cwd=cwd,
            timeout_ms=timeout_ms,
            env=env,
        )

    def merge_base(
        self,
        session: SandboxSession,
        a: str,
        b: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git merge-base <a> <b>``（共同祖先）。"""
        return self._git(session, ["merge-base", a, b], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def fetch_from(
        self,
        session: SandboxSession,
        repo_path: str,
        ref: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git fetch <repo_path> <ref>``（从本地副本取对象，**非**任意远端 URL）。"""
        return self._git(
            session, ["fetch", repo_path, ref], cwd=cwd, timeout_ms=timeout_ms, env=env
        )

    def merge(
        self,
        session: SandboxSession,
        ref: str,
        *,
        no_ff: bool = True,
        message: str | None = None,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内合并 ``ref``（默认 ``--no-ff``；可选提交信息）。冲突 → 非零退出码。"""
        args: list[str] = ["merge"]
        if no_ff:
            args.append("--no-ff")
        if message:
            args.extend(["-m", message])
        args.append(ref)
        return self._git(session, args, cwd=cwd, timeout_ms=timeout_ms, env=env)

    def merge_abort(
        self,
        session: SandboxSession,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git merge --abort``（冲突后回滚合并，**保留原状**）。"""
        return self._git(session, ["merge", "--abort"], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def update_ref(
        self,
        session: SandboxSession,
        ref: str,
        sha: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内 ``git update-ref <ref> <sha>``（**仅**更新服务端 Project 目标分支）。"""
        return self._git(session, ["update-ref", ref, sha], cwd=cwd, timeout_ms=timeout_ms, env=env)

    def push_ref(
        self,
        session: SandboxSession,
        *,
        remote: str,
        refspec: str,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内**受限**推送（``git push <remote> <refspec>``，**永不加** ``--force``）。

        Raises:
            DomainError: ``remote`` 疑似 URL（``scheme://`` / ``@host``）或含 ``--force`` / ``-f``、
                ``refspec`` 以 ``:``（删分支）或 ``+``（强推）开头 —— ``PERMISSION_DENIED``。
        """
        if self._is_remote_url(remote) or "--force" in remote or remote == "-f":
            raise DomainError(
                "禁止推送至任意 URL / 强推 remote",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "remote"},
            )
        token = refspec.strip()
        if not token or token.startswith(":") or token.startswith("+"):
            raise DomainError(
                "禁止删除远端分支 / 强推（refspec 不得以 ':' 或 '+' 开头）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "refspec"},
            )
        if "--force" in refspec or refspec.startswith("-f"):
            raise DomainError(
                "禁止强推（force push）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "refspec"},
            )
        return self._git(
            session, ["push", remote, refspec], cwd=cwd, timeout_ms=timeout_ms, env=env
        )

    @staticmethod
    def _is_remote_url(remote: str) -> bool:
        """判断 remote 是否疑似**任意 URL**（``scheme://`` / ``user@host:path``）。"""
        text = (remote or "").strip()
        if "://" in text:
            return True
        return "@" in text

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
