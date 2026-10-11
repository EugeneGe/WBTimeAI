"""``/memory`` 路由（W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h）。

端点：

- ``GET  /memory`` 按 scope 浏览（query：``scope_type`` / ``scope_id`` / ``kind`` /
  ``limit``）；响应 F-d 形状；
- ``DELETE /memory/{memory_id}`` 删除一条记忆（**F-h**；不存在 / 跨租户 → 404）。

Router **只**做校验 → 调用 ``AppServices.memory`` → 映射响应（N-8）；**不** import
``astra_memory`` / ORM / Runtime（见 ``test_layering.py`` 的 API 无 ORM 直调断言）。
多租户隔离：``tenant_id`` **强制**（任何浏览 / 删除先按租户过滤，I-2/I-3）。

🔴 **并行对齐备注**：后端流（``T2-34``）落库 ``build_memory_store`` 前，``services.memory``
   经占位存储回退（空列表 / 删除 404）——端点**保持可响应**且走统一响应壳；落库后自动接管。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.memory import MemoryResponse

router = APIRouter(prefix="/memory", tags=["memory"])

#: 浏览默认条数（与 ``MemoryService`` 口径一致）。
_DEFAULT_LIMIT = 50


def _tenant_id(user: object) -> str:
    """取当前用户租户标识。"""
    return getattr(user, "tenant_id", None) or ""


def _to_memory_response(dto: object) -> MemoryResponse:
    """MemoryView DTO → 响应（F-d 形状）。"""
    return MemoryResponse(
        id=str(getattr(dto, "id", "")),
        tenant_id=getattr(dto, "tenant_id", None),
        workspace_id=getattr(dto, "workspace_id", None),
        kind=str(getattr(dto, "kind", "") or ""),
        scope_type=str(getattr(dto, "scope_type", "") or ""),
        scope_id=getattr(dto, "scope_id", None),
        visibility=str(getattr(dto, "visibility", "private") or "private"),
        content=str(getattr(dto, "content", "") or ""),
        memory_type=getattr(dto, "memory_type", None),
        importance=float(getattr(dto, "importance", 0.0) or 0.0),
        confidence=getattr(dto, "confidence", None),
        source_run_id=getattr(dto, "source_run_id", None),
        expires_at=getattr(dto, "expires_at", None),
        created_at=getattr(dto, "created_at", None),
    )


@router.get("", response_model=list[MemoryResponse], summary="按 scope 浏览记忆")
def list_memories(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    scope_type: Annotated[str | None, Query(max_length=50)] = None,
    scope_id: Annotated[str | None, Query(max_length=255)] = None,
    kind: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = _DEFAULT_LIMIT,
) -> list[MemoryResponse]:
    """按 ``scope_type`` / ``scope_id`` / ``kind`` 浏览当前租户的记忆。"""
    dtos = services.memory.list_memories(
        tenant_id=_tenant_id(user),
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        limit=limit,
    )
    return [_to_memory_response(dto) for dto in dtos]


@router.delete("/{memory_id}", status_code=204, summary="删除记忆")
def delete_memory(
    memory_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """删除一条记忆（不存在 / 跨租户 → 404）。"""
    services.memory.delete_memory(memory_id, tenant_id=_tenant_id(user))
    return Response(status_code=204)
