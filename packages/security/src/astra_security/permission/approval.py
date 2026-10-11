"""``ApprovalService``——基础审批机制（W4 / T2-26，**零迁移**；设计 §2.10 / W4 裁定 §3.4）。

职责（**冻结 API**）：

- :meth:`request`：发起审批（落 ``PENDING``；emit ``ApprovalRequested``）；
- :meth:`decide`：决议（``APPROVED`` / ``REJECTED``；emit ``ApprovalDecided``）；
- :meth:`expire_due`：过期扫描（``expires_at <= now`` → ``EXPIRED``；emit ``ApprovalDecided``）；
- :meth:`get`：读取。

**结构化实现** :class:`astra_domain.ApprovalGateway`（``HUMAN_APPROVAL`` 节点以关键字调用，
参数名一致），由**组合根**注入 ``HumanApprovalNode``。

🔴 表 ``approval`` 随迁移 ``0010``（2a）建，本服务**零迁移**；
   ``event_bus`` 为空则**仅持久化、不发事件**；``clock`` 为 **fake clock 注入点**。
🔴 事件类经**函数内延迟导入** ``astra_event``（``astra_security`` 的 pyproject 未声明
   ``astra-event``；延迟导入避免新增顶层依赖，且无环）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import Approval, ApprovalRepository, ApprovalStatus

__all__ = ["ApprovalService"]


def _default_clock() -> datetime:
    """默认时钟（UTC now）。"""
    return datetime.now(UTC)


class ApprovalService:
    """基础审批机制服务（落库 + 状态机 + 事件）。"""

    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        event_bus: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化。

        Args:
            repository: 审批仓储（领域 Protocol；SQL 实现由组合根注入）。
            event_bus: 事件总线（``EventBus`` Protocol：``publish``）；``None`` → 不发事件。
            clock: 时钟（fake clock 注入点）；缺省 ``datetime.now(timezone.utc)``。
        """
        self._repository = repository
        self._event_bus = event_bus
        self._clock: Callable[[], datetime] = clock or _default_clock

    # -- ApprovalGateway ----------------------------------------------------

    def request(
        self,
        *,
        subject_type: str,
        subject_ref: str,
        payload: dict[str, Any] | None = None,
        requested_by: str | None = None,
        expires_at: datetime | None = None,
        tenant_id: str | None = None,
    ) -> Approval:
        """发起一条审批请求并挂起（落 ``PENDING`` + emit ``ApprovalRequested``）。

        Args:
            subject_type: 主体类型（``tool`` / ``mcp`` / ``workflow_node``）。
            subject_ref: 主体引用（``workflow_node`` 时为 ``workflow_run_id:node_key``）。
            payload: 审批载荷。
            requested_by: 发起人用户标识。
            expires_at: 到期时间（``None`` = 不过期）。
            tenant_id: 所属租户标识（``approval.tenant_id`` 非空）。

        Returns:
            已落库的 :class:`~astra_domain.Approval`（``PENDING``）。

        Raises:
            DomainError: ``subject_type`` / ``subject_ref`` 为空（``VALIDATION_ERROR``）。
        """
        if not subject_type:
            raise DomainError(
                "审批主体类型不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "subject_type"},
            )
        if not subject_ref:
            raise DomainError(
                "审批主体引用不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "subject_ref"},
            )
        approval = Approval(
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_ref=subject_ref,
            requested_by=requested_by,
            status=str(ApprovalStatus.PENDING),
            payload=dict(payload or {}),
            expires_at=expires_at,
        )
        saved = self._repository.add(approval)
        self._emit_requested(saved)
        return saved

    # -- 决议 / 过期 --------------------------------------------------------

    def decide(
        self,
        approval_id: str,
        *,
        status: str,
        decided_by: str | None,
        now: datetime | None = None,
    ) -> Approval:
        """对审批作出决议（``APPROVED`` / ``REJECTED``；emit ``ApprovalDecided``）。

        Args:
            approval_id: 审批标识。
            status: 决议状态（``APPROVED`` / ``REJECTED``）。
            decided_by: 决议人用户标识。
            now: 决议时间（``None`` = 注入时钟当前值）。

        Returns:
            已更新的 :class:`~astra_domain.Approval`。

        Raises:
            DomainError: 审批不存在（``NOT_FOUND``）/ 非决议状态（``VALIDATION_ERROR``）/
                非法状态转移（``VALIDATION_ERROR``）。
        """
        target = self._coerce_decision(status)
        approval = self._repository.get(approval_id)
        if approval is None:
            raise DomainError(
                "审批不存在",
                code=ErrorCode.NOT_FOUND,
                data={"approval_id": approval_id},
            )
        approval.decide(status=target, decided_by=decided_by, now=now or self._clock())
        updated = self._repository.update(approval)
        self._emit_decided(updated)
        return updated

    def expire_due(self, *, now: datetime | None = None) -> list[Approval]:
        """扫描待决议审批，把已到期的置为 ``EXPIRED``（emit ``ApprovalDecided``）。

        Args:
            now: 当前时间（``None`` = 注入时钟当前值）。

        Returns:
            本次置为过期的审批列表（按 ``created_at`` 升序）。
        """
        at = now or self._clock()
        expired: list[Approval] = []
        for approval in self._repository.list_pending():
            if not approval.is_due(now=at):
                continue
            approval.expire(now=at)
            updated = self._repository.update(approval)
            self._emit_decided(updated)
            expired.append(updated)
        return expired

    def get(self, approval_id: str) -> Approval | None:
        """按主键读取审批记录。"""
        return self._repository.get(approval_id)

    def find_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Approval | None:
        """按 ``(subject_type, subject_ref)`` 取最近一条审批记录（重入幂等用）。"""
        return self._repository.get_by_subject_ref(
            subject_type=subject_type,
            subject_ref=subject_ref,
        )

    # -- 内部 ---------------------------------------------------------------

    @staticmethod
    def _coerce_decision(status: str | ApprovalStatus) -> ApprovalStatus:
        """把决议状态归一为 ``APPROVED`` / ``REJECTED``。

        Raises:
            DomainError: 非决议状态（``VALIDATION_ERROR``）。
        """
        try:
            target = status if isinstance(status, ApprovalStatus) else ApprovalStatus(str(status))
        except ValueError as exc:
            raise DomainError(
                f"非法审批决议状态：{status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"status": str(status)},
            ) from exc
        if target not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise DomainError(
                f"非法审批决议状态：{status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"status": str(status)},
            )
        return target

    def _emit_requested(self, approval: Approval) -> None:
        """emit ``ApprovalRequested``（无总线 → 静默跳过）。"""
        if self._event_bus is None:
            return
        from astra_event import ApprovalRequested

        self._event_bus.publish(
            ApprovalRequested.create(
                approval_id=approval.id,
                subject_type=approval.subject_type,
                subject_ref=approval.subject_ref,
                requested_by=approval.requested_by,
            )
        )

    def _emit_decided(self, approval: Approval) -> None:
        """emit ``ApprovalDecided``（无总线 → 静默跳过）。"""
        if self._event_bus is None:
            return
        from astra_event import ApprovalDecided

        self._event_bus.publish(
            ApprovalDecided.create(
                approval_id=approval.id,
                status=str(approval.status),
                decided_by=approval.decided_by,
            )
        )
