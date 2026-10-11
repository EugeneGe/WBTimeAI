"""``SkillRegistry``（按名与版本注册 + **来源优先级**判定；W2 裁定 R3 §3.3）。

来源覆盖优先级 **``workspace > plugin > builtin``** 的判定**集中在本注册表**
（:meth:`SkillRegistry.resolve`），与 ``ToolRegistry`` / ``ModelRegistry`` **同构**：

1. 取所有来源中 ``name`` 匹配的候选，按 ``(source.rank, version_key, seq)`` **降序**排序；
2. ``source.rank`` 高者优先（``workspace > plugin > builtin``）；
3. **同 source 同 name**：``version``（语义化版本元组）高者优先；
4. **同 source 同 name 同 version**：**后注册覆盖**（``override=True`` 语义）；
   ``override=False`` → ``DomainError(CONFLICT)``。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core`` + 本包 ``manifest``）。
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from enum import StrEnum

from astra_core import DomainError, ErrorCode

from .manifest import LoadedSkill, version_key

__all__ = ["SkillSource", "SkillRegistry"]


class SkillSource(StrEnum):
    """Skill 来源（``rank`` 决定覆盖优先级：``builtin=0 < plugin=1 < workspace=2``）。"""

    BUILTIN = "builtin"
    PLUGIN = "plugin"
    WORKSPACE = "workspace"

    @property
    def rank(self) -> int:
        """来源优先级（数值大者优先）。"""
        return _RANK[self.value]

    @classmethod
    def ensure(cls, value: str | SkillSource) -> SkillSource:
        """校验并归一化来源（非法值 → ``VALIDATION_ERROR``）。"""
        if isinstance(value, SkillSource):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            raise DomainError(
                "Skill 来源非法",
                code=ErrorCode.VALIDATION_ERROR,
                data={"source": str(value)},
            ) from exc


#: 来源优先级映射（R3 §3.3）。
_RANK: dict[str, int] = {
    SkillSource.BUILTIN.value: 0,
    SkillSource.PLUGIN.value: 1,
    SkillSource.WORKSPACE.value: 2,
}


@dataclass(frozen=True)
class _Entry:
    """注册表内部条目（承载优先级判定所需字段）。"""

    name: str
    version: str
    source: SkillSource
    seq: int
    loaded: LoadedSkill

    @property
    def version_key(self) -> tuple[int, int, int]:
        """语义化版本元组（用于同来源同名排序）。"""
        return version_key(self.version)

    @property
    def sort_key(self) -> tuple[int, tuple[int, int, int], int]:
        """排序键：``(source.rank, version_key, seq)`` 降序取首。"""
        return (self.source.rank, self.version_key, self.seq)


class SkillRegistry:
    """Skill 注册表（按名 / 版本注册，判定来源优先级）。

    Args:
        default_source: 缺省来源（当 :meth:`register` 未显式给出 ``source`` 时使用）。
    """

    def __init__(self, *, default_source: SkillSource = SkillSource.BUILTIN) -> None:
        self._by_name: dict[str, builtins.list[_Entry]] = {}
        self._default_source = default_source
        self._seq = 0

    def register(
        self,
        name: str,
        version: str,
        loaded_skill: LoadedSkill,
        *,
        source: SkillSource | None = None,
        override: bool = True,
    ) -> None:
        """注册一个已装载的 Skill 版本。

        Args:
            name: Skill 名（唯一键之一）。
            version: 语义化版本。
            loaded_skill: 已装载的 Skill。
            source: 来源（缺省用注册表 ``default_source``）。
            override: 同 ``(source, name, version)`` 重名时是否覆盖（默认 ``True``）。

        Raises:
            DomainError: ``override=False`` 且同来源同名同版本已存在（``CONFLICT``）。
        """
        resolved_source = source or self._default_source
        entries = self._by_name.setdefault(name, [])
        if not override:
            for entry in entries:
                if entry.source == resolved_source and entry.version == version:
                    raise DomainError(
                        f"Skill 已注册：{name}@{version}（{resolved_source.value}）",
                        code=ErrorCode.CONFLICT,
                        data={"name": name, "version": version, "source": resolved_source.value},
                    )
        self._seq += 1
        entries.append(
            _Entry(
                name=name,
                version=version,
                source=resolved_source,
                seq=self._seq,
                loaded=loaded_skill,
            )
        )

    def unregister(
        self,
        name: str,
        *,
        version: str | None = None,
        source: SkillSource | None = None,
    ) -> None:
        """注销（幂等）：可限定 ``version`` / ``source``；均不匹配时静默返回。"""
        entries = self._by_name.get(name)
        if not entries:
            return
        remaining = [
            entry
            for entry in entries
            if not (
                (version is None or entry.version == version)
                and (source is None or entry.source == source)
            )
        ]
        if remaining:
            self._by_name[name] = remaining
        else:
            self._by_name.pop(name, None)

    def resolve(self, name: str) -> LoadedSkill | None:
        """按名解析**生效版本**（来源优先级 → 版本 → 后注册覆盖）。

        Returns:
            生效的 :class:`LoadedSkill`；无匹配返回 ``None``。
        """
        entry = self.resolve_entry(name)
        return entry.loaded if entry is not None else None

    def resolve_entry(self, name: str) -> _Entry | None:
        """按名解析生效条目（供测试 / 调试）。"""
        entries = self._by_name.get(name)
        if not entries:
            return None
        return max(entries, key=lambda entry: entry.sort_key)

    def get(self, name: str, version: str) -> LoadedSkill | None:
        """按 ``(name, version)`` 取**优先级最高**的已注册项，无匹配返回 ``None``。"""
        entries = [entry for entry in self._by_name.get(name, []) if entry.version == version]
        if not entries:
            return None
        return max(entries, key=lambda entry: entry.sort_key).loaded

    def names(self) -> builtins.list[str]:
        """返回已注册 Skill 名（排序）。"""
        return sorted(self._by_name)

    def versions(self, name: str) -> builtins.list[str]:
        """返回某名的全部已注册版本（去重排序）。"""
        return sorted({entry.version for entry in self._by_name.get(name, [])})

    def list(self) -> builtins.list[LoadedSkill]:
        """返回每个名的**生效版本**（按名排序）。"""
        result: builtins.list[LoadedSkill] = []
        for name in self.names():
            resolved = self.resolve(name)
            if resolved is not None:
                result.append(resolved)
        return result

    def all(self) -> builtins.list[LoadedSkill]:
        """返回全部已注册项（含被覆盖的旧版本；按 ``(name, rank, version)`` 排序）。"""
        collected: builtins.list[_Entry] = []
        for first in self.names():
            collected.extend(self._by_name.get(first, []))
        collected.sort(key=lambda entry: (entry.name, *entry.sort_key))
        return [entry.loaded for entry in collected]

    def __contains__(self, name: object) -> bool:  # noqa: D105
        return isinstance(name, str) and name in self._by_name

    def __len__(self) -> int:  # noqa: D105
        return len(self._by_name)
