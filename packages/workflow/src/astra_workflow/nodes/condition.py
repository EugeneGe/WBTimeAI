"""``CONDITION`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §9-e）。

``config`` 约定键：``{expression, whitelist?, true_branch?, false_branch?}``。

🔴 **禁任意代码**：表达式经 **``ast`` 白名单**解析 + 递归求值（**不使用 ``eval`` /
``exec``**）。起步白名单运算符（W4 裁定 §9-e）：

- 比较：``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=`` / ``in``
- 逻辑：``and`` / ``or`` / ``not``
- 函数：``len`` / ``contains``
- 取值：**仅**裸标识符 + **点号路径**（``n1.score`` / ``input.topic``）——
  经**纯字典遍历**解析，**从不**对对象调用 ``getattr``（故 ``__class__`` 等只取到
  ``None``，无属性泄漏面）

``config.whitelist`` 提供时与内置白名单**取交集**（**只收窄**，不放宽）。
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from typing import Any

from astra_core import DomainError, ErrorCode

from ..domain import NODE_TYPE_CONDITION, WorkflowNode
from ..engine.variables import VariableContext
from .base import NodeResult

__all__ = [
    "DEFAULT_TRUE_BRANCH",
    "DEFAULT_FALSE_BRANCH",
    "DEFAULT_OPERATOR_WHITELIST",
    "ConditionNode",
    "evaluate_expression",
]


#: ``CONDITION`` 默认真分支名（与 ``workflow_edge.condition`` 匹配）。
DEFAULT_TRUE_BRANCH = "true"
#: ``CONDITION`` 默认假分支名。
DEFAULT_FALSE_BRANCH = "false"

#: 起步白名单运算符 / 函数（W4 裁定 §9-e，**冻结**）。
DEFAULT_OPERATOR_WHITELIST: frozenset[str] = frozenset(
    {"==", "!=", "<", "<=", ">", ">=", "and", "or", "not", "in", "contains", "len"}
)

_OPERATOR_BY_NODE: dict[type[ast.AST], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.In: "in",
    # ``not in`` 视为 ``in`` 的否定式，由同一白名单项授权。
    ast.NotIn: "in",
    ast.And: "and",
    ast.Or: "or",
    ast.Not: "not",
}

#: 允许的函数名（**白名单**，与运算符白名单取交集后生效）。
_ALLOWED_FUNCS: frozenset[str] = frozenset({"len", "contains"})

#: 允许的 AST 节点类型（**禁** ``Attribute`` / ``Subscript`` / ``Lambda`` / 推导式等）。
_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Attribute,
        ast.Load,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.List,
        ast.Tuple,
        ast.Set,
        ast.Dict,
        # -- 白名单运算符节点（仅下列九种） -----------------------------------
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.And,
        ast.Or,
        ast.Not,
    }
)

#: 允许的一元运算符（**仅** ``not``；``-`` / ``+`` 等算术**不在**白名单）。
_ALLOWED_UNARYOPS: frozenset[type[ast.unaryop]] = frozenset({ast.Not})


def _effective_whitelist(whitelist: Collection[str] | None) -> frozenset[str]:
    """计算生效白名单（与内置白名单**取交集**，只收窄）。"""
    if not whitelist:
        return DEFAULT_OPERATOR_WHITELIST
    return DEFAULT_OPERATOR_WHITELIST & frozenset(str(item) for item in whitelist)


def _operator_names(node: ast.AST) -> list[str]:
    """提取某 AST 节点涉及的全部运算符 / 函数名。"""
    names: list[str] = []
    if isinstance(node, ast.Compare):
        for op in node.ops:
            name = _OPERATOR_BY_NODE.get(type(op))
            if name:
                names.append(name)
    elif isinstance(node, ast.BoolOp):
        name = _OPERATOR_BY_NODE.get(type(node.op))
        if name:
            names.append(name)
    elif isinstance(node, ast.UnaryOp):
        name = _OPERATOR_BY_NODE.get(type(node.op))
        if name:
            names.append(name)
    elif isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            names.append(func.id)
    return names


def _dotted_path(node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
    """把 ``a.b.c`` 形式的 AST 展开为 ``(root, ("b", "c"))``；非规范形式返回 ``None``。

    🔴 仅接受以 ``ast.Name`` 为根、由 ``ast.Attribute`` 串起的**纯点号路径**；
       路径中混入调用 / 下标 / 其它语法一律拒绝。
    """
    segments: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        attr = current.attr
        if attr.startswith("__") and attr.endswith("__"):
            return None  # dunder 一律拒绝（防御纵深）
        segments.append(attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return current.id, tuple(reversed(segments))


def _validate(tree: ast.AST, allowed: frozenset[str]) -> None:
    """校验 AST 是否**全部**落在白名单内；否则抛 ``DomainError``。

    Raises:
        DomainError: 命中白名单外的语法 / 运算符（``VALIDATION_ERROR``）。
    """
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise DomainError(
                f"CONDITION 表达式含白名单外语法：{type(node).__name__}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "expression_syntax_denied", "node": type(node).__name__},
            )
        if isinstance(node, ast.UnaryOp) and type(node.op) not in _ALLOWED_UNARYOPS:
            raise DomainError(
                "CONDITION 表达式不支持该一元运算符",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "expression_operator_denied", "node": type(node.op).__name__},
            )
        if isinstance(node, ast.Attribute) and _dotted_path(node) is None:
            raise DomainError(
                "CONDITION 表达式仅支持以标识符为根的点号路径",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "expression_syntax_denied", "node": "Attribute"},
            )
        for name in _operator_names(node):
            if name not in allowed:
                raise DomainError(
                    f"CONDITION 表达式含白名单外运算符 / 函数：{name}",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={"reason": "expression_operator_denied", "operator": name},
                )


def _eval(node: ast.AST, data: Mapping[str, Any]) -> Any:
    """递归求值（**无 ``eval``**）。"""
    if isinstance(node, ast.Expression):
        return _eval(node.body, data)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return data.get(node.id)
    if isinstance(node, ast.Attribute):
        parsed = _dotted_path(node)
        if parsed is None:  # pragma: no cover - 已由 _validate 拦截
            raise DomainError("非法属性路径", code=ErrorCode.VALIDATION_ERROR)
        root, segments = parsed
        return _lookup(data.get(root), segments)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):  # pragma: no cover - 已由 _validate 拦截
            raise DomainError("不支持的一元运算符", code=ErrorCode.VALIDATION_ERROR)
        return not _eval(node.operand, data)
    if isinstance(node, ast.BoolOp):
        values = [_eval(value, data) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        return any(values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, data)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = _eval(comparator, data)
            result = _compare(op, left, right)
            if not result:
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if not isinstance(func, ast.Name):  # pragma: no cover - 已由 _validate 拦截
            raise DomainError("非法函数调用", code=ErrorCode.VALIDATION_ERROR)
        args = [_eval(arg, data) for arg in node.args]
        if func.id == "len":
            return len(args[0]) if args else 0
        if func.id == "contains":
            return args[1] in args[0] if len(args) >= 2 else False
        raise DomainError(  # pragma: no cover - 已由 _validate 拦截
            f"未授权函数：{func.id}", code=ErrorCode.VALIDATION_ERROR
        )
    if isinstance(node, ast.List):
        return [_eval(item, data) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(item, data) for item in node.elts)
    if isinstance(node, ast.Set):
        return {_eval(item, data) for item in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _eval(key, data) if key is not None else None: _eval(value, data)
            for key, value in zip(node.keys, node.values, strict=False)
        }
    raise DomainError(  # pragma: no cover - 已由 _validate 拦截
        f"不可求值的语法：{type(node).__name__}", code=ErrorCode.VALIDATION_ERROR
    )


def _compare(op: ast.AST, left: Any, right: Any) -> bool:
    """按白名单比较运算符求值。"""
    if isinstance(op, ast.Eq):
        return bool(left == right)
    if isinstance(op, ast.NotEq):
        return bool(left != right)
    if isinstance(op, ast.Lt):
        return bool(left < right)
    if isinstance(op, ast.LtE):
        return bool(left <= right)
    if isinstance(op, ast.Gt):
        return bool(left > right)
    if isinstance(op, ast.GtE):
        return bool(left >= right)
    if isinstance(op, ast.In):
        return bool(left in right)
    if isinstance(op, ast.NotIn):
        return bool(left not in right)
    raise DomainError(  # pragma: no cover - 已由 _validate 拦截
        "不支持的比较运算符", code=ErrorCode.VALIDATION_ERROR
    )


def _lookup(current: Any, segments: tuple[str, ...]) -> Any:
    """沿点号路径做**纯字典遍历**（非字典即视为缺失，返回 ``None``）。"""
    for segment in segments:
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def evaluate_expression(
    expression: str,
    data: Mapping[str, Any],
    *,
    whitelist: Collection[str] | None = None,
) -> Any:
    """**安全**求值条件表达式（白名单 + ``ast``，**禁 ``eval``**）。

    Args:
        expression: 条件表达式文本。
        data: 可用变量（``node_key`` / ``input`` 命名空间）。
        whitelist: 可选运算符白名单（与内置白名单**取交集**，只收窄）。

    Returns:
        表达式求值结果（通常为 ``bool``）。

    Raises:
        DomainError: 语法错误 / 命中白名单外语法或运算符（``VALIDATION_ERROR``）。
    """
    try:
        tree = ast.parse(str(expression).strip(), mode="eval")
    except SyntaxError as error:
        raise DomainError(
            f"CONDITION 表达式语法错误：{error.msg}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "expression_syntax_error", "expression": expression},
        ) from error
    _validate(tree, _effective_whitelist(whitelist))
    return _eval(tree, data)


class ConditionNode:
    """``CONDITION`` 节点执行器（白名单表达式求值 → 选分支）。"""

    type = NODE_TYPE_CONDITION

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """求值 ``config.expression`` 并产出 ``next_branch``。

        Raises:
            DomainError: 缺少 ``expression`` 或命中白名单外语法（``VALIDATION_ERROR``）。
        """
        config = dict(node.config or {})
        expression = config.get("expression")
        if not expression:
            raise DomainError(
                f"CONDITION 节点缺少 expression：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "missing_expression", "node_key": node.node_key},
            )
        raw_whitelist = config.get("whitelist")
        whitelist: list[str] | None = None
        if isinstance(raw_whitelist, (list, tuple)):
            whitelist = [str(item) for item in raw_whitelist]

        data: dict[str, Any] = {"input": var_ctx.inputs, **var_ctx.outputs}
        truthy = bool(evaluate_expression(str(expression), data, whitelist=whitelist))
        true_branch = str(config.get("true_branch") or DEFAULT_TRUE_BRANCH)
        false_branch = str(config.get("false_branch") or DEFAULT_FALSE_BRANCH)
        branch = true_branch if truthy else false_branch
        return NodeResult.success({"value": truthy, "branch": branch}, next_branch=branch)
