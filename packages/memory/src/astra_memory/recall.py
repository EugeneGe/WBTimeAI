"""隔离维度召回 + 权重排序（``recall``；设计 §2.7 / §3.3；W6 / T2-33）。

- **隔离过滤先于排序**（I-2 / I-3）：先按 ``tenant_id`` + 作用域 + 可见性 + 类别过滤（SQL），
  **再**按权重排序；
- **权重** ``score = importance_weight × importance × similarity × recency``：
  - ``recency``（时效）＝ ``0.5 ** (age_days / half_life)``；
  - ``similarity`` 由可选 ``similarity_provider`` 提供（PG 向量路）；缺省 ＝ ``1.0``
    （SQLite 退化 recency / keyword，无相似度项）；
- **USER 隐私（R-19 / B5）**：非用户触发（``schedule`` / ``event`` / ``webhook``）**不召回
  ``USER``** 且排除 ``private`` 可见性；用户触发时 ``USER`` 仅本人可见。

🔴 本模块**零 Web / ORM**（仅依赖 ``store`` Protocol + 领域实体）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from astra_common.time import ensure_utc, utcnow
from astra_domain import MemoryQuery, MemoryRecord

from .domain.entities import Memory
from .domain.kinds import (
    MEMORY_KIND_AGENT,
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_PROJECT,
    MEMORY_KIND_SHORT_TERM,
    MEMORY_KIND_USER,
    SCOPE_TYPE_AGENT,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_TENANT,
    VISIBILITY_WORKSPACE,
)
from .extractor import NON_USER_TRIGGERS
from .store import MemoryStore

__all__ = ["MemoryRecall", "DEFAULT_RECALL_TOP_K", "DEFAULT_IMPORTANCE_WEIGHT"]

#: 默认召回条数（＝ ``MemorySettings.recall_top_k`` 默认值）。
DEFAULT_RECALL_TOP_K = 10

#: 默认重要度权重系数。
DEFAULT_IMPORTANCE_WEIGHT = 1.0

#: 默认时效半衰期（天）。
DEFAULT_RECENCY_HALF_LIFE_DAYS = 30.0

#: 全部记忆类别（默认召回范围）。
_ALL_KINDS: tuple[str, ...] = (
    MEMORY_KIND_SHORT_TERM,
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_PROJECT,
    MEMORY_KIND_AGENT,
    MEMORY_KIND_USER,
)

#: 候选放大倍数（先多取再按权重截断）。
_CANDIDATE_FACTOR = 4
_CANDIDATE_FLOOR = 50


class MemoryRecall:
    """隔离维度召回器（过滤 + 权重排序 + ``MemoryRecord`` 映射）。

    Args:
        store: 记忆存储抽象。
        top_k: 默认召回条数。
        importance_weight: 重要度权重系数。
        recency_half_life_days: 时效半衰期（天）；``<= 0`` ＝ 时效项恒 ``1.0``。
        similarity_provider: 可选相似度函数（``Memory -> float``；PG 向量路注入）。
    """

    def __init__(
        self,
        *,
        store: MemoryStore,
        top_k: int = DEFAULT_RECALL_TOP_K,
        importance_weight: float = DEFAULT_IMPORTANCE_WEIGHT,
        recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
        similarity_provider: Callable[[Memory], float] | None = None,
    ) -> None:
        self._store = store
        self._top_k = int(top_k)
        self._importance_weight = float(importance_weight)
        self._half_life_days = float(recency_half_life_days)
        self._similarity_provider = similarity_provider

    def recall(self, query: MemoryQuery, *, now: datetime | None = None) -> list[MemoryRecord]:
        """按隔离维度召回并排序，返回 ``MemoryRecord`` 列表（top-k）。

        Args:
            query: RP-03 召回请求（含隔离维度 / 类别 / 文本）。
            now: 参照时间（缺省 ＝ 当前 UTC）。

        Returns:
            已按权重降序排序的 ``MemoryRecord``（``tenant_id`` 为空 → 空列表）。
        """
        tenant_id = (query.tenant_id or "").strip()
        if not tenant_id:
            return []
        reference = now or utcnow()
        non_user = _is_non_user_trigger(query.trigger)
        kinds = _effective_kinds(query.kinds, non_user=non_user)
        if not kinds:
            return []
        limit = int(query.limit) if query.limit and query.limit > 0 else self._top_k
        candidate_limit = max(limit * _CANDIDATE_FACTOR, _CANDIDATE_FLOOR)

        candidates: dict[str, Memory] = {}
        for scope_type, scope_id, visibility in _scopes_for(query, non_user=non_user):
            found = self._store.search(
                tenant_id=tenant_id,
                scope_type=scope_type,
                scope_id=scope_id,
                visibility=visibility,
                kinds=kinds,
                text=(query.text or None),
                limit=candidate_limit,
                now=reference,
            )
            for memory in found:
                candidates.setdefault(memory.id, memory)

        ranked = sorted(
            candidates.values(),
            key=lambda memory: self._weight(memory, reference),
            reverse=True,
        )
        return [_to_record(memory) for memory in ranked[:limit]]

    # -- 内部 ---------------------------------------------------------------

    def _weight(self, memory: Memory, now: datetime) -> float:
        """计算召回权重（``importance_weight × importance × similarity × recency``）。"""
        score = self._importance_weight * float(memory.importance or 0.0)
        score *= _recency_factor(memory.created_at, now, self._half_life_days)
        if self._similarity_provider is not None and memory.vector is not None:
            score *= float(self._similarity_provider(memory))
        return score


def _to_record(memory: Memory) -> MemoryRecord:
    """把领域 ``Memory`` 映射为 RP-03 输出 ``MemoryRecord``。"""
    metadata: dict[str, Any] = {
        "kind": memory.kind,
        "scope_type": memory.scope_type,
        "scope_id": memory.scope_id,
        "visibility": memory.visibility,
        "memory_type": memory.memory_type,
        "importance": float(memory.importance),
        "confidence": float(memory.confidence),
    }
    return MemoryRecord(
        key=memory.id,
        content=memory.content,
        metadata=metadata,
        kind=memory.kind,
        scope_type=memory.scope_type,
        scope_id=memory.scope_id,
        visibility=memory.visibility,
        importance=float(memory.importance),
        tenant_id=memory.tenant_id or "",
        workspace_id=memory.workspace_id,
        source_run_id=memory.source_run_id,
        expires_at=memory.expires_at,
    )


def _is_non_user_trigger(trigger: str | None) -> bool:
    """判断是否**非用户触发**（``None`` / ``user`` 视为用户触发）。"""
    if not trigger:
        return False
    return str(trigger) in NON_USER_TRIGGERS


def _effective_kinds(kinds: list[str] | None, *, non_user: bool) -> list[str]:
    """解析生效类别集合（非用户触发**排除 ``USER``**，B5）。"""
    effective = list(kinds) if kinds else list(_ALL_KINDS)
    if non_user:
        effective = [kind for kind in effective if kind != MEMORY_KIND_USER]
    return effective


def _scopes_for(
    query: MemoryQuery, *, non_user: bool
) -> list[tuple[str | None, str | None, list[str]]]:
    """把 ``MemoryQuery`` 解析为**作用域 → 允许可见性**的检索计划（隔离不变量）。

    - ``(user, user_id)``：用户触发时含 ``private``（**USER 仅本人**）；非用户触发**不含**；
    - ``(agent, agent_id)``：用户触发含 ``private``，非用户触发仅 ``workspace`` / ``tenant``；
    - ``(workspace, workspace_id)``：仅 ``workspace`` / ``tenant``；
    - **末尾恒追加**一条**租户级**检索（仅 ``workspace`` / ``tenant``，**绝不含 ``private``**）——
      保证 ``PROJECT`` / ``LONG_TERM`` 等**非 ``private``** 记忆任何触发下均可召回。
    """
    if non_user:
        broad = [VISIBILITY_WORKSPACE, VISIBILITY_TENANT]
        own = [VISIBILITY_WORKSPACE, VISIBILITY_TENANT]
    else:
        broad = [VISIBILITY_WORKSPACE, VISIBILITY_TENANT]
        own = [VISIBILITY_PRIVATE, VISIBILITY_WORKSPACE, VISIBILITY_TENANT]

    scopes: list[tuple[str | None, str | None, list[str]]] = []
    if not non_user and query.user_id:
        scopes.append((SCOPE_TYPE_USER, query.user_id, own))
    if query.agent_id:
        scopes.append((SCOPE_TYPE_AGENT, query.agent_id, own))
    if query.workspace_id:
        scopes.append((SCOPE_TYPE_WORKSPACE, query.workspace_id, broad))
    # 租户级兜底：不限定作用域（仍强制 tenant_id + 绝不含 private）。
    scopes.append((None, None, broad))
    return scopes


def _recency_factor(created_at: datetime | None, now: datetime, half_life_days: float) -> float:
    """时效因子 ``0.5 ** (age_days / half_life)``（半衰期 ``<= 0`` → ``1.0``）。"""
    if half_life_days <= 0 or created_at is None:
        return 1.0
    reference = ensure_utc(created_at)
    age_days = max(0.0, (now - reference).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / half_life_days))
