"""``MemoryStore`` 抽象往返 + 能力选路单元测试（W6 / T2-34）。

覆盖：

- :func:`resolve_memory_vector_capability`：SQLite（非 PG）确定性解析为 ``False``；
- :func:`build_memory_store`：``vector_search=false`` → :class:`SqlMemoryStore`；
  ``vector_search=true`` → :class:`VectorMemoryStore`；
- ``SqlMemoryStore`` 往返：``upsert`` 插入 / 覆盖 + ``search`` 隔离过滤；
- ``delete`` 跨租户不可删；``VectorMemoryStore`` 写向量 + 余弦重排；
- ``build_memory_manager``：结构化契合 RP-03 ``MemoryManager`` Protocol。

🔴 SQLite 侧真实往返（``session_factory`` 夹具）；PG 路受环境门控。
"""

from __future__ import annotations

from datetime import timedelta

from astra_common.time import utcnow
from astra_domain import MemoryQuery
from astra_memory import (
    MEMORY_KIND_LONG_TERM,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_WORKSPACE,
    SqlMemoryStore,
    VectorMemoryStore,
    build_memory_manager,
    build_memory_store,
    resolve_memory_vector_capability,
)

from tests.fixtures.memory import DEFAULT_TENANT, make_memory


def test_resolve_vector_capability_sqlite_is_false(session_factory: object) -> None:
    """SQLite（非 postgresql 方言）→ 自动解析为 ``False``（确定性探测，非 try/except）。"""
    assert resolve_memory_vector_capability(explicit=None, session_factory=session_factory) is False
    # 显式覆盖优先。
    assert resolve_memory_vector_capability(explicit=True, session_factory=session_factory) is True


def test_build_memory_store_selects_sql_when_disabled(session_factory: object) -> None:
    """``vector_search=false`` → :class:`SqlMemoryStore`。"""
    store = build_memory_store(session_factory=session_factory, vector_search=False)
    assert isinstance(store, SqlMemoryStore)
    assert not isinstance(store, VectorMemoryStore)


def test_build_memory_store_selects_vector_when_enabled(session_factory: object) -> None:
    """``vector_search=true`` → :class:`VectorMemoryStore`。"""
    store = build_memory_store(
        session_factory=session_factory,
        vector_search=True,
        embedding_dimensions=4,
        embedder=lambda text: [1.0, 0.0, 0.0, 0.0],
    )
    assert isinstance(store, VectorMemoryStore)


def test_sql_memory_store_roundtrip_and_upsert(session_factory: object) -> None:
    """``SqlMemoryStore``：插入 → search 命中 → 同 id 覆盖 → 内容更新。"""
    store = build_memory_store(session_factory=session_factory, vector_search=False)
    created = store.upsert(
        make_memory(
            content="往返内容",
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    found = store.search(tenant_id=DEFAULT_TENANT, scope_type=SCOPE_TYPE_WORKSPACE, scope_id="ws1")
    assert [item.content for item in found] == ["往返内容"]

    created.content = "更新后内容"
    store.upsert(created)
    found_again = store.search(
        tenant_id=DEFAULT_TENANT, scope_type=SCOPE_TYPE_WORKSPACE, scope_id="ws1"
    )
    assert [item.content for item in found_again] == ["更新后内容"]


def test_sql_memory_store_delete_is_tenant_scoped(session_factory: object) -> None:
    """``delete`` 强制租户过滤：跨租户不可删。"""
    from astra_memory import build_memory_repositories

    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    memory = store.upsert(make_memory(content="删除目标", visibility=VISIBILITY_WORKSPACE))
    store.delete(memory.id, tenant_id="tenant-other")
    assert repositories.memories.get(memory.id) is not None
    store.delete(memory.id, tenant_id=DEFAULT_TENANT)
    assert repositories.memories.get(memory.id) is None


def test_sql_memory_store_search_excludes_expired(session_factory: object) -> None:
    """``search`` 排除已到期记忆（TTL 过滤先于排序）。"""
    store = build_memory_store(session_factory=session_factory, vector_search=False)
    store.upsert(make_memory(content="过期", expires_at=utcnow() - timedelta(hours=1)))
    store.upsert(make_memory(content="有效"))
    found = store.search(tenant_id=DEFAULT_TENANT)
    assert [item.content for item in found] == ["有效"]


def test_vector_memory_store_writes_and_reranks(session_factory: object) -> None:
    """``VectorMemoryStore``：写入向量 + 按余弦相似度把最相关记忆排到首位。"""

    def embedder(text: str) -> list[float]:
        vector = [0.0, 0.0, 0.0, 0.0]
        for index, char in enumerate(text):
            vector[index % 4] += (ord(char) % 7) + 1.0
        return vector

    store = build_memory_store(
        session_factory=session_factory,
        vector_search=True,
        embedding_dimensions=4,
        embedder=embedder,
    )
    store.upsert(
        make_memory(
            content="咖啡",
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    store.upsert(
        make_memory(
            content="完全不相干的另一段文字",
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    ranked = store.search(
        tenant_id=DEFAULT_TENANT,
        scope_type=SCOPE_TYPE_WORKSPACE,
        scope_id="ws1",
        text="咖啡",
    )
    assert ranked[0].content == "咖啡"


def test_build_memory_manager_is_structurally_compatible(session_factory: object) -> None:
    """``build_memory_manager`` 产物结构化契合 RP-03 ``MemoryManager``。"""
    from astra_runtime.reserved.memory_manager import MemoryManager as MemoryManagerProtocol

    manager = build_memory_manager(
        session_factory=session_factory, settings=None, vector_search=False
    )
    assert isinstance(manager, MemoryManagerProtocol)
    assert manager.recall(MemoryQuery(tenant_id=DEFAULT_TENANT)) == []


def test_build_memory_manager_remember_and_recall(session_factory: object) -> None:
    """经组合工厂装配的管理器可 ``remember`` → ``recall`` 往返（真实 SQLite）。"""
    from astra_domain import MemoryRecord

    manager = build_memory_manager(
        session_factory=session_factory, settings=None, vector_search=False
    )
    manager.remember(
        MemoryRecord(
            key="agg-m1",
            content="工厂装配内容",
            tenant_id=DEFAULT_TENANT,
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    records = manager.recall(MemoryQuery(text="工厂", tenant_id=DEFAULT_TENANT, workspace_id="ws1"))
    assert [record.content for record in records] == ["工厂装配内容"]
