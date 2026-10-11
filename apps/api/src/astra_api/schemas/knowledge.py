"""Knowledge schema（请求 / 响应；W6 / T2-35；设计 §2.6 / §2.12）。

端点（``/knowledge*``）：``bases`` CRUD + ``documents`` 列表 / 登记 + ``search`` 检索试跑。

🔴 统一响应壳（总纲 §11.1）：成功体由 ``ResponseShellMiddleware`` 包裹；本 schema 仅定义
   **业务 DTO**（`data` 载荷），不重复壳字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CreateKnowledgeBaseRequest",
    "CreateDocumentRequest",
    "SearchRequest",
    "KnowledgeBaseResponse",
    "DocumentResponse",
    "SearchHitResponse",
    "SearchResponse",
]


class CreateKnowledgeBaseRequest(BaseModel):
    """创建知识库请求。"""

    name: str = Field(min_length=1, max_length=255, description="知识库名（租户内唯一）")
    description: str | None = Field(default=None, description="描述")
    workspace_id: str | None = Field(default=None, description="归属工作区（可空）")
    embedding_model: dict[str, Any] = Field(default_factory=dict, description="嵌入模型配置")
    chunk_config: dict[str, Any] = Field(default_factory=dict, description="分块配置")


class CreateDocumentRequest(BaseModel):
    """登记文档请求（2b 仅登记元数据；二进制上传归后续阶段）。"""

    title: str = Field(min_length=1, max_length=512, description="标题")
    source_type: str = Field(default="file", max_length=20, description="源类型（file/url/text）")
    storage_key: str | None = Field(default=None, description="Storage 对象键（可空）")
    mime: str | None = Field(default=None, max_length=255, description="MIME 类型（可空）")
    size: int | None = Field(default=None, ge=0, description="字节数（可空）")
    checksum: str | None = Field(default=None, max_length=255, description="内容摘要（可空）")


class SearchRequest(BaseModel):
    """检索试跑请求。"""

    query: str = Field(min_length=1, max_length=4096, description="查询文本")
    knowledge_base_id: str | None = Field(default=None, description="指定 KB（可空）")
    workspace_id: str | None = Field(default=None, description="按工作区收敛 KB 集合（可空）")
    top_k: int = Field(default=5, ge=1, le=50, description="召回条数")


class KnowledgeBaseResponse(BaseModel):
    """知识库响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    embedding_model: dict[str, Any] = Field(default_factory=dict)
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"
    created_by: str = ""
    created_at: datetime | None = None


class DocumentResponse(BaseModel):
    """文档响应（``status`` 供前端展示索引进度）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    knowledge_base_id: str = ""
    title: str = ""
    source_type: str = "file"
    storage_key: str | None = None
    mime: str | None = None
    size: int | None = None
    checksum: str | None = None
    status: str = "PENDING"
    error: str | None = None
    task_id: str | None = None
    created_at: datetime | None = None


class SearchHitResponse(BaseModel):
    """检索命中（引用可回溯）。"""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    content: str = ""
    score: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """检索试跑响应（命中 + 检索路 `mode`）。"""

    model_config = ConfigDict(from_attributes=True)

    query: str = ""
    mode: str = "keyword"
    kb_ids: list[str] = Field(default_factory=list)
    hits: list[SearchHitResponse] = Field(default_factory=list)
