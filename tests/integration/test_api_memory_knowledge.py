"""API 层一等回归：``/memory`` + ``/knowledge``（W6 / T2-35 · F-3 提升）。

由 W6 独立验证探针 ``tests/integration/test_qa_w6_api_probes.py`` **提升**为仓内一等回归——
补齐 W6 独立验证发现的**仓内 API 级穿透缺口**（原仅前端 msw mock，无真实 API 用例）。

覆盖（真实 ``create_app`` + 真实 SQLite，``session_factory`` 与 API 同库）：

- **Memory**：
  - ``GET /api/v1/memory`` 走**真实** ``MemoryStore``（预置记忆可召回；**证伪「恒空」**）；
  - 响应走**统一响应壳** ``{code,message,data,request_id}``；
  - ``DELETE /api/v1/memory/{id}`` 命中 → ``204``；二次 → ``404``（**证伪「恒 404」**）；
  - **跨租户** API 不可见（隔离 I-2 / I-3）；
  - 组合根经真实 lifespan **注入真实** ``MemoryManager``（补 F28 型缺口）；
- **Knowledge**：``POST/GET /knowledge/bases``、``POST /knowledge/search`` 走响应壳且可用。

🔴 PG 无本机环境 → 仅 SQLite（与社区默认部署同实现）。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id

# -- 支撑 --------------------------------------------------------------------


def _shell_data(resp: Any) -> Any:
    """取统一响应壳的 ``data``（``{code,message,data,request_id}``）；非壳原样返回。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def _assert_shell(resp: Any) -> dict[str, Any]:
    """断言成功响应为统一响应壳，返回其体。"""
    body = resp.json()
    assert isinstance(body, dict), f"响应非壳对象：{body}"
    assert set(body.keys()) >= {"code", "message", "data", "request_id"}, f"非统一响应壳：{body}"
    return body


def _default_tenant_id(session_factory: Any) -> str:
    """取默认租户标识（与 ``/auth/register`` 落库口径一致）。"""
    from astra_identity import build_identity_services

    return str(build_identity_services(session_factory).tenants.ensure_default().id)


def _seed_memory(
    session_factory: Any,
    *,
    tenant_id: str,
    content: str,
    kind: str = "LONG_TERM",
    scope_type: str = "user",
    scope_id: str = "user-test",
    visibility: str = "private",
) -> str:
    """经真实 ORM 预置一条记忆，返回其 id。"""
    from astra_database import session_scope
    from astra_database.models.memory import Memory as OrmMemory

    memory_id = generate_id()
    with session_scope(session_factory) as session:
        session.add(
            OrmMemory(
                id=memory_id,
                tenant_id=tenant_id,
                kind=kind,
                scope_type=scope_type,
                scope_id=scope_id,
                visibility=visibility,
                content=content,
                memory_type="fact",
                importance=1.0,
                confidence=1.0,
            )
        )
    return memory_id


def _ensure_sqlite_fts(session_factory: Any) -> None:
    """建 external-content FTS5 虚表 + 触发器（``create_all`` 不含迁移专属虚表 ``0013``）。"""
    import sqlalchemy as sa

    engine = session_factory.kw["bind"]  # type: ignore[attr-defined]
    ddl = [
        "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunk_fts USING fts5("
        "content, content='document_chunk', content_rowid='rowid')",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ai AFTER INSERT ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ad AFTER DELETE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_au AFTER UPDATE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
    ]
    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(sa.text(statement))


def _seed_document_chunk(session_factory: Any, *, knowledge_base_id: str, content: str) -> str:
    """经真实仓储预置 1 文档 + 1 分块（触发 FTS 索引），返回 ``document_id``。"""
    from astra_knowledge import (
        Document,
        DocumentChunk,
        SqlDocumentChunkRepository,
        SqlDocumentRepository,
    )

    tenant_id = _default_tenant_id(session_factory)
    document = SqlDocumentRepository(session_factory).add(
        Document(
            id=generate_id(),
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            title="QA 回归文档",
            source_type="text",
            status="READY",
        )
    )
    SqlDocumentChunkRepository(session_factory).add(
        DocumentChunk(
            id=generate_id(),
            document_id=document.id,
            ordinal=0,
            content=content,
            meta={"format": "text"},
        )
    )
    return document.id


# -- Memory ------------------------------------------------------------------


