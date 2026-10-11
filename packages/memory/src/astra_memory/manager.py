"""``MemoryManager``（能力包 Rich；RP-03 面 + Rich 面；设计 §2.7 / §5.4；W6 / T2-33）。

**RP-03 面（签名冻结，结构化契合 runtime ``MemoryManager`` Protocol）**：

- :meth:`remember` / :meth:`recall`；

**Rich 面（应用层调用；F-f 冻结）**：

- :meth:`extract`（Run 结束抽取 + 落库 + 建关系；**应用层触发**，B2）；
- :meth:`forget`（按租户显式删除 + 级联删关系，§13-e）；
- :meth:`prune`（TTL 清理）。

🔴 **不 import ``astra_runtime``**（能力包不依赖 runtime，保无环；W6 裁定 §9-14）；
结构化契合 = 实现 ``remember`` / ``recall`` 即满足 ``isinstance(x, MemoryManager)``。
🔴 异常隔离：抽取失败 / 超限**不影响 Run 终态**（返回空列表 + WARN）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from astra_domain import RUN_TRIGGER_USER, MemoryQuery, MemoryRecord
from astra_model import ChatMessage

from .domain.entities import Memory, MemoryRelation
from .domain.kinds import (
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_SHORT_TERM,
    MEMORY_KIND_USER,
    RELATION_TYPE_SUPERSEDES,
    SCOPE_TYPE_AGENT,
    SCOPE_TYPE_CONVERSATION,
    SCOPE_TYPE_PROJECT,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_WORKSPACE,
)
from .extractor import MemoryExtractor
from .recall import MemoryRecall
from .store import MemoryStore

__all__ = ["MemoryManager", "DEFAULT_SHORT_TERM_TTL_SECONDS"]

_logger = logging.getLogger("astra_memory.manager")

#: ``SHORT_TERM`` 默认存活时长（秒，24h）；无 ``MemorySettings`` 覆写时使用。
DEFAULT_SHORT_TERM_TTL_SECONDS = 86400


class MemoryManager:
    """记忆管理器（RP-03 面 + Rich 面；能力包实现，由**组合根**注入 runtime）。

    Args:
        store: 记忆存储抽象（``upsert`` / ``search`` / ``delete`` / ``prune``）。
        extractor: LLM 抽取器（``None`` ＝ 不抽取）。
        recall: 召回服务（``None`` ＝ 用 ``store`` 自建默认召回）。
        relation_repository: 关系仓储（``None`` ＝ 不建 / 不级联关系）。
        settings: ``MemorySettings``（duck-typing 读取；可空）。
    """

    def __init__(
        self,
        *,
        store: MemoryStore,
        extractor: MemoryExtractor | None = None,
        recall: MemoryRecall | None = None,
        relation_repository: Any = None,
        settings: Any = None,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._recall = recall or MemoryRecall(store=store)
        self._relation_repository = relation_repository
        self._settings = settings

    # -- RP-03 面（签名冻结） -----------------------------------------------

    def remember(self, record: MemoryRecord) -> None:
        """写入一条记忆（RP-03；按 ``key`` 作为主键 upsert）。

        Raises:
            DomainError: 隔离字段非法（``VALIDATION_ERROR``）。
        """
        memory = self._record_to_memory(record)
        memory.assert_valid()
        self._store.upsert(memory)

    def recall(self, query: MemoryQuery) -> list[MemoryRecord]:
        """按查询召回记忆（RP-03；无匹配返回空列表）。"""
        return self._recall.recall(query)

    # -- Rich 面（应用层调用；F-f 冻结） ------------------------------------

    def extract(
        self,
        *,
        run: Any,
        messages: Sequence[ChatMessage],
        tenant_id: str | None = None,
        user_id: str | None = None,
        trigger: str | None = None,
        enabled: bool | None = None,
        token_budget: int | None = None,
        now: datetime | None = None,
    ) -> list[Memory]:
        """从 Run 的对话抽取候选记忆并落库（+ 建 ``supersedes`` 关系）。

        Args:
            run: 触发的 ``AgentRun``（提供 ``id`` / ``tenant_id`` / ``agent_id`` /
                ``conversation_id`` / ``user_id`` / ``trigger``）。
            messages: 对话消息。
            tenant_id: 租户标识（缺省取 ``run.tenant_id``；为空 → 跳过）。
            user_id: 触发用户标识（缺省取 ``run.user_id``）。
            trigger: 触发来源（缺省取 ``run.trigger``）。
            enabled: 抽取开关覆盖（``None`` ＝ 取 ``MemorySettings.extraction_enabled``）。
            token_budget: 单次 token 上限覆盖。
            now: 参照时间（缺省 ＝ 当前 UTC）。

        Returns:
            落库后的 ``Memory`` 列表（抽取关闭 / 超限 / 异常 → 空列表）。
        """
        if not self._extraction_enabled(enabled):
            return []
        if self._extractor is None:
            return []

        reference = now or utcnow()
        tenant = tenant_id if tenant_id is not None else getattr(run, "tenant_id", None) or ""
        tenant = str(tenant)
        if not tenant:
            return []
        effective_user = user_id if user_id is not None else getattr(run, "user_id", None)
        effective_trigger = trigger or getattr(run, "trigger", None) or RUN_TRIGGER_USER

        try:
            drafts = self._extractor.extract(
                messages=list(messages),
                settings=self._settings,
                trigger=effective_trigger,
                token_budget=token_budget,
            )
        except Exception as exc:  # noqa: BLE001 - 异常隔离：抽取失败不中断 Run
            _logger.warning("记忆抽取失败（已隔离，不影响 Run 终态）：%s", exc)
            return []

        budget = self._resolve_token_budget(token_budget)
        if self._extractor.last_token_usage > budget:
            _logger.warning(
                "记忆抽取超出 token 上限（used=%s > limit=%s），本次丢弃候选",
                self._extractor.last_token_usage,
                budget,
            )
            return []

        saved: list[Memory] = []
        for draft in drafts:
            memory = self._draft_to_memory(
                draft, run=run, tenant_id=tenant, user_id=effective_user, now=reference
            )
            try:
                stored = self._store.upsert(memory)
            except Exception as exc:  # noqa: BLE001 - 单条落库失败不中断整体抽取
                _logger.warning("记忆落库失败（已隔离）：%s", exc)
                continue
            self._link_supersedes(stored, tenant_id=tenant)
            saved.append(stored)
        return saved

    def forget(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆并**显式**级联删关系（§13-e）。"""
        self._store.delete(memory_id, tenant_id=tenant_id)
        if self._relation_repository is not None:
            self._relation_repository.delete_by_memory(memory_id)

    def prune(self, *, now: datetime | None = None) -> int:
        """清理已到期记忆（TTL / 遗忘），返回删除条数。"""
        return int(self._store.prune(now=now or utcnow()))

    # -- 观测 ---------------------------------------------------------------

    @property
    def last_token_usage(self) -> int:
        """最近一次抽取的 token 用量（无抽取器 → ``0``）。"""
        return int(getattr(self._extractor, "last_token_usage", 0) or 0)

    # -- 内部 ---------------------------------------------------------------

    def _extraction_enabled(self, enabled: bool | None) -> bool:
        """解析抽取开关（显式覆盖优先，否则取 ``MemorySettings.extraction_enabled``）。"""
        if enabled is not None:
            return bool(enabled)
        return bool(getattr(self._settings, "extraction_enabled", True))

    def _resolve_token_budget(self, token_budget: int | None) -> int:
        """解析单次抽取 token 上限（显式覆盖 → ``settings`` → 抽取器默认）。"""
        if token_budget is not None:
            return int(token_budget)
        value = getattr(self._settings, "extraction_token_limit", None)
        if value is not None:
            return int(value)
        return int(getattr(self._extractor, "token_limit", 0) or 0)

    def _record_to_memory(self, record: MemoryRecord) -> Memory:
        """把 RP-03 ``MemoryRecord`` 映射为领域 ``Memory``（缺省补齐合法值）。"""
        return Memory(
            id=record.key or generate_id(),
            tenant_id=record.tenant_id or "",
            workspace_id=record.workspace_id,
            kind=record.kind or MEMORY_KIND_LONG_TERM,
            scope_type=record.scope_type or SCOPE_TYPE_USER,
            scope_id=record.scope_id,
            visibility=record.visibility or VISIBILITY_PRIVATE,
            content=record.content,
            memory_type="",
            importance=float(record.importance or 0.0),
            confidence=0.0,
            source_run_id=record.source_run_id,
            vector=None,
            expires_at=record.expires_at,
        )

    def _draft_to_memory(
        self, draft: Any, *, run: Any, tenant_id: str, user_id: str | None, now: datetime
    ) -> Memory:
        """把抽取候选映射为领域 ``Memory``（按 ``kind`` 派生作用域 / 可见性 / TTL）。"""
        scope_type, scope_id, visibility = self._derive_scope(draft.kind, run=run, user_id=user_id)
        expires_at = None
        if draft.kind == MEMORY_KIND_SHORT_TERM:
            expires_at = now + timedelta(seconds=self._short_term_ttl_seconds())
        return Memory(
            tenant_id=tenant_id,
            workspace_id=getattr(run, "workspace_id", None),
            kind=draft.kind,
            scope_type=scope_type,
            scope_id=scope_id,
            visibility=visibility,
            content=draft.content,
            memory_type=draft.memory_type or "",
            importance=float(draft.importance or 0.0),
            confidence=float(draft.confidence or 0.0),
            source_run_id=getattr(run, "id", None),
            vector=None,
            expires_at=expires_at,
        )

    def _derive_scope(self, kind: str, *, run: Any, user_id: str | None) -> tuple[str, str, str]:
        """按记忆类别派生 ``(scope_type, scope_id, visibility)``。

        - ``USER`` → ``(user, user_id, private)``（**仅本人可见**，R-19）；
        - ``AGENT`` → ``(agent, agent_id, workspace)``；
        - ``PROJECT`` → ``(project, workspace_id|tenant, workspace)``；
        - ``SHORT_TERM`` → ``(conversation, conversation_id|agent_id, workspace)``（带 TTL）；
        - ``LONG_TERM``（默认）→ ``(workspace, workspace_id|agent_id|tenant, workspace)``。
        """
        agent_id = str(getattr(run, "agent_id", "") or "")
        conversation_id = str(getattr(run, "conversation_id", "") or "")
        workspace_id = str(getattr(run, "workspace_id", "") or "")
        tenant_id = str(getattr(run, "tenant_id", "") or "")
        if kind == MEMORY_KIND_USER:
            return SCOPE_TYPE_USER, str(user_id or ""), VISIBILITY_PRIVATE
        if kind == "AGENT":
            return SCOPE_TYPE_AGENT, agent_id or tenant_id, VISIBILITY_WORKSPACE
        if kind == "PROJECT":
            return SCOPE_TYPE_PROJECT, workspace_id or tenant_id, VISIBILITY_WORKSPACE
        if kind == MEMORY_KIND_SHORT_TERM:
            return SCOPE_TYPE_CONVERSATION, conversation_id or agent_id, VISIBILITY_WORKSPACE
        return SCOPE_TYPE_WORKSPACE, workspace_id or agent_id or tenant_id, VISIBILITY_WORKSPACE

    def _short_term_ttl_seconds(self) -> int:
        """``SHORT_TERM`` 存活时长（秒）。"""
        value = getattr(self._settings, "short_term_ttl_seconds", None)
        if value is not None:
            return int(value)
        return DEFAULT_SHORT_TERM_TTL_SECONDS

    def _link_supersedes(self, memory: Memory, *, tenant_id: str) -> None:
        """为**同作用域 + 同类别 + 同内容类型**的不同事实建 ``supersedes`` 关系（§6.1）。

        最小冲突检测：命中的既有记忆中，内容不同者 → 建 ``(new → old, supersedes)``。
        """
        if self._relation_repository is None:
            return
        try:
            peers = self._store.search(
                tenant_id=tenant_id,
                scope_type=memory.scope_type,
                scope_id=memory.scope_id,
                kinds=[memory.kind],
                limit=20,
                now=utcnow(),
            )
        except Exception:  # noqa: BLE001 - 关系建失败不阻断落库
            return
        normalized = " ".join((memory.content or "").lower().split())
        for peer in peers:
            if peer.id == memory.id or peer.memory_type != memory.memory_type:
                continue
            if " ".join((peer.content or "").lower().split()) == normalized:
                continue
            try:
                self._relation_repository.add(
                    MemoryRelation(
                        from_memory_id=memory.id,
                        to_memory_id=peer.id,
                        relation=RELATION_TYPE_SUPERSEDES,
                    )
                )
            except Exception:  # noqa: BLE001 - 唯一键冲突 / 落库失败不阻断
                continue
