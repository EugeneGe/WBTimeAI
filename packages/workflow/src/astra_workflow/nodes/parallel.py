"""``PARALLEL`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §4 / N-P2-02 / WR-2）。

``config`` 约定键：``{branches: list[node_key], max_parallel?（只收窄）}``。

执行口径（**冻结**）：

1. 解析分支列表（``node_key`` 列表）；
2. **上限判定**：``len(branches) > max_parallel`` → **立即抛**
   ``DomainError(RESOURCE_LIMIT_EXCEEDED)``，**不静默排队**（WR-2）；
   ``config.max_parallel`` 与引擎默认取 **较小值**（**只收窄**，§9-f）；
3. ``ConcurrencyGuard.acquire(len(branches))`` → 分支并发 → ``release``（``finally``）；
4. 每个分支经 ``NodeContext.dispatcher`` 分派，**各产生独立 ``node_run``**。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain.constants import DEFAULT_MAX_PARALLEL

from ..domain import NODE_TYPE_PARALLEL, WorkflowNode
from ..engine.ports import ConcurrencyGuard, NullConcurrencyGuard
from ..engine.variables import VariableContext
from .base import NodeResult

__all__ = ["ParallelNode"]


class ParallelNode:
    """``PARALLEL`` 节点执行器（**有界并发**，超限即抛）。"""

    type = NODE_TYPE_PARALLEL

    def __init__(
        self,
        *,
        concurrency: ConcurrencyGuard | None = None,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        use_threads: bool = True,
    ) -> None:
        """初始化。

        Args:
            concurrency: 并发守卫（缺省 :class:`NullConcurrencyGuard`）。
            max_parallel: 引擎侧并发上限（``ConcurrencyConfig.max_parallel``）。
            use_threads: 是否以线程池并发执行分支；``False`` 时按序执行（便于确定性单测）。
        """
        self._concurrency: ConcurrencyGuard = (
            concurrency if concurrency is not None else NullConcurrencyGuard()
        )
        self._max_parallel = max_parallel if max_parallel > 0 else DEFAULT_MAX_PARALLEL
        self._use_threads = use_threads

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """并发执行各分支。

        Raises:
            DomainError: 分支数超过 ``max_parallel``（``RESOURCE_LIMIT_EXCEEDED``）；
                分支缺失 / 未装配分派器（``VALIDATION_ERROR`` / ``CONFIGURATION_ERROR``）。
        """
        if ctx is None or getattr(ctx, "dispatcher", None) is None:
            raise DomainError(
                "PARALLEL 节点需要携带 dispatcher 的 NodeContext",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "dispatcher_missing", "node_key": node.node_key},
            )

        config = dict(node.config or {})
        branches = self._branches(config, var_ctx)
        limit = self._limit(config)

        if len(branches) > limit:
            raise DomainError(
                f"PARALLEL 分支数超过并发上限：{len(branches)} > {limit}",
                code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                data={
                    "reason": "parallel_limit_exceeded",
                    "node_key": node.node_key,
                    "branches": len(branches),
                    "max_parallel": limit,
                },
            )

        self._concurrency.acquire(len(branches))
        try:
            outputs = self._run_branches(branches, var_ctx, ctx, limit)
        finally:
            self._concurrency.release(len(branches))
        return NodeResult.success({"branches": outputs})

    # -- 内部 ---------------------------------------------------------------

    def _branches(self, config: dict[str, Any], var_ctx: VariableContext) -> list[str]:
        """解析分支 ``node_key`` 列表。"""
        raw = var_ctx.resolve_value(config.get("branches"))
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raise DomainError(
                "PARALLEL 节点 branches 必须为 node_key 列表",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_branches"},
            )
        return [str(item) for item in raw if str(item)]

    def _limit(self, config: dict[str, Any]) -> int:
        """计算生效并发上限（``config.max_parallel`` 与引擎默认取**较小值**）。"""
        declared = config.get("max_parallel")
        limit = self._max_parallel
        if declared is not None:
            try:
                limit = min(limit, int(declared))
            except (TypeError, ValueError) as error:
                raise DomainError(
                    "PARALLEL 节点 max_parallel 必须为整数",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={"reason": "invalid_max_parallel", "value": declared},
                ) from error
        return max(1, limit)

    def _run_branches(
        self,
        branches: list[str],
        var_ctx: VariableContext,
        ctx: Any,
        limit: int,
    ) -> dict[str, Any]:
        """执行全部分支并聚合输出。"""

        def dispatch(key: str) -> tuple[str, NodeResult]:
            return key, ctx.dispatch(key, var_ctx, ctx)

        if not branches:
            return {}
        if not self._use_threads or len(branches) == 1:
            return {key: result.output for key, result in (dispatch(key) for key in branches)}
        workers = max(1, min(len(branches), limit))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(dispatch, branches))
        return {key: result.output for key, result in results}
