"""Docker 可用性探测（C-01 装配落点，W4 架构裁定 Q3）。

🔴 ``import docker`` **仅在函数内**（延迟导入）：避免 ``_build_optional`` 的模块导入即失败
   而被误判为「包缺失」（R5）。本探测**仅**被 ``astra_sandbox.factory.build_sandbox_provider``
   调用；Runtime / Tool **永不探测** Docker（C-01）。
"""

from __future__ import annotations

from typing import Literal

__all__ = ["docker_available", "docker_sdk_status"]

#: Docker SDK 探测三态（诊断用；与 :func:`docker_available` **同源**，避免双口径）：
#:
#: - ``"no_sdk"``：``docker`` SDK（``docker`` py 包）不可导入；
#: - ``"unreachable"``：SDK 就位但 ``docker.from_env().ping()`` 失败 / 返回假；
#: - ``"reachable"``：SDK 就位且守护进程可达。
DockerSdkStatus = Literal["no_sdk", "unreachable", "reachable"]


def docker_sdk_status() -> DockerSdkStatus:
    """探测 Docker SDK / 守护进程的三态（**仅探测**，不创建 / 运行任何容器）。

    ``astra doctor`` 的 docker 自检与 :func:`docker_available` **共用此判定**，
    保证「doctor 语义 == capabilities 装配语义」（F-2：镜像含 SDK 而无 CLI，旧以 CLI
    存在与否判定会误报 FAIL）。

    Returns:
        ``"no_sdk"`` / ``"unreachable"`` / ``"reachable"``（任何探测异常 → ``"unreachable"``，
        不抛出）。
    """
    try:
        import docker
    except ImportError:
        return "no_sdk"
    try:
        client = docker.from_env()
        reachable = bool(client.ping())
    except Exception:  # noqa: BLE001 - 探测容错：任何异常均视为不可达
        return "unreachable"
    return "reachable" if reachable else "unreachable"


def docker_available() -> bool:
    """探测本机 Docker 是否可用（SDK 可导入 **且** 守护进程可达）。

    Returns:
        ``True`` 仅当 ``docker_sdk_status() == "reachable"``（``docker`` SDK 可导入 **且**
        ``docker.from_env().ping()`` 成功）；否则 ``False``（``ImportError`` / 任意异常 →
        ``False``，不抛出）。
    """
    return docker_sdk_status() == "reachable"
