"""Memory schema（请求 / 响应；W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d）。

端点（``/memory*``）：``GET /memory``（按 scope 浏览）+ ``DELETE /memory/{id}``。

响应形状**严格对齐**裁定 §2.4 **F-d** 冻结契约：
``MemoryView{id, kind, scope_type, scope_id, visibility, content, importance,
source_run_id, expires_at, created_at}``（本 schema 额外携带只读 ``tenant_id`` /
``workspace_id`` / ``memory_type`` / ``confidence``——**加性**）。

🔴 统一响应壳（总纲 §11.1）：成功体由 ``ResponseShellMiddleware`` 包裹；本 schema 仅定义
   **业务 DTO**（`data` 载荷）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["MemoryResponse"]


class MemoryResponse(BaseModel):
    """记忆视图响应（F-d 形状；含来源 Run `source_run_id`）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    kind: str = ""
    scope_type: str = ""
    scope_id: str | None = None
    visibility: str = "private"
    content: str = ""
    memory_type: str | None = None
    importance: float = 0.0
    confidence: float | None = None
    source_run_id: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
