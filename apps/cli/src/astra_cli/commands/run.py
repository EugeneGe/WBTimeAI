"""``astra run``——单进程启动 HTTP 服务（决策 D5）。

**复用** ``astra_api`` 的 ``create_app``（经 ``astra_api.main:app``），
**不复制 / 内联任何业务逻辑**；默认 ``127.0.0.1:8080``。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RunConfig", "run", "DEFAULT_HOST", "DEFAULT_PORT"]

#: 默认监听地址（对齐配置默认值）。
DEFAULT_HOST = "127.0.0.1"

#: 默认监听端口。
DEFAULT_PORT = 8080

#: ASGI 应用导入路径（由 ``astra_api.main`` 暴露）。
ASGI_APP = "astra_api.main:app"


@dataclass
class RunConfig:
    """``astra run`` 参数。

    Attributes:
        host: 监听地址。
        port: 监听端口。
        reload: 是否开启自动重载（开发用）。
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    reload: bool = False


def run(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    reload: bool = False,
) -> None:
    """以 uvicorn 单进程启动 Astra AI HTTP 服务。

    Args:
        host: 监听地址（默认 ``127.0.0.1``）。
        port: 监听端口（默认 ``8080``）。
        reload: 是否开启自动重载。
    """
    import uvicorn

    config = RunConfig(host=host, port=port, reload=reload)
    uvicorn.run(ASGI_APP, host=config.host, port=config.port, reload=config.reload)
