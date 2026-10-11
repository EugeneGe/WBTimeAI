"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter

from astra_api import __version__

router = APIRouter(tags=["health"])


@router.get("/health", summary="健康检查")
async def health() -> dict[str, str]:
    """返回服务健康状态。

    Returns:
        ``{"status": "ok", "service": "astra-api", "version": <版本>}``
    """
    return {"status": "ok", "service": "astra-api", "version": __version__}
