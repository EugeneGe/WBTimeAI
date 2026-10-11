"""Memory 相关 DTO（W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d；应用层，零框架依赖）。

- :class:`MemoryViewDTO`：记忆视图（按 **scope** 浏览；携带**来源 Run** `source_run_id`）。

字段形状**严格对齐**裁定 §2.4 **F-d** 冻结契约：
``MemoryView{id, kind, scope_type, scope_id, visibility, content, importance,
source_run_id, expires_at, created_at}``（本 DTO 额外携带只读 ``tenant_id`` /
``workspace_id`` / ``memory_type`` / ``confidence``——**加性**，不破坏 F-d 形状）。

🔴 **并行对齐备注**：W6 后端流（`T2-32`）尚未落库 `memory` ORM 时，本 DTO 经
   :meth:`MemoryViewDTO.from_entity` 用 ``getattr`` **结构化**映射，不 hard-import
   ``astra_memory`` 领域实体（避免与后端流并行期 import 失败）。后端流落库后可直接对齐。

🔴 约定（A27）：业务 DTO 顶层键**不得**同时使用 ``{code, message, data, request_id}``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .base import DTO

__all__ = ["MemoryViewDTO"]


def _as_float(value: object, default: float = 0.0) -> float:
    """把原始列值稳健归一化为 ``float``（非法 / 缺失 → ``default``）。"""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_float_opt(value: object) -> float | None:
    """把原始列值归一化为 ``float | None``（缺失 → ``None``）。"""
    return None if value is None else _as_float(value)


@dataclass
class MemoryViewDTO(DTO):
    """一条记忆记录视图（按 scope 浏览；F-d 形状）。"""

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

    @classmethod
    def from_entity(cls, entity: object) -> MemoryViewDTO:
        """由记忆实体 / 记录（结构化）构造 DTO（**不 hard-import** 能力包实体）。"""

        def _get(name: str, default: object = None) -> object:
            return getattr(entity, name, default)

        return cls(
            id=str(_get("id", "") or ""),
            tenant_id=_get("tenant_id"),  # type: ignore[arg-type]
            workspace_id=_get("workspace_id"),  # type: ignore[arg-type]
            kind=str(_get("kind", "") or ""),
            scope_type=str(_get("scope_type", "") or ""),
            scope_id=(None if _get("scope_id") is None else str(_get("scope_id"))),
            visibility=str(_get("visibility", "private") or "private"),
            content=str(_get("content", "") or ""),
            memory_type=(None if _get("memory_type") is None else str(_get("memory_type"))),
            importance=_as_float(_get("importance")),
            confidence=_as_float_opt(_get("confidence")),
            source_run_id=(None if _get("source_run_id") is None else str(_get("source_run_id"))),
            expires_at=_get("expires_at"),  # type: ignore[arg-type]
            created_at=_get("created_at"),  # type: ignore[arg-type]
        )
