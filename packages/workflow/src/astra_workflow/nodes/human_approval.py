"""``HUMAN_APPROVAL`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §3.4 / §6.4 #6）。

``config`` 约定键：``{subject_ref?, expires_at?, payload?}``。

执行口径（**冻结**）：

- 经 ``ApprovalGateway``（``astra_domain.ports`` 的 **Protocol**）发起审批，
  **不 import ``astra_security``**（跨包契约由组合根注入真实 ``ApprovalService``）；
- ``subject_type`` 固定为 ``workflow_node``；``subject_ref`` 缺省
  ``{workflow_run_id}:{node_key}``（W4 裁定 §6.4 #6）；
- 返回 ``NodeResult(status=WAITING_APPROVAL)`` → 引擎置 ``workflow_run`` 为
  ``WAITING_APPROVAL``（**非终态**）并**挂起返回**；
- 决议后由 ``WorkflowService.resume`` 续跑（``ApprovalDecided`` → 续跑，§3.4）。

**重入幂等（T2-26 resume-aware）**：``WorkflowEngine.resume`` 会以 ``attempt + 1`` **重入**本节点。
故 :meth:`execute` 先经 ``ApprovalGateway.find_by_subject_ref`` 查既有审批，据此**幂等收敛**：

- 无既有审批 → 发起新审批并挂起；
- ``APPROVED`` → **直接放行**（返回成功，**不再发起第 2 条**）；
- ``PENDING`` → 防御性继续挂起（返回同一 ``approval_id``）；
- ``REJECTED`` / ``EXPIRED`` → 抛 :class:`DomainError`（正常由组合根订阅处理器置 run ``FAILED``）。

🔴 ``approval`` 表随迁移 ``0010``（2a）建立，本节点**零迁移**。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import ApprovalGateway, ApprovalStatus

from ..domain import NODE_TYPE_HUMAN_APPROVAL, WorkflowNode
from ..engine.variables import VariableContext
from .base import NodeResult

__all__ = ["APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE", "HumanApprovalNode"]


#: ``HUMAN_APPROVAL`` 节点发起的审批主体类型（设计 §2.10 / W4 裁定 §6.4 #6）。
APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE = "workflow_node"


def _approval_id(approval: Any) -> str | None:
    """取审批记录的 ``id``（``None`` 安全，供 ``workflow_node_run.approval_id`` 关联）。"""
    value = getattr(approval, "id", None)
    return str(value) if value is not None else None


class HumanApprovalNode:
    """``HUMAN_APPROVAL`` 节点执行器（挂起等待人工决议；**重入幂等**）。"""

    type = NODE_TYPE_HUMAN_APPROVAL

    def __init__(
        self,
        gateway: ApprovalGateway | None,
        *,
        subject_type: str = APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE,
    ) -> None:
        """初始化。

        Args:
            gateway: 审批网关（组合根注入 ``ApprovalService``）；``None`` 时执行期
                **显式报错**（``CONFIGURATION_ERROR``，不静默放行）。
            subject_type: 审批主体类型（默认 ``workflow_node``）。
        """
        self._gateway = gateway
        self._subject_type = subject_type

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """发起审批并挂起；**重入时按既有审批状态幂等收敛**。

        Raises:
            DomainError: 未装配审批网关（``CONFIGURATION_ERROR``）；或重入时既有审批
                ``REJECTED`` / ``EXPIRED``（``VALIDATION_ERROR``，防御）。
        """
        if self._gateway is None:
            raise DomainError(
                "HUMAN_APPROVAL 节点未装配 ApprovalGateway",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "approval_gateway_missing", "node_key": node.node_key},
            )

        config = dict(node.config or {})
        run_id = str(getattr(ctx, "run_id", "") or "")
        subject_ref = str(
            var_ctx.resolve_value(config.get("subject_ref"))
            or config.get("subject_ref")
            or f"{run_id}:{node.node_key}"
        )

        # 重入幂等：先查既有审批（WorkflowEngine.resume 以 attempt+1 重入本节点）。
        existing = self._gateway.find_by_subject_ref(
            subject_type=self._subject_type,
            subject_ref=subject_ref,
        )
        if existing is not None:
            return self._resolve_existing(existing, node)

        payload = var_ctx.resolve_value(config.get("payload") or {})
        if not isinstance(payload, dict):
            payload = {"value": payload}

        approval = self._gateway.request(
            subject_type=self._subject_type,
            subject_ref=subject_ref,
            payload=payload,
            requested_by=getattr(ctx, "requested_by", None),
            expires_at=config.get("expires_at"),
            tenant_id=getattr(ctx, "tenant_id", None),
        )
        return NodeResult.suspended_for_approval(_approval_id(approval))

    def _resolve_existing(self, existing: Any, node: WorkflowNode) -> NodeResult:
        """按既有审批状态收敛（幂等；**不重复发起**）。

        Raises:
            DomainError: 既有审批 ``REJECTED`` / ``EXPIRED``（``VALIDATION_ERROR``）。
        """
        status = str(getattr(existing, "status", "") or "")
        approval_id = _approval_id(existing)
        if status == str(ApprovalStatus.APPROVED):
            return NodeResult.success({"approval_id": approval_id, "status": status})
        if status == str(ApprovalStatus.PENDING):
            return NodeResult.suspended_for_approval(approval_id)
        raise DomainError(
            f"审批未通过，工作流不可继续：{status or 'UNKNOWN'}",
            code=ErrorCode.VALIDATION_ERROR,
            data={
                "reason": "approval_not_granted",
                "status": status,
                "node_key": node.node_key,
                "approval_id": approval_id,
            },
        )
