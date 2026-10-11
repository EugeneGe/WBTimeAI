"""Approval schema（W10 / T2-49；设计 §2.10 / §2.12）。

面向 ``/approvals`` 待办列表与决议的响应模型（``Approval`` 领域实体的对外视图）。

🔴 决议请求体为空——决议人取当前用户（``CurrentUser``），状态由端点语义固定
   （``approve`` → ``APPROVED`` / ``reject`` → ``REJECTED``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ApprovalResponse"]


class ApprovalResponse(BaseModel):
    """审批记录响应（``Approval`` 的对外视图）。"""

    id: str
    tenant_id: str | None = None
    subject_type: str = ""
    subject_ref: str = ""
    requested_by: str | None = None
    status: str = "PENDING"
    decided_by: str | None = None
    decided_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
