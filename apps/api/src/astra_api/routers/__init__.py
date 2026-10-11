"""路由聚合导出。"""

from __future__ import annotations

from .health import router as health_router
from .v1 import api_router

__all__ = ["health_router", "api_router"]
