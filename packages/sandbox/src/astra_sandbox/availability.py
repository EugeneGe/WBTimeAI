"""Docker 可用性探测（C-01 装配落点，W4 架构裁定 Q3）。

🔴 ``import docker`` **仅在函数内**（延迟导入）：避免 ``_build_optional`` 的模块导入即失败
   而被误判为「包缺失」（R5）。本探测**仅**被 ``astra_sandbox.factory.build_sandbox_provider``
   调用；Runtime / Tool **永不探测** Docker（C-01）。
"""

from __future__ import annotations

__all__ = ["docker_available"]


def docker_available() -> bool:
    """探测本机 Docker 是否可用（SDK 可导入 **且** 守护进程可达）。

    Returns:
        ``True`` 仅当 ``docker`` SDK 可导入 **且** ``docker.from_env().ping()`` 成功；
        否则 ``False``（``ImportError`` / 任意异常 → ``False``，不抛出）。
    """
    try:
        import docker
    except ImportError:
        return False
    try:
        client = docker.from_env()
        return bool(client.ping())
    except Exception:  # noqa: BLE001 - 探测容错：任何异常均视为不可用
        return False
