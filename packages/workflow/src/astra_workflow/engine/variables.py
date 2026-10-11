"""Workflow 变量上下文（``node_key`` 命名空间；W4 裁定 §6.4 #1）。

约定：

- 节点 ``output`` 以 ``node_key`` **命名空间**注入：``VariableContext.outputs[node_key]``；
- 节点 ``input`` 表达式引用 ``${node_key.path}`` / ``${input.path}``，
  经**白名单安全求值器**解析（**禁 ``eval`` / 禁任意代码**）；
- 解析为**纯字典/下标遍历**：不支持属性访问、不支持下标字面量以外的语法。

🔴 本模块**零框架**（无 ORM / Web / Runtime），可在纯单测中驱动。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "INPUT_NAMESPACE",
    "REF_PATTERN",
    "VariableContext",
    "resolve_reference",
]

#: 运行入参所在的命名空间名（``${input.xxx}``）。
INPUT_NAMESPACE = "input"

#: 引用语法：``${root.path.to.field}``（**仅**标识符与点号）。
REF_PATTERN: re.Pattern[str] = re.compile(
    r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}"
)

_MISSING = object()


@dataclass
class VariableContext:
    """Workflow 运行期变量上下文（可序列化，供挂起 / 续跑重建）。

    Attributes:
        inputs: 运行入参（``${input.xxx}``）。
        outputs: 已完成节点的产出，键为 ``node_key``（``${node_key.xxx}``）。
    """

    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    # -- 写入 ---------------------------------------------------------------

    def set_output(self, node_key: str, output: dict[str, Any] | None) -> None:
        """以 ``node_key`` 命名空间写入节点产出。"""
        self.outputs[node_key] = dict(output or {})

    def get_output(self, node_key: str) -> dict[str, Any]:
        """读取某节点的产出；不存在返回空字典。"""
        return dict(self.outputs.get(node_key) or {})

    # -- 解析 ---------------------------------------------------------------

    def root(self, namespace: str) -> dict[str, Any]:
        """返回某命名空间的根字典（``input`` 或某 ``node_key``）。"""
        if namespace == INPUT_NAMESPACE:
            return self.inputs
        return self.outputs.get(namespace, {})

    def resolve(self, template: str) -> Any:
        """解析模板字符串中的全部引用。

        - 若整个字符串**恰为一个**引用（如 ``"${n1.text}"``）→ 返回**原对象**（保留类型）；
        - 否则按字符串插值拼接（如 ``"hi ${n1.name}"``）。

        Args:
            template: 含 ``${...}`` 引用的模板。

        Returns:
            解析后的值（引用缺失时以空字符串插值 / ``None`` 原样返回）。
        """
        matches = list(REF_PATTERN.finditer(template))
        if not matches:
            return template
        if len(matches) == 1 and matches[0].group(0) == template:
            return self._lookup(matches[0].group(1), matches[0].group(2))
        return REF_PATTERN.sub(lambda m: _stringify(self._lookup(m.group(1), m.group(2))), template)

    def resolve_value(self, value: Any) -> Any:
        """**递归**解析任意值中的引用（``str`` / ``dict`` / ``list`` / 标量）。"""
        if isinstance(value, str):
            return self.resolve(value)
        if isinstance(value, dict):
            return {key: self.resolve_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve_value(item) for item in value]
        return value

    def _lookup(self, namespace: str, path: str) -> Any:
        """按 ``namespace`` + 点号路径取值；缺失返回 ``None``。"""
        current: Any = self.root(namespace)
        for segment in path.split(".") if path else []:
            if not segment:
                continue
            if isinstance(current, dict):
                current = current.get(segment, _MISSING)
            else:  # 非字典继续取路径 → 视为缺失（**禁属性访问**）
                return None
            if current is _MISSING:
                return None
        return current

    # -- 快照（挂起 / 续跑 / 重放） ------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """序列化为快照字典（写入 ``workflow_run.output``，供续跑重建）。"""
        return {
            "inputs": dict(self.inputs),
            "outputs": {key: dict(value) for key, value in self.outputs.items()},
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any] | None) -> VariableContext:
        """由快照字典重建（``run.output`` → 变量上下文，W4 裁定 §3.5）。"""
        payload = data or {}
        return cls(
            inputs=dict(payload.get("inputs") or {}),
            outputs={
                str(key): dict(value or {}) for key, value in (payload.get("outputs") or {}).items()
            },
        )


def resolve_reference(context: VariableContext, template: str) -> Any:
    """模块级便捷函数：在 ``context`` 中解析 ``template``。"""
    return context.resolve(template)


def _stringify(value: Any) -> str:
    """将引用值转为可插值字符串（``None`` → 空串）。"""
    return "" if value is None else str(value)
