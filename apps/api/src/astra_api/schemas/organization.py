"""组织 schema（最小实现：默认组织读取）。"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["OrganizationResponse"]


class OrganizationResponse(BaseModel):
    """组织响应。"""

    id: str
    tenant_id: str | None = None
    name: str
    slug: str
