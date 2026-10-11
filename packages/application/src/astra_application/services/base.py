"""应用服务基类。"""

from __future__ import annotations

from typing import Any

__all__ = ["ApplicationService"]


class ApplicationService:
    """应用服务基类：持有仓储 / 子域服务依赖。

    Phase 0 采用显式依赖注入（组合根装配后传入），不使用服务定位器。
    """

    def __init__(self, **dependencies: Any) -> None:
        for name, dependency in dependencies.items():
            setattr(self, name, dependency)
