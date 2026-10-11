"""Audit schema（W3 / T2-17；设计 §2.18 / §2.12）。

``GET /audit`` 基础过滤（user/action/resource/时间 + 分页）的响应模型。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["AuditLogResponse"]


class AuditLogResponse(BaseModel):
    """审计记录响应（**四要素**：who / action / resource / outcome）。"""

    id: str
    tenant_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None, description="who（用户）")
    agent_id: str | None = Field(default=None, description="who（Agent，可空）")
    run_id: str | None = Field(default=None)
    action: str = Field(default="", description="action")
    resource_type: str | None = Field(default=None, description="resource 类型")
    resource_id: str | None = Field(default=None, description="resource 标识")
    outcome: str = Field(default="SUCCESS", description="outcome（SUCCESS/FAILURE/...)")
    duration_ms: int | None = Field(default=None)
    request_id: str | None = Field(default=None)
    created_at: datetime | None = Field(default=None)
