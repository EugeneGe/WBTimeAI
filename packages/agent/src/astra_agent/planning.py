"""RP-05 ``Planner`` 起步实现（W4 裁定 §6.3 / R10；**落能力包，不落 runtime**）。

背景（W4 裁定 F7 / F9）：

- ``Planner`` Protocol + ``NullPlanner`` 位于 ``astra_runtime.reserved.planner``，
  签名**一字不改**（回归闸 ``tests/unit/test_runtime_reserved_null.py``）；
- Runtime 目前**无 Planner 消费点**（``AgentRuntime`` 不调用 ``plan(...)``），故 W4
  **暂不接线**进 Runtime，只交付**起步实现**并由**组合根**持有（承接 ``C2-18``）；
- 落点选择：任务卡要求「与 Workflow 编排分离」——ReAct 规划属 **Agent 自治**，
  非 Workflow 固定流程，故落 ``astra_agent``（**不落 runtime**、不落 workflow）。

实现口径（起步）：

- **纯文本切分**，不引模型、不引第三方依赖；
- 优先按**换行**切分（编号 / 列表条目），其次按**句末标点**切分；
- ``max_steps`` 有界（默认 ``DEFAULT_PLAN_MAX_STEPS = 10``），防无界计划；
- ``context["tools"]`` 给出可用工具名时，按**字面命中**为步骤挂 ``tool_name``
  （**不猜测参数**，``arguments`` 恒为空字典）。
"""

from __future__ import annotations

import re

from astra_domain import Plan, PlanStep

__all__ = [
    "DEFAULT_PLAN_MAX_STEPS",
    "SENTENCE_SPLIT_PATTERN",
    "SimplePlanner",
    "build_simple_planner",
]


#: 默认计划最大步数（**有界**）。
DEFAULT_PLAN_MAX_STEPS = 10

#: 句末标点切分（中英文）。
SENTENCE_SPLIT_PATTERN: re.Pattern[str] = re.compile(r"(?<=[。；;!！?？])\s*")

#: 行首编号 / 列表符号（用于剥离后作为步骤描述）。
_BULLET_PATTERN: re.Pattern[str] = re.compile(r"^\s*(?:[-*•]|\d+[.、)])\s*")


class SimplePlanner:
    """起步规划器（**结构化兼容** ``astra_runtime.reserved.planner.Planner`` Protocol）。

    实现 ``plan(goal, context) -> Plan``（签名与 Protocol **逐字一致**），供组合根
    持有 / 未来经 ``AgentRuntime.build(planner=...)`` 注入（加性可选形参，承接 ``C2-18``）。

    Attributes:
        max_steps: 计划最大步数（有界）。
    """

    def __init__(self, *, max_steps: int = DEFAULT_PLAN_MAX_STEPS) -> None:
        """初始化规划器。

        Args:
            max_steps: 计划最大步数（``<=0`` 时回退默认值）。
        """
        self.max_steps = max_steps if max_steps > 0 else DEFAULT_PLAN_MAX_STEPS

    def plan(self, goal: str, context: dict[str, object] | None = None) -> Plan:
        """为目标产出执行计划（起步：纯文本切分，**有界**）。

        Args:
            goal: 目标描述文本。
            context: 可选上下文（``tools``: 可用工具名列表）。

        Returns:
            :class:`Plan`（无有效步骤时返回**仅含 goal 的空计划**，同 ``NullPlanner``）。
        """
        steps = self._split(goal, context or {})
        return Plan(goal=goal, steps=steps)

    # -- 内部 ---------------------------------------------------------------

    def _split(self, goal: str, context: dict[str, object]) -> list[PlanStep]:
        """将目标文本切分为有界步骤列表。"""
        candidates = self._candidates(goal)
        tools = self._tool_names(context)
        steps: list[PlanStep] = []
        for text in candidates:
            if len(steps) >= self.max_steps:
                break
            description = _BULLET_PATTERN.sub("", text).strip()
            if not description:
                continue
            steps.append(
                PlanStep(
                    description=description,
                    tool_name=self._match_tool(description, tools),
                    arguments={},
                )
            )
        return steps

    def _candidates(self, goal: str) -> list[str]:
        """产出候选步骤文本（换行优先 → 句末标点 → 整句）。"""
        text = (goal or "").strip()
        if not text:
            return []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            return lines
        sentences = [
            item.strip() for item in SENTENCE_SPLIT_PATTERN.split(lines[0]) if item.strip()
        ]
        return sentences if len(sentences) > 1 else [lines[0]]

    @staticmethod
    def _tool_names(context: dict[str, object]) -> tuple[str, ...]:
        """从上下文提取可用工具名（``context["tools"]``）。"""
        raw = context.get("tools")
        if isinstance(raw, (list, tuple)):
            return tuple(str(item) for item in raw if str(item))
        if isinstance(raw, str) and raw:
            return (raw,)
        return ()

    @staticmethod
    def _match_tool(description: str, tools: tuple[str, ...]) -> str | None:
        """按**字面命中**为步骤挂工具名（长名优先；未命中返回 ``None``）。"""
        for tool in sorted(tools, key=len, reverse=True):
            if tool in description:
                return tool
        return None


def build_simple_planner(*, max_steps: int = DEFAULT_PLAN_MAX_STEPS) -> SimplePlanner:
    """构造起步 :class:`SimplePlanner`（供**组合根**持有）。

    Args:
        max_steps: 计划最大步数。

    Returns:
        :class:`SimplePlanner`。
    """
    return SimplePlanner(max_steps=max_steps)
