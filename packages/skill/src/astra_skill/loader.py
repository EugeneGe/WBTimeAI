"""``SkillLoader``（从某来源目录装载 Skill 包；W2 裁定 R3 §3.3）。

- :meth:`SkillLoader.load_dir`：扫描一个**来源根目录**下的全部 Skill 包（含根目录自身
  即为一个 Skill 包的情形）；每个包经 :func:`astra_skill.manifest.load_skill_package`
  解析；
- **判定口径**：Loader 只负责「从某来源目录装载」，**同名覆盖优先级判定集中在
  ``SkillRegistry``**（R3 §3.3）。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core`` + 本包 ``manifest`` / ``registry``）。
"""

from __future__ import annotations

from pathlib import Path

from .manifest import LoadedSkill, load_skill_package
from .registry import SkillSource

__all__ = ["SkillLoader"]


class SkillLoader:
    """Skill 包目录装载器（按来源装载，不做优先级判定）。"""

    def __init__(self, *, manifest_filename: str = "skill.yaml") -> None:
        self._manifest_filename = manifest_filename

    def load_dir(self, root: Path | str, *, source: SkillSource) -> list[LoadedSkill]:
        """装载 ``root`` 下（含自身）的全部 Skill 包。

        规则（R3 §3.3）：

        1. 若 ``root`` 自身含 ``skill.yaml`` → 作为**单个** Skill 包装载；
        2. 否则扫描 ``root`` 的**一层子目录**，凡含 ``skill.yaml`` 者各装载一个包；
        3. ``root`` 不存在 / 无任何 ``skill.yaml`` → 返回空列表（**不抛错**，便于装配宽松）。

        Args:
            root: 来源根目录。
            source: 来源（``builtin`` / ``plugin`` / ``workspace``）。

        Returns:
            装载出的 :class:`LoadedSkill` 列表（按目录名稳定排序）。
        """
        base = Path(root)
        if not base.is_dir():
            return []
        if (base / self._manifest_filename).is_file():
            return [load_skill_package(base, source=source.value)]
        loaded: list[LoadedSkill] = []
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / self._manifest_filename).is_file():
                loaded.append(load_skill_package(child, source=source.value))
        return loaded