def test_api_memory_reads_real_store(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``GET /memory`` 命真实存储（预置记忆可召回）——证伪「恒空」；并验证响应壳。"""
    tenant_id = _default_tenant_id(session_factory)
    _seed_memory(session_factory, tenant_id=tenant_id, content="QA 回归：真实存储可见")

    resp = client.get("/api/v1/memory", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = _assert_shell(resp)
    contents = [item["content"] for item in body["data"]]
    assert (
        "QA 回归：真实存储可见" in contents
    ), f"真实存储记忆未召回（疑走 NullMemoryStore）：{contents}"


def test_api_memory_delete_then_404(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """删除命中 → 204；二次删除 → 404——证伪「恒 404」。"""
    tenant_id = _default_tenant_id(session_factory)
    memory_id = _seed_memory(session_factory, tenant_id=tenant_id, content="QA 回归：待删除")

    first = client.delete(f"/api/v1/memory/{memory_id}", headers=auth_headers)
    assert first.status_code == 204, first.text

    after = client.get("/api/v1/memory", headers=auth_headers)
    assert memory_id not in [item["id"] for item in _shell_data(after)]

    second = client.delete(f"/api/v1/memory/{memory_id}", headers=auth_headers)
    assert second.status_code == 404, f"二次删除应 404，实得 {second.status_code}"


def test_api_memory_cross_tenant_invisible(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
    session_factory: Any,
) -> None:
    """其他租户的记忆在 API 层**不可见**（隔离 I-2 / I-3）。"""
    from astra_identity import build_identity_services

    other_tenant_id = str(
        build_identity_services(session_factory).tenants.ensure_tenant("acme", "Acme").id
    )
    _seed_memory(session_factory, tenant_id=other_tenant_id, content="其他租户私有记忆")

    resp = client.get("/api/v1/memory", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert "其他租户私有记忆" not in [
        item["content"] for item in _shell_data(resp)
    ], "跨租户 API 泄漏！"


def test_composition_root_injects_real_memory_manager(client: Any) -> None:
    """组合根经真实 lifespan **注入真实** ``MemoryManager``（补 F28 型缺口）。"""
    from astra_memory import MemoryManager
    from astra_runtime.reserved import NullMemoryManager

    runtime = client.app.state.services.runtime
    memory_manager = runtime.execution_manager._memory_manager  # noqa: SLF001 - 装配接线断言
    assert memory_manager is not None, "组合根应注入 memory_manager（否则记忆段恒空）"
    assert isinstance(memory_manager, MemoryManager), f"注入非真实实现：{type(memory_manager)}"
    assert not isinstance(memory_manager, NullMemoryManager)
    assert hasattr(memory_manager, "extract"), "真实实现应含 Rich 面 extract"


# -- Knowledge ---------------------------------------------------------------


def test_api_knowledge_base_crud_via_shell(client: Any, auth_headers: dict[str, str]) -> None:
    """``POST/GET /knowledge/bases`` 走统一响应壳且可用。"""
    created = client.post(
        "/api/v1/knowledge/bases",
        headers=auth_headers,
        json={"name": "QA 回归库", "description": "F-3"},
    )
    assert created.status_code == 201, created.text
    created_body = _assert_shell(created)
    kb_id = created_body["data"]["id"]
    assert created_body["data"]["name"] == "QA 回归库"

    listed = client.get("/api/v1/knowledge/bases", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert kb_id in [item["id"] for item in _shell_data(listed)]

    detail = client.get(f"/api/v1/knowledge/bases/{kb_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert _shell_data(detail)["id"] == kb_id


def test_api_knowledge_search_reads_real_store(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``POST /knowledge/search`` 走**真实存储**（非 Null）：预置分块可召回。

    - 走统一响应壳 ``{code,message,data,request_id}``；
    - ``mode == "keyword"``（SQLite FTS5 路），命中预置分块内容（证伪「恒空 / Null 检索器」）。
    """
    created = client.post(
        "/api/v1/knowledge/bases",
        headers=auth_headers,
        json={"name": "QA 检索库"},
    )
    assert created.status_code == 201, created.text
    kb_id = _shell_data(created)["id"]

    _ensure_sqlite_fts(session_factory)
    _seed_document_chunk(
        session_factory,
        knowledge_base_id=kb_id,
        content="AstraAi 知识检索：F-3 真实存储命中验证",
    )

    resp = client.post(
        "/api/v1/knowledge/search",
        headers=auth_headers,
        json={"query": "AstraAi 知识检索", "knowledge_base_id": kb_id, "top_k": 5},
    )
    assert resp.status_code == 200, resp.text
    data = _assert_shell(resp)["data"]
    assert data["mode"] == "keyword"
    assert data["hits"], "检索未命中（疑走 Null 检索器 / 空存储）"
    assert any("知识检索" in hit["content"] for hit in data["hits"])


def test_api_knowledge_documents_read_write_via_shell(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """文档登记（写）→ 列表（读）走真实存储 + 响应壳（非 Null）。"""
    created = client.post(
        "/api/v1/knowledge/bases",
        headers=auth_headers,
        json={"name": "QA 文档库"},
    )
    assert created.status_code == 201, created.text
    kb_id = _shell_data(created)["id"]

    document = client.post(
        f"/api/v1/knowledge/bases/{kb_id}/documents",
        headers=auth_headers,
        json={"title": "F-3 文档", "source_type": "text"},
    )
    assert document.status_code == 201, document.text
    doc_body = _assert_shell(document)
    doc_id = doc_body["data"]["id"]
    assert doc_body["data"]["status"] == "PENDING"

    listed = client.get(f"/api/v1/knowledge/bases/{kb_id}/documents", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert doc_id in [item["id"] for item in _shell_data(listed)]


def test_api_knowledge_cross_tenant_404(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
) -> None:
    """跨租户访问他租户知识库 → 404（隔离 I-1）。"""
    created = client.post(
        "/api/v1/knowledge/bases",
        headers=other_tenant_headers,
        json={"name": "他租户库"},
    )
    assert created.status_code == 201, created.text
    kb_id = _shell_data(created)["id"]

    peek = client.get(f"/api/v1/knowledge/bases/{kb_id}", headers=auth_headers)
    assert peek.status_code == 404, f"跨租户应 404，实得 {peek.status_code}"
