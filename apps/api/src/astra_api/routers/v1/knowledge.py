"""``/knowledge`` 路由（W6 / T2-35；设计 §2.6 / §2.12）。

端点：

- ``GET  /knowledge/bases`` 知识库列表；``POST /knowledge/bases`` 创建；
- ``GET  /knowledge/bases/{id}`` 详情；
- ``GET  /knowledge/bases/{id}/documents`` 文档列表（携 ``status`` 进度）；
- ``POST /knowledge/bases/{id}/documents`` 登记文档（``PENDING``）；
- ``POST /knowledge/search`` 检索试跑（命中 + 引用 + 检索路 ``mode``）。

Router **只**做校验 → 调用 ``AppServices.knowledge`` → 映射响应（N-8）；**不** import
``astra_knowledge`` / ORM / Runtime（见 ``test_layering.py`` 的 API 无 ORM 直调断言）。
跨租户 / 不存在 → **404**（隔离不变量 I-1）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.knowledge import (
    CreateDocumentRequest,
    CreateKnowledgeBaseRequest,
    DocumentResponse,
    KnowledgeBaseResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _tenant_id(user: object) -> str:
    """取当前用户租户标识。"""
    return getattr(user, "tenant_id", None) or ""


def _to_base_response(dto: object) -> KnowledgeBaseResponse:
    """KnowledgeBase DTO → 响应。"""
    return KnowledgeBaseResponse(
        id=str(getattr(dto, "id", "")),
        tenant_id=getattr(dto, "tenant_id", None),
        workspace_id=getattr(dto, "workspace_id", None),
        name=str(getattr(dto, "name", "") or ""),
        description=getattr(dto, "description", None),
        embedding_model=dict(getattr(dto, "embedding_model", {}) or {}),
        chunk_config=dict(getattr(dto, "chunk_config", {}) or {}),
        status=str(getattr(dto, "status", "ACTIVE") or "ACTIVE"),
        created_by=str(getattr(dto, "created_by", "") or ""),
        created_at=getattr(dto, "created_at", None),
    )


def _to_document_response(dto: object) -> DocumentResponse:
    """Document DTO → 响应。"""
    return DocumentResponse(
        id=str(getattr(dto, "id", "")),
        knowledge_base_id=str(getattr(dto, "knowledge_base_id", "") or ""),
        title=str(getattr(dto, "title", "") or ""),
        source_type=str(getattr(dto, "source_type", "file") or "file"),
        storage_key=getattr(dto, "storage_key", None),
        mime=getattr(dto, "mime", None),
        size=getattr(dto, "size", None),
        checksum=getattr(dto, "checksum", None),
        status=str(getattr(dto, "status", "PENDING") or "PENDING"),
        error=getattr(dto, "error", None),
        task_id=getattr(dto, "task_id", None),
        created_at=getattr(dto, "created_at", None),
    )


def _to_search_response(dto: object) -> SearchResponse:
    """KnowledgeSearchResult DTO → 响应。"""
    raw_hits = getattr(dto, "hits", []) or []
    hits = [
        SearchHitResponse(
            chunk_id=str(getattr(hit, "chunk_id", "") or ""),
            content=str(getattr(hit, "content", "") or ""),
            score=float(getattr(hit, "score", 0.0) or 0.0),
            source=str(getattr(hit, "source", "") or ""),
            metadata=dict(getattr(hit, "metadata", {}) or {}),
        )
        for hit in raw_hits
    ]
    return SearchResponse(
        query=str(getattr(dto, "query", "") or ""),
        mode=str(getattr(dto, "mode", "keyword") or "keyword"),
        kb_ids=[str(item) for item in (getattr(dto, "kb_ids", []) or [])],
        hits=hits,
    )


@router.get("/bases", response_model=list[KnowledgeBaseResponse], summary="知识库列表")
def list_knowledge_bases(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[KnowledgeBaseResponse]:
    """列出当前租户下的全部知识库。"""
    dtos = services.knowledge.list_bases(tenant_id=_tenant_id(user))
    return [_to_base_response(dto) for dto in dtos]


@router.post(
    "/bases",
    response_model=KnowledgeBaseResponse,
    status_code=201,
    summary="创建知识库",
)
def create_knowledge_base(
    payload: CreateKnowledgeBaseRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> KnowledgeBaseResponse:
    """创建一个知识库（``(tenant_id, name)`` 唯一）。"""
    dto = services.knowledge.create_base(
        tenant_id=_tenant_id(user),
        name=payload.name,
        created_by=str(getattr(user, "id", "") or ""),
        description=payload.description,
        workspace_id=payload.workspace_id,
        embedding_model=payload.embedding_model,
        chunk_config=payload.chunk_config,
    )
    return _to_base_response(dto)


@router.get(
    "/bases/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="知识库详情",
)
def get_knowledge_base(
    knowledge_base_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> KnowledgeBaseResponse:
    """按 id 获取知识库（跨租户 / 不存在 → 404）。"""
    return _to_base_response(
        services.knowledge.get_base(knowledge_base_id, tenant_id=_tenant_id(user))
    )


@router.get(
    "/bases/{knowledge_base_id}/documents",
    response_model=list[DocumentResponse],
    summary="文档列表",
)
def list_documents(
    knowledge_base_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[DocumentResponse]:
    """列出某知识库下的全部文档（``status`` 供前端展示索引进度）。"""
    dtos = services.knowledge.list_documents(knowledge_base_id, tenant_id=_tenant_id(user))
    return [_to_document_response(dto) for dto in dtos]


@router.post(
    "/bases/{knowledge_base_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="登记文档",
)
def create_document(
    knowledge_base_id: str,
    payload: CreateDocumentRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> DocumentResponse:
    """登记一份文档（初始 ``status=PENDING``，供索引任务消费）。"""
    dto = services.knowledge.create_document(
        knowledge_base_id,
        tenant_id=_tenant_id(user),
        title=payload.title,
        source_type=payload.source_type,
        storage_key=payload.storage_key,
        mime=payload.mime,
        size=payload.size,
        checksum=payload.checksum,
    )
    return _to_document_response(dto)


@router.post("/search", response_model=SearchResponse, summary="检索试跑")
def search_knowledge(
    payload: SearchRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SearchResponse:
    """检索试跑（命中分块 + 引用 + 当前检索路 ``mode``）。"""
    dto = services.knowledge.search(
        tenant_id=_tenant_id(user),
        query=payload.query,
        knowledge_base_id=payload.knowledge_base_id,
        workspace_id=payload.workspace_id,
        top_k=payload.top_k,
    )
    return _to_search_response(dto)
