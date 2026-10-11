"""``SkillResolver``（Skill 解析实现；RP-01；W2 裁定 R5 / T2-08 / T2-09；
**W3 裁定 §19 · T2-09.1 绑定驱动补齐**）。

- 结构化契合 runtime ``reserved.skill_resolver.SkillResolver`` Protocol
  （``resolve(query: SkillQuery) -> list[ResolvedSkill]``，**签名不变**）；
- 真实实现落 ``astra_skill``（**不落 runtime**，保 runtime 抽象包不变量），经**组合根注入**；
- **解析策略（W3 裁定 §19.2.2 冻结）**：

  1. **候选集（绑定门）**：``query.agent_version_id`` 非空且已注入 ``bindings_provider`` →
     候选 ＝ ``bindings_provider(query.agent_version_id)``（该版本**已启用**绑定对应的
     生效 ``LoadedSkill``）；否则回落 ``registry.list()``（旧路径零回归）；
  2. **相关度（分词 / 整词）**：对 ``query.text`` 按非词字符切词（``\\w`` + CJK），保留
     ``len >= 2`` 的 token；**tokens 为空 → 命中（返回全部候选）**；否则 **任一 token
     命中**候选的整词集合（``name`` / ``description`` / ``category`` 同法切词）即命中；
     **整词判定**（``tok == word``）防 ``pdf`` 误命中 ``pdfx``；
  3. **排序 / 截断**：保持按 ``name`` 升序（不改既有排序 golden），取前 ``limit``。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_domain`` + 本包 ``registry``）；**不** import
   ``astra_agent`` / ORM（守 R2 §2.1「``skill→agent`` 不建」）——绑定经**组合根注入**的
   ``bindings_provider`` 回调提供。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from astra_domain import ResolvedSkill, SkillQuery

from .manifest import LoadedSkill, SkillResourceSpec
from .registry import SkillRegistry

__all__ = ["SkillResolver"]

#: 分词器（非「词字符 / CJK 统一表意」的连续段为分隔；W3 裁定 §19.2.2）。
_TOKEN_SPLIT = re.compile(r"[^\w\u4e00-\u9fff]+")

#: 最小 token 长度（过滤单字符噪声）。
_MIN_TOKEN_LENGTH = 2


def _tokenize(text: str) -> list[str]:
    """把文本切为小写 token（长度 ``>= 2``；保持出现顺序）。"""
    return [
        token
        for token in _TOKEN_SPLIT.split((text or "").lower())
        if len(token) >= _MIN_TOKEN_LENGTH
    ]


def _skill_words(loaded: LoadedSkill) -> set[str]:
    """某 Skill 的**整词集合**（``name`` / ``description`` / ``category`` 同法切词）。"""
    manifest = loaded.manifest
    words: set[str] = set()
    for field in (manifest.name, manifest.description, manifest.category):
        words.update(_tokenize(str(field)))
    return words


def _matches(loaded: LoadedSkill, tokens: list[str]) -> bool:
    """整词匹配（``tokens`` 为空即全匹配；否则任一 token ∈ 整词集合）。"""
    if not tokens:
        return True
    words = _skill_words(loaded)
    return any(token in words for token in tokens)


class SkillResolver:
    """Skill 解析器（RP-01 真实实现；绑定驱动 + 分词 / 整词匹配）。

    Args:
        registry: Skill 注册表（解析**生效版本**）。
        max_skills: 未显式指定 ``query.limit`` 时的默认上限。
        bindings_provider: 可选注入——``(agent_version_id) -> list[LoadedSkill]``，由**组合根**
            提供该版本**已启用**绑定对应的 ``LoadedSkill``；缺省 ``None`` 时回落注册表全量。
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        max_skills: int = 5,
        bindings_provider: Callable[[str], list[LoadedSkill]] | None = None,
    ) -> None:
        self._registry = registry
        self._max_skills = max_skills
        self._bindings_provider = bindings_provider

    @property
    def has_bindings_provider(self) -> bool:
        """是否已注入绑定解析回调（供装配 / 断言）。"""
        return self._bindings_provider is not None

    def resolve(self, query: SkillQuery) -> list[ResolvedSkill]:
        """按查询解析可用技能（无匹配返回空列表）。

        算法见模块 docstring（绑定门 → 分词 / 整词 → 按 ``name`` 排序截断）。

        Args:
            query: 解析请求（``text`` / ``workspace_id`` / ``limit`` / ``agent_version_id``）。

        Returns:
            :class:`~astra_domain.ports.ResolvedSkill` 列表（按 ``name`` 排序）。
        """
        text = query.text or ""
        candidates = self._candidates(query)
        tokens = _tokenize(text)
        matched = [loaded for loaded in candidates if _matches(loaded, tokens)]
        matched.sort(key=lambda loaded: loaded.name)
        limit = query.limit if query.limit and query.limit > 0 else self._max_skills
        return [
            ResolvedSkill(
                name=loaded.manifest.name,
                description=loaded.manifest.description,
                content=loaded.instructions,
                version=loaded.manifest.version,
            )
            for loaded in matched[:limit]
        ]

    def _candidates(self, query: SkillQuery) -> list[LoadedSkill]:
        """候选集：绑定门（``agent_version_id`` + 已注入 provider）→ 否则注册表全量。"""
        if query.agent_version_id and self._bindings_provider is not None:
            return list(self._bindings_provider(query.agent_version_id))
        return list(self._registry.list())

    def resources(self, name: str, version: str | None = None) -> list[SkillResourceSpec]:
        """返回某 Skill 的资源清单（``version`` 为空时取生效版本）。"""
        if version is not None:
            loaded = self._registry.get(name, version)
        else:
            loaded = self._registry.resolve(name)
        return list(loaded.resources) if loaded is not None else []
