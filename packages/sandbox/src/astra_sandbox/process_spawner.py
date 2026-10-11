"""本地子进程启动器（被托管的宿主进程；``astra_sandbox`` —「唯一执行出口」）。

``tests/integration/test_sandbox_scan.py`` 规定：除
``packages/sandbox/**``（唯一合法执行出口）外，任何包**不得**直调 ``subprocess``。
MCP stdio 传输需拉起本地 MCP Server 子进程，故本模块在该**出口**提供
:class:`SubprocessProcessSpawner`；``astra_mcp`` 只面向注入的
``ProcessSpawner`` Protocol（结构化契合，**不** import 本模块、**不** import subprocess）。

用法（组合根）：把 :class:`SubprocessProcessSpawner` 注入
``astra_mcp.build_mcp_client(spawner=...)``。
"""

from __future__ import annotations

import subprocess  # noqa: S404 - 「唯一执行出口」：本包为 allowlist 的合法子进程启动点
from collections.abc import Mapping, Sequence

__all__ = ["SubprocessProcessSpawner"]


class SubprocessProcessSpawner:
    """基于 ``subprocess.Popen`` 的本地子进程启动器（stdio 管道就绪）。

    返回的 ``subprocess.Popen`` 对象**结构化满足** ``astra_mcp.client.ManagedProcess``
    （``stdin`` / ``stdout`` / ``stderr`` / ``poll`` / ``terminate`` / ``kill`` / ``wait``）。
    """

    def spawn(
        self,
        *,
        command: str,
        args: Sequence[str],
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> subprocess.Popen[bytes]:
        """拉起子进程（stdio 传输：stdin/stdout/stderr 全管道，无缓冲）。

        Args:
            command: 可执行文件路径 / 名。
            args: 参数列表。
            env: 环境变量（``None`` = 继承父进程）。
            cwd: 工作目录（可空）。

        Returns:
            已启动的 ``Popen`` 句柄。

        Raises:
            OSError: 可执行文件不存在 / 无权限等（由调用方转 ``MCPTransportError``）。
        """
        return subprocess.Popen(  # noqa: S603 - 命令由受信 MCP Server 配置提供
            [command, *[str(item) for item in args]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env) if env else None,
            cwd=cwd,
            bufsize=0,
        )
