"""``astra_knowledge`` 领域实体（设计 §2.6；W5 裁定 §4.2）。

- :class:`KnowledgeBase`：知识库聚合根（身份与生命周期；``(tenant_id, name)`` 唯一）；
- :class:`Document`：文档（**可变聚合根**，承载索引状态机）；
- :class:`DocumentChunk`：分块（``(document_id, ordinal)`` 唯一——断点续跑锚）；
- :class:`Embedding`：分块向量（值密集型，含 ``vector: list[float]``）；
- :class:`AgentKnowledge`：KnowledgeBase↔AgentVersion 绑定（同构 ``AgentSkill``）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_domain import AggregateRoot
from astra_domain.entities.base import Entity

from ..status import (
    DOCUMENT_STATUS_PENDING,
    KNOWLEDGE_BASE_STATUS_ACTIVE,
    DocumentStatus,
    assert_document_transition,
)

__all__ = [
    "KnowledgeBase",
    "Document",
    "DocumentChunk",
    "Embedding",
    "AgentKnowledge",
]

#: Document 源类型。
DOCUMENT_SOURCE_TYPE_FILE = "file"
DOCUMENT_SOURCE_TYPE_URL = "url"
DOCUMENT_SOURCE_TYPE_TEXT = "text"


@dataclass
class KnowledgeBase(AggregateRoot):
    """知识库聚合根（数据驱动的「文档集合 + 检索配置」单元）。

    Attributes:
        workspace_id: 归属工作区标识（可空）。
        name: 唯一键（租户内唯一）。
        description: 描述。
        embedding_model: 嵌入模型配置 ``{provider, model, dimensions}``（显式路由，P1-a）。
        chunk_config: 分块配置 ``{strategy, size, overlap}``（默认 ``fixed/800/100``）。
        status: 生命周期状态（``KnowledgeBaseStatus`` 字面值）。
        created_by: 创建者用户标识。
    """

    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    embedding_model: dict[str, Any] = field(default_factory=dict)
    chunk_config: dict[str, Any] = field(default_factory=dict)
    status: str = KNOWLEDGE_BASE_STATUS_ACTIVE
    created_by: str = ""


@dataclass
class Document(AggregateRoot):
    """文档（**可变聚合根**；索引状态机的宿主）。

    Attributes:
        knowledge_base_id: 归属知识库标识。
        title: 标题。
        source_type: 源类型（``file`` / ``url`` / ``text``）。
        storage_key: ``Storage`` 对象键（可空）。
        mime: MIME 类型（可空）。
        size: 字节数（可空）。
        checksum: 内容摘要（可空）。
        status: 索引状态（``DocumentStatus`` 字面值）。
        error: 失败原因（可空）。
        task_id: 关联的索引任务标识（可空）。
    """

    knowledge_base_id: str = ""
    title: str = ""
    source_type: str = DOCUMENT_SOURCE_TYPE_FILE
    storage_key: str | None = None
    mime: str | None = None
    size: int | None = None
    checksum: str | None = None
    status: str = DOCUMENT_STATUS_PENDING
    error: str | None = None
    task_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（``READY``）。"""
        return self.status == DocumentStatus.READY.value

    def transition_to(self, status: str | DocumentStatus) -> str:
        """迁移到目标状态（非法迁移抛 ``DomainError(VALIDATION_ERROR)``）。

        Args:
            status: 目标状态（``DocumentStatus`` 字面值 / 枚举）。

        Returns:
            迁移后的状态字面值。
        """
        target = status.value if isinstance(status, DocumentStatus) else str(status)
        assert_document_transition(self.status, target)
        self.status = target
        return target

    def mark_failed(self, error: str) -> str:
        """失败迁移（``* → FAILED``）并记录原因。"""
        target = self.transition_to(DocumentStatus.FAILED)
        self.error = error
        return target


@dataclass
class DocumentChunk(Entity):
    """文档分块（``(document_id, ordinal)`` 唯一；断点续跑锚）。

    Attributes:
        document_id: 归属文档标识。
        ordinal: 块序号（文档内唯一）。
        content: 块文本。
        token_count: token 数（可空）。
        meta: 附加元数据（标题路径 / 页码等；DB 列名 ``metadata``）。
        embedding_id: 反查缓存（可空；**不作检索唯一依据**）。
    """

    document_id: str = ""
    ordinal: int = 0
    content: str = ""
    token_count: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    embedding_id: str | None = None


@dataclass
class Embedding(Entity):
    """分块向量（值密集型；``chunk_id`` 唯一 1:1）。

    Attributes:
        chunk_id: 归属分块标识（唯一）。
        model: 嵌入模型名。
        dimensions: 向量维度。
        vector: 向量值。
    """

    chunk_id: str = ""
    model: str = ""
    dimensions: int = 0
    vector: list[float] = field(default_factory=list)


@dataclass
class AgentKnowledge(AggregateRoot):
    """KnowledgeBase↔AgentVersion 绑定（随版本版本化）。

    Attributes:
        agent_version_id: 归属 AgentVersion 标识。
        knowledge_base_id: 绑定的知识库标识。
        enabled: 是否启用。
        config: 覆盖配置（可空）。
    """

    agent_version_id: str = ""
    knowledge_base_id: str = ""
    enabled: bool = True
    config: dict[str, Any] | None = None
