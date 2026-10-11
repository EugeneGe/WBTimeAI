"""``SqlKnowledgeBaseRepository`` 等（实现 ``astra_knowledge`` 的领域仓储 Protocol）。

- :class:`SqlKnowledgeBaseRepository`（``knowledge_base`` 表，``(tenant_id, name)`` 唯一）；
- :class:`SqlDocumentRepository`（``document`` 表）；
- :class:`SqlDocumentChunkRepository`（``document_chunk`` 表，``(document_id, ordinal)`` 唯一）；
- :class:`SqlEmbeddingRepository`（``embedding`` 表，``chunk_id`` 唯一 1:1）；
- :class:`SqlAgentKnowledgeRepository`（``agent_knowledge`` 表）。

🔴 落在能力包 ``repositories/``（W5 裁定 §4.3；能力包仅禁 Web，ORM 允许）。
"""

from __future__ import annotations

import builtins
import json
import re
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_database import apply_scope, session_scope
from astra_database.models.knowledge import AgentKnowledge as OrmAgentKnowledge
from astra_database.models.knowledge import Document as OrmDocument
from astra_database.models.knowledge import DocumentChunk as OrmDocumentChunk
from astra_database.models.knowledge import Embedding as OrmEmbedding
from astra_database.models.knowledge import KnowledgeBase as OrmKnowledgeBase
from astra_domain import ScopeFilter
from sqlalchemy import bindparam, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from ..domain import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedding,
    KnowledgeBase,
)
from .mappers import (
    agent_knowledge_to_domain,
    agent_knowledge_to_orm,
    document_chunk_to_domain,
    document_chunk_to_orm,
    document_to_domain,
    document_to_orm,
    embedding_to_domain,
    embedding_to_orm,
    knowledge_base_to_domain,
    knowledge_base_to_orm,
)

__all__ = [
    "SqlKnowledgeBaseRepository",
    "SqlDocumentRepository",
    "SqlDocumentChunkRepository",
    "SqlEmbeddingRepository",
    "SqlAgentKnowledgeRepository",
]


def _vector_literal(vector: list[float]) -> str:
    """把 ``list[float]`` 渲染为 pgvector 字面量 ``'[v1,v2,...]'``（经 ``CAST(:q AS vector)``）。"""
    return "[" + ",".join(repr(float(item)) for item in vector) + "]"


#: FTS5 词元分割器（词字符 / CJK 统一表意连续段）。
_FTS_TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _fts_match_query(text: str) -> str:
    """把用户文本渲染为安全的 FTS5 ``MATCH`` 表达式（词元 ``OR`` 连接；空 → 空串）。

    逐词元加双引号防 FTS5 语法注入（``"`` / ``*`` / ``:`` 等元字符失效）。
    """
    tokens = [token for token in _FTS_TOKEN.findall(text or "") if token]
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens)


def _chunk_from_mapping(row: Any) -> DocumentChunk:  # noqa: ANN401 - SQLAlchemy RowMapping
    """把查询行映射为领域 :class:`DocumentChunk`（语义 / 关键字两路共用）。

    ``dc.metadata`` 经原生 ``text()`` 查询返回**原始列值**（SQLite 为 JSON 文本字符串；
    PG ``JSONB`` 由驱动解析为 ``dict``），故统一经 :func:`_coerce_json` 归一化。
    """
    created_at = row["created_at"]
    normalized = created_at if isinstance(created_at, datetime) else utcnow()
    return DocumentChunk(
        id=str(row["id"]),
        created_at=normalized,
        updated_at=normalized,
        document_id=str(row["document_id"]),
        ordinal=int(row["ordinal"]),
        content=str(row["content"]),
        token_count=(int(row["token_count"]) if row["token_count"] is not None else None),
        meta=_coerce_json(row["meta"]),
        embedding_id=(str(row["embedding_id"]) if row["embedding_id"] is not None else None),
    )


