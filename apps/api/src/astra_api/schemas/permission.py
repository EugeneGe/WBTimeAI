"""能力检查 schema（W3 / T2-14；设计 §2.10.2）。

``GET /permissions/check?cap=...`` 的响应：后端下发的 capability 判定结果——
**前端 ``can()`` 的唯一数据源**（前端 **不做**本地推断，W3 裁定 §4.2）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PermissionCheckResponse"]


class PermissionCheckResponse(BaseModel):
    """能力检查响应（``{capability, allowed, effect, reason, source}``）。"""

    capability: str = Field(description="待判定的 capability（如 ``tool:git.commit``）")
    allowed: bool = Field(description="是否放行")
    effect: str = Field(description="效果字面值（``ALLOW`` / ``DENY``）")
    reason: str = Field(default="", description="人类可读原因")
    source: str | None = Field(default=None, description="命中的判定来源")
