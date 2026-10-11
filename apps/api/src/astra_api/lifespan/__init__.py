"""应用生命周期（lifespan）。

启动：加载配置 → 初始化日志 → 装配 Providers → 存入 ``app.state``。
关闭：释放资源（释放数据库引擎）。
"""

from __future__ import annotations

from .startup import lifespan

__all__ = ["lifespan"]
