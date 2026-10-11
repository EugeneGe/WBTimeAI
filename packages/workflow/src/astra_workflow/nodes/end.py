"""``END`` 节点（W4 / T2-22；设计 §2.5）。

``config`` 约定键：``{}``（**终态汇聚**，无副作用）。

``END`` 为图的**汇聚点**：引擎遇到即视为该路径结束（不产出、不驱动后继）。
"""

from __future__ import annotations

from typing import Any

from ..domain import NODE_TYPE_END, WorkflowNode
from ..engine.variables import VariableContext
from .base import NodeResult

__all__ = ["EndNode"]


class EndNode:
    """``END`` 节点执行器（终态汇聚，无副作用）。"""

    type = NODE_TYPE_END

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """返回空产出的成功结果。"""
        return NodeResult.success({})
