"""``LOOP`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §4「有界迭代」）。

``config`` 约定键：``{max_iterations, body, until?}``。

执行口径（**冻结**）：

- ``body``：循环体的 ``node_key``（字符串或列表），逐轮经 ``NodeContext.dispatcher``
  分派（**每轮各产生独立 ``node_run``**）；
- ``max_iterations``：**强制有界**（缺省 ``DEFAULT_MAX_ITERATIONS = 10``，§9-e）；
  并受**绝对上限** ``ABSOLUTE_MAX_ITERATIONS`` 约束（防配置放大为无界循环）；
- ``until``：可选**白名单**表达式（复用 :func:`condition.evaluate_expression`，
  **禁 ``eval``**）；为真即**提前退出**。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain.constants import DEFAULT_MAX_ITERATIONS

from ..domain import NODE_TYPE_LOOP, WorkflowNode
from ..engine.variables import VariableContext
from .base import NodeResult
from .condition import evaluate_expression

__all__ = ["ABSOLUTE_MAX_ITERATIONS", "LoopNode"]


#: ``LOOP`` 迭代次数的**绝对上限**（防配置把循环放大为无界）。
ABSOLUTE_MAX_ITERATIONS = 1000


class LoopNode:
    """``LOOP`` 节点执行器（**有界迭代**，``max_iterations`` 强制）。"""

    type = NODE_TYPE_LOOP

    def __init__(self, *, default_max_iterations: int = DEFAULT_MAX_ITERATIONS) -> None:
        """初始化。

        Args:
            default_max_iterations: 未声明 ``config.max_iterations`` 时的默认值。
        """
        self._default = (
            default_max_iterations if default_max_iterations > 0 else DEFAULT_MAX_ITERATIONS
        )

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """执行循环体（**有界**）。

        Raises:
            DomainError: ``body`` 缺失 / ``max_iterations`` 非法或超绝对上限
                （``VALIDATION_ERROR``）；未装配分派器（``CONFIGURATION_ERROR``）。
        """
        if ctx is None or getattr(ctx, "dispatcher", None) is None:
            raise DomainError(
                "LOOP 节点需要携带 dispatcher 的 NodeContext",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "dispatcher_missing", "node_key": node.node_key},
            )

        config = dict(node.config or {})
        body = self._body(config, var_ctx)
        max_iterations = self._max_iterations(config)
        until = config.get("until")

        iterations = 0
        for _ in range(max_iterations):
            for key in body:
                ctx.dispatch(key, var_ctx, ctx)
            iterations += 1
            if until and self._should_stop(str(until), var_ctx, config):
                break

        return NodeResult.success({"iterations": iterations})

    # -- 内部 ---------------------------------------------------------------

    def _body(self, config: dict[str, Any], var_ctx: VariableContext) -> list[str]:
        """解析循环体 ``node_key`` 列表。"""
        raw = var_ctx.resolve_value(config.get("body"))
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise DomainError(
                "LOOP 节点 body 必须为非空 node_key 列表",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_body"},
            )
        return [str(item) for item in raw if str(item)]

    def _max_iterations(self, config: dict[str, Any]) -> int:
        """解析并校验 ``max_iterations``（**有界**）。"""
        raw = config.get("max_iterations", self._default)
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise DomainError(
                "LOOP 节点 max_iterations 必须为整数",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_max_iterations", "value": raw},
            ) from error
        if value <= 0:
            raise DomainError(
                "LOOP 节点 max_iterations 必须为正整数",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_max_iterations", "value": value},
            )
        if value > ABSOLUTE_MAX_ITERATIONS:
            raise DomainError(
                f"LOOP 节点 max_iterations 超过绝对上限：{value} > {ABSOLUTE_MAX_ITERATIONS}",
                code=ErrorCode.VALIDATION_ERROR,
                data={
                    "reason": "max_iterations_too_large",
                    "value": value,
                    "cap": ABSOLUTE_MAX_ITERATIONS,
                },
            )
        return value

    def _should_stop(self, until: str, var_ctx: VariableContext, config: dict[str, Any]) -> bool:
        """按白名单表达式判定是否提前退出。"""
        data: dict[str, Any] = {"input": var_ctx.inputs, **var_ctx.outputs}
        raw_whitelist = config.get("whitelist")
        whitelist = (
            [str(item) for item in raw_whitelist]
            if isinstance(raw_whitelist, (list, tuple))
            else None
        )
        return bool(evaluate_expression(until, data, whitelist=whitelist))