def _coerce_json(
    value: Any,
) -> dict[str, Any]:  # noqa: ANN401 - 原始列值（dict / str / bytes / None）
    """把原生列值归一化为 ``dict``（``JSONType`` 序列化结果在原生查询下为文本）。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


class SqlKnowledgeBaseRepository:
    """基于 SQLAlchemy 的 KnowledgeBase 仓储（``knowledge_base`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> KnowledgeBase | None:
        """按主键获取知识库，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmKnowledgeBase, entity_id)
            return knowledge_base_to_domain(row) if row is not None else None

    def get_by_name(self, tenant_id: str, name: str) -> KnowledgeBase | None:
        """按 ``(tenant_id, name)`` 获取知识库，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmKnowledgeBase).where(
                OrmKnowledgeBase.tenant_id == tenant_id, OrmKnowledgeBase.name == name
            )
            row = session.execute(statement).scalars().first()
            return knowledge_base_to_domain(row) if row is not None else None

    def add(self, entity: KnowledgeBase) -> KnowledgeBase:
        """新增知识库并返回。"""
        with session_scope(self._session_factory) as session:
            row = knowledge_base_to_orm(entity)
            session.add(row)
            session.flush()
            return knowledge_base_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[KnowledgeBase]:
        """按等值条件列出知识库（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmKnowledgeBase)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmKnowledgeBase, field) == value)
            statement = apply_scope(statement, OrmKnowledgeBase, scope)
            rows = session.execute(statement).scalars().all()
            return [knowledge_base_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[KnowledgeBase]:
        """列出某租户下的全部知识库。"""
        return self.list(tenant_id=tenant_id)

    def list_by_workspace(self, workspace_id: str) -> builtins.list[KnowledgeBase]:
        """列出某工作区下的全部知识库。"""
        return self.list(workspace_id=workspace_id)

    def update(self, entity: KnowledgeBase) -> KnowledgeBase:
        """更新知识库并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmKnowledgeBase, entity.id)
            if row is None:
                return knowledge_base_to_domain(knowledge_base_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.name = entity.name
            row.description = entity.description
            row.embedding_model = dict(entity.embedding_model or {})
            row.chunk_config = dict(entity.chunk_config or {})
            row.status = entity.status
            session.flush()
            return knowledge_base_to_domain(row)

    def delete(self, entity: KnowledgeBase) -> None:
        """删除知识库。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmKnowledgeBase, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlDocumentRepository:
    """基于 SQLAlchemy 的 Document 仓储（``document`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Document | None:
        """按主键获取文档，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocument, entity_id)
            return document_to_domain(row) if row is not None else None

    def add(self, entity: Document) -> Document:
        """新增文档并返回。"""
        with session_scope(self._session_factory) as session:
            row = document_to_orm(entity)
            session.add(row)
            session.flush()
            return document_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Document]:
        """按等值条件列出文档（``scope`` 叠加租户过滤；文档表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDocument)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmDocument, field) == value)
            statement = apply_scope(statement, OrmDocument, scope)
            rows = session.execute(statement).scalars().all()
            return [document_to_domain(row) for row in rows]

    def list_by_kb(self, knowledge_base_id: str) -> builtins.list[Document]:
        """列出某知识库下的全部文档（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmDocument)
                .where(OrmDocument.knowledge_base_id == knowledge_base_id)
                .order_by(OrmDocument.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [document_to_domain(row) for row in rows]

    def list_by_status(self, status: str) -> builtins.list[Document]:
        """按状态列出文档。"""
        return self.list(status=status)

    def get_by_task(self, task_id: str) -> Document | None:
        """按 ``task_id`` 获取文档，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDocument).where(OrmDocument.task_id == task_id)
            row = session.execute(statement).scalars().first()
            return document_to_domain(row) if row is not None else None

    def update_status(
        self, document_id: str, status: str, *, error: str | None = None
    ) -> Document | None:
        """更新文档状态（并可选记录 ``error``），不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocument, document_id)
            if row is None:
                return None
            row.status = status
            if error is not None:
                row.error = error
            session.flush()
            return document_to_domain(row)

    def update(self, entity: Document) -> Document:
        """更新文档并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocument, entity.id)
            if row is None:
                return document_to_domain(document_to_orm(entity))
            row.knowledge_base_id = entity.knowledge_base_id
            row.title = entity.title
            row.source_type = entity.source_type
            row.storage_key = entity.storage_key
            row.mime = entity.mime
            row.size = entity.size
            row.checksum = entity.checksum
            row.status = entity.status
            row.error = entity.error
            row.task_id = entity.task_id
            session.flush()
            return document_to_domain(row)

    def delete(self, entity: Document) -> None:
        """删除文档。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocument, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlDocumentChunkRepository:
    """基于 SQLAlchemy 的 DocumentChunk 仓储（``document_chunk`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> DocumentChunk | None:
        """按主键获取分块，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocumentChunk, entity_id)
            return document_chunk_to_domain(row) if row is not None else None

    def add(self, entity: DocumentChunk) -> DocumentChunk:
        """新增分块并返回。"""
        with session_scope(self._session_factory) as session:
            row = document_chunk_to_orm(entity)
            session.add(row)
            session.flush()
            return document_chunk_to_domain(row)

    def add_many(self, entities: builtins.list[DocumentChunk]) -> builtins.list[DocumentChunk]:
        """批量新增分块并返回。"""
        with session_scope(self._session_factory) as session:
            rows = [document_chunk_to_orm(entity) for entity in entities]
            session.add_all(rows)
            session.flush()
            return [document_chunk_to_domain(row) for row in rows]

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[DocumentChunk]:
        """按等值条件列出分块（``scope`` 叠加过滤；分块表无租户 / 组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDocumentChunk)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmDocumentChunk, field) == value)
            statement = apply_scope(statement, OrmDocumentChunk, scope)
            rows = session.execute(statement).scalars().all()
            return [document_chunk_to_domain(row) for row in rows]

    def list_by_document(
        self, document_id: str, *, order_by_ordinal: bool = True
    ) -> builtins.list[DocumentChunk]:
        """列出某文档的全部分块（默认按 ``ordinal`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDocumentChunk).where(OrmDocumentChunk.document_id == document_id)
            if order_by_ordinal:
                statement = statement.order_by(OrmDocumentChunk.ordinal.asc())
            rows = session.execute(statement).scalars().all()
            return [document_chunk_to_domain(row) for row in rows]

    def exists_ordinals(self, document_id: str) -> set[int]:
        """返回某文档**已完成**的全部 ``ordinal`` 集合（断点续跑锚）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmDocumentChunk.ordinal).where(
                OrmDocumentChunk.document_id == document_id
            )
            return {int(item) for item in session.execute(statement).scalars().all()}

    def update(self, entity: DocumentChunk) -> DocumentChunk:
        """更新分块并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocumentChunk, entity.id)
            if row is None:
                return document_chunk_to_domain(document_chunk_to_orm(entity))
            row.ordinal = entity.ordinal
            row.content = entity.content
            row.token_count = entity.token_count
            row.meta = dict(entity.meta or {}) or None
            row.embedding_id = entity.embedding_id
            session.flush()
            return document_chunk_to_domain(row)

    def set_embedding_id(self, chunk_id: str, embedding_id: str | None) -> None:
        """回填 ``document_chunk.embedding_id``（四步写入第 ④ 步；反查缓存）。"""
        with session_scope(self._session_factory) as session:
            session.execute(
                update(OrmDocumentChunk)
                .where(OrmDocumentChunk.id == chunk_id)
                .values(embedding_id=embedding_id)
            )

    def search_fts(
        self,
        query: str,
        *,
        knowledge_base_ids: builtins.list[str],
        top_k: int = 5,
    ) -> builtins.list[tuple[DocumentChunk, float]]:
        """SQLite FTS5 关键字路：``MATCH`` + ``bm25`` 检索（返回 ``(chunk, score)``）。

        🔴 仅在 SQLite 下可用（``document_chunk_fts`` 虚表由 ``0013`` 创建）；``score`` ＝
        ``-bm25(...)``（**越大越相关**），按 ``bm25`` 升序返回稳定序。
        """
        match = _fts_match_query(query)
        if not match or not knowledge_base_ids or top_k <= 0:
            return []
        statement = text(
            "SELECT dc.id AS id, dc.document_id AS document_id, dc.ordinal AS ordinal, "
            "dc.content AS content, dc.token_count AS token_count, "
            "dc.metadata AS meta, dc.embedding_id AS embedding_id, "
            "dc.created_at AS created_at, "
            "-bm25(document_chunk_fts) AS score "
            "FROM document_chunk_fts "
            "JOIN document_chunk AS dc ON dc.rowid = document_chunk_fts.rowid "
            "JOIN document AS d ON d.id = dc.document_id "
            "WHERE document_chunk_fts MATCH :q AND d.knowledge_base_id IN :kbs "
            "ORDER BY bm25(document_chunk_fts) "
            "LIMIT :k"
        ).bindparams(bindparam("kbs", expanding=True))
        with session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    statement,
                    {"q": match, "kbs": builtins.list(knowledge_base_ids), "k": int(top_k)},
                )
                .mappings()
                .all()
            )
        return [(_chunk_from_mapping(row), float(row["score"])) for row in rows]

    def delete(self, entity: DocumentChunk) -> None:
        """删除分块。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmDocumentChunk, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlEmbeddingRepository:
    """基于 SQLAlchemy 的 Embedding 仓储（``embedding`` 表；``chunk_id`` 唯一 1:1）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Embedding | None:
        """按主键获取向量，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmEmbedding, entity_id)
            return embedding_to_domain(row) if row is not None else None

    def get_by_chunk(self, chunk_id: str) -> Embedding | None:
        """按 ``chunk_id`` 获取向量，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmEmbedding).where(OrmEmbedding.chunk_id == chunk_id)
            row = session.execute(statement).scalars().first()
            return embedding_to_domain(row) if row is not None else None

    def add(self, entity: Embedding) -> Embedding:
        """新增向量并返回。"""
        with session_scope(self._session_factory) as session:
            row = embedding_to_orm(entity)
            session.add(row)
            session.flush()
            return embedding_to_domain(row)

    def add_many(self, entities: builtins.list[Embedding]) -> builtins.list[Embedding]:
        """批量新增向量并返回。"""
        with session_scope(self._session_factory) as session:
            rows = [embedding_to_orm(entity) for entity in entities]
            session.add_all(rows)
            session.flush()
            return [embedding_to_domain(row) for row in rows]

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Embedding]:
        """按等值条件列出向量（``scope`` 叠加过滤；向量表无租户 / 组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmEmbedding)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmEmbedding, field) == value)
            statement = apply_scope(statement, OrmEmbedding, scope)
            rows = session.execute(statement).scalars().all()
            return [embedding_to_domain(row) for row in rows]

    def search_semantic(
        self,
        vector: builtins.list[float],
        *,
        knowledge_base_ids: builtins.list[str],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> builtins.list[tuple[DocumentChunk, float]]:
        """PG 语义路：按余弦相似度检索（返回 ``(chunk, score)`` 按分数降序）。

        🔴 仅在 PostgreSQL + pgvector 下可用（``capability.vector_search`` 为真）；
        ``filters`` 为保留参数（当前最小闭环未启用，便于后续加性扩展）。
        """
        if not knowledge_base_ids or top_k <= 0:
            return []
        statement = text(
            "SELECT dc.id AS id, dc.document_id AS document_id, dc.ordinal AS ordinal, "
            "dc.content AS content, dc.token_count AS token_count, "
            "dc.metadata AS meta, dc.embedding_id AS embedding_id, "
            "dc.created_at AS created_at, "
            "1 - (emb.vector <=> CAST(:q AS vector)) AS score "
            "FROM embedding AS emb "
            "JOIN document_chunk AS dc ON dc.id = emb.chunk_id "
            "JOIN document AS d ON d.id = dc.document_id "
            "WHERE d.knowledge_base_id IN :kbs "
            "ORDER BY emb.vector <=> CAST(:q AS vector) "
            "LIMIT :k"
        ).bindparams(bindparam("kbs", expanding=True))
        with session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    statement,
                    {
                        "q": _vector_literal(vector),
                        "kbs": list(knowledge_base_ids),
                        "k": int(top_k),
                    },
                )
                .mappings()
                .all()
            )
        results: list[tuple[DocumentChunk, float]] = []
        for row in rows:
            chunk = _chunk_from_mapping(row)
            results.append((chunk, float(row["score"])))
        return results

    def update(self, entity: Embedding) -> Embedding:
        """更新向量并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmEmbedding, entity.id)
            if row is None:
                return embedding_to_domain(embedding_to_orm(entity))
            row.chunk_id = entity.chunk_id
            row.model = entity.model
            row.dimensions = entity.dimensions
            row.vector = [float(item) for item in entity.vector]
            session.flush()
            return embedding_to_domain(row)

    def delete(self, entity: Embedding) -> None:
        """删除向量。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmEmbedding, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlAgentKnowledgeRepository:
    """基于 SQLAlchemy 的 AgentKnowledge 绑定仓储（``agent_knowledge`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentKnowledge | None:
        """按主键获取绑定，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentKnowledge, entity_id)
            return agent_knowledge_to_domain(row) if row is not None else None

    def add(self, entity: AgentKnowledge) -> AgentKnowledge:
        """新增绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = agent_knowledge_to_orm(entity)
            session.add(row)
            session.flush()
            return agent_knowledge_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[AgentKnowledge]:
        """按等值条件列出绑定（``scope`` 叠加租户过滤；绑定表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentKnowledge)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentKnowledge, field) == value)
            statement = apply_scope(statement, OrmAgentKnowledge, scope)
            rows = session.execute(statement).scalars().all()
            return [agent_knowledge_to_domain(row) for row in rows]

    def list_by_agent_version(self, agent_version_id: str) -> builtins.list[AgentKnowledge]:
        """列出某 AgentVersion 绑定的全部 KnowledgeBase（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentKnowledge)
                .where(OrmAgentKnowledge.agent_version_id == agent_version_id)
                .order_by(OrmAgentKnowledge.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [agent_knowledge_to_domain(row) for row in rows]

    def update(self, entity: AgentKnowledge) -> AgentKnowledge:
        """更新绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentKnowledge, entity.id)
            if row is None:
                return agent_knowledge_to_domain(agent_knowledge_to_orm(entity))
            row.agent_version_id = entity.agent_version_id
            row.knowledge_base_id = entity.knowledge_base_id
            row.enabled = entity.enabled
            row.config = dict(entity.config) if entity.config is not None else None
            session.flush()
            return agent_knowledge_to_domain(row)

    def delete(self, entity: AgentKnowledge) -> None:
        """删除绑定。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentKnowledge, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
