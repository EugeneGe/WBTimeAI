"""Approval 仓储接口（**仅 Protocol**，零 ORM；W4 / T2-26）。

对应 ORM 表：``approval``（随迁移 ``0010`` 建于 2a；**零迁移**）。领域模型
:class:`astra_domain.approval.Approval`。

🔴 设计 §2.15.1 / W4 裁定 R9：SQL 实现落 ``astra_security.repositories``
   （``astra_security`` 自带仓储目录——能力包内 SQL 例外）；``astra_domain``
   保持**零框架依赖**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..approval import Approval

__all__ = ["ApprovalRepository"]


@runtime_checkable
class ApprovalRepository(Protocol):
    """审批仓储接口（新增 / 读取 / 更新 / 列待决议）。"""

    def add(self, approval: Approval) -> Approval:
        """新增审批记录并返回。"""
        ...

    def get(self, approval_id: str) -> Approval | None:
        """按主键获取审批记录，不存在返回 ``None``。"""
        ...

    def update(self, approval: Approval) -> Approval:
        """更新审批记录并返回。"""
        ...

    def list_pending(self, *, tenant_id: str | None = None) -> list[Approval]:
        """列出待决议（``PENDING``）的审批记录（可按租户过滤；按 ``created_at`` 升序）。"""
        ...

    def get_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Approval | None:
        """取 ``(subject_type, subject_ref)`` 的**最近一条**审批记录（``created_at`` 降序）。

        供 ``HUMAN_APPROVAL`` 节点重入**幂等**判定（T2-26）；无则 ``None``。
        """
        ...
