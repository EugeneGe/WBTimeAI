"""``astra_memory`` 领域层单元测试（W6 / T2-32）。

覆盖：

- 值域枚举 / 常量（``MemoryKind`` / ``ScopeType`` / ``Visibility`` / ``RelationType``）；
- 校验函数（合法 → 归一字面值；非法 → ``DomainError(VALIDATION_ERROR)``）；
- 领域实体（:class:`Memory` / :class:`MemoryRelation`）默认值与 ``assert_valid`` / TTL 判定；
- ORM ↔ 领域映射（**可空时间戳 / 向量保持 ``None``**，承接 ``P2-51``）。

🔴 纯领域单测（零 DB / 零 Web）；ORM 映射用例直接实例化声明式行（不落库）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from astra_core import DomainError, ErrorCode
from astra_database.models.memory import Memory as OrmMemory
from astra_database.models.memory import MemoryRelation as OrmMemoryRelation
from astra_memory import (
    MEMORY_KIND_AGENT,
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_PROJECT,
    MEMORY_KIND_SHORT_TERM,
    MEMORY_KIND_USER,
    RELATION_TYPE_DERIVED_FROM,
    RELATION_TYPE_RELATED,
    RELATION_TYPE_SUPERSEDES,
    SCOPE_TYPE_AGENT,
    SCOPE_TYPE_CONVERSATION,
    SCOPE_TYPE_PROJECT,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_TENANT,
    VISIBILITY_WORKSPACE,
    MemoryKind,
    MemoryRelation,
    RelationType,
    ScopeType,
    Visibility,
    assert_memory_kind,
    assert_relation_type,
    assert_scope_type,
    assert_visibility,
)
from astra_memory.repositories.mappers import (
    memory_relation_to_domain,
    memory_relation_to_orm,
    memory_to_domain,
    memory_to_orm,
)

from tests.fixtures.memory import DEFAULT_TENANT, make_memory, make_relation

# -- 值域枚举 / 常量 ----------------------------------------------------------


def test_memory_kind_values_are_frozen() -> None:
    """``MemoryKind`` 五类字面值冻结（W6 裁定 §9-1）。"""
    assert MemoryKind.values() == (
        MEMORY_KIND_SHORT_TERM,
        MEMORY_KIND_LONG_TERM,
        MEMORY_KIND_PROJECT,
        MEMORY_KIND_AGENT,
        MEMORY_KIND_USER,
    )


def test_scope_visibility_relation_values() -> None:
    """``ScopeType`` / ``Visibility`` / ``RelationType`` 值域齐全。"""
    assert set(ScopeType.values()) == {
        SCOPE_TYPE_USER,
        SCOPE_TYPE_AGENT,
        SCOPE_TYPE_PROJECT,
        SCOPE_TYPE_WORKSPACE,
        SCOPE_TYPE_CONVERSATION,
    }
    assert set(Visibility.values()) == {
        VISIBILITY_PRIVATE,
        VISIBILITY_WORKSPACE,
        VISIBILITY_TENANT,
    }
    assert set(RelationType.values()) == {
        RELATION_TYPE_SUPERSEDES,
        RELATION_TYPE_DERIVED_FROM,
        RELATION_TYPE_RELATED,
    }


# -- 校验函数 ----------------------------------------------------------------


def test_assert_memory_kind_accepts_str_and_enum() -> None:
    """合法 ``kind``（字符串 / 枚举）→ 归一化字面值。"""
    assert assert_memory_kind(MEMORY_KIND_LONG_TERM) == MEMORY_KIND_LONG_TERM
    assert assert_memory_kind(MemoryKind.USER) == MEMORY_KIND_USER


def test_assert_memory_kind_rejects_unknown() -> None:
    """非法 ``kind`` → ``DomainError(VALIDATION_ERROR)``。"""
    with pytest.raises(DomainError) as exc:
        assert_memory_kind("NOPE")
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert exc.value.data.get("field") == "kind"


def test_assert_scope_visibility_relation_reject_unknown() -> None:
    """``scope_type`` / ``visibility`` / ``relation`` 非法值均被拒。"""
    for fn, field in (
        (assert_scope_type, "scope_type"),
        (assert_visibility, "visibility"),
        (assert_relation_type, "relation"),
    ):
        with pytest.raises(DomainError) as exc:
            fn("bogus")
        assert exc.value.code == ErrorCode.VALIDATION_ERROR
        assert exc.value.data.get("field") == field


# -- 领域实体 ----------------------------------------------------------------


def test_memory_assert_valid_ok_and_invalid() -> None:
    """合法记忆通过校验；非法 ``scope_type`` → 抛错。"""
    make_memory().assert_valid()
    bad = make_memory(scope_type="nope")
    with pytest.raises(DomainError):
        bad.assert_valid()


def test_memory_is_expired_semantics() -> None:
    """``expires_at=None`` 永不过期；未来不过期；过去已过期。"""
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert make_memory(expires_at=None).is_expired(now) is False
    assert make_memory(expires_at=now + timedelta(minutes=1)).is_expired(now) is False
    assert make_memory(expires_at=now - timedelta(minutes=1)).is_expired(now) is True
    assert make_memory(expires_at=now).is_expired(now) is True


def test_memory_relation_assert_valid() -> None:
    """关系合法通过；非法关系类型抛错。"""
    valid = make_relation(from_memory_id="a", to_memory_id="b", relation=RELATION_TYPE_SUPERSEDES)
    valid.assert_valid()
    with pytest.raises(DomainError):
        MemoryRelation(from_memory_id="a", to_memory_id="b", relation="nope").assert_valid()


# -- ORM ↔ 领域映射 -----------------------------------------------------------


def test_mapper_roundtrip_preserves_vector_and_expiry() -> None:
    """领域 → ORM → 领域往返保留向量 / 到期时间（``_opt_dt`` / ``_opt_vector``）。"""
    expires = datetime(2031, 5, 1, tzinfo=UTC)
    entity = make_memory(
        content="往返内容",
        vector=[1, 2, 3],
        expires_at=expires,
        importance=0.7,
        confidence=0.6,
    )
    row = memory_to_orm(entity)
    assert row.vector == [1.0, 2.0, 3.0]
    assert row.expires_at == expires

    restored = memory_to_domain(row)
    assert restored.id == entity.id
    assert restored.content == "往返内容"
    assert restored.vector == [1.0, 2.0, 3.0]
    assert restored.expires_at == expires
    assert restored.importance == pytest.approx(0.7)


def test_mapper_keeps_none_for_nullable_fields() -> None:
    """🔴 可空字段 ``None`` 必须保持 ``None``（禁 ``_dt()`` 误填，``P2-51``）。"""
    entity = make_memory(vector=None, expires_at=None)
    row = memory_to_orm(entity)
    assert row.vector is None
    assert row.expires_at is None

    # 直接以可空列全为 None 的声明式行驱动映射，断言不回退当前时间。
    bare = OrmMemory(
        id=entity.id,
        tenant_id=DEFAULT_TENANT,
        workspace_id=None,
        kind=MEMORY_KIND_LONG_TERM,
        scope_type=SCOPE_TYPE_USER,
        scope_id="u1",
        visibility=VISIBILITY_PRIVATE,
        content="空值记忆",
        memory_type="fact",
        importance=0.0,
        confidence=0.0,
        source_run_id=None,
        vector=None,
        expires_at=None,
    )
    mapped = memory_to_domain(bare)
    assert mapped.vector is None
    assert mapped.expires_at is None


def test_mapper_relation_roundtrip() -> None:
    """``memory_relation`` ORM ↔ 领域往返。"""
    entity = make_relation(from_memory_id="a", to_memory_id="b")
    row = memory_relation_to_orm(entity)
    assert isinstance(row, OrmMemoryRelation)
    assert row.from_memory_id == "a"
    assert row.to_memory_id == "b"
    restored = memory_relation_to_domain(row)
    assert restored.from_memory_id == "a"
    assert restored.to_memory_id == "b"
    assert restored.relation == RELATION_TYPE_RELATED
