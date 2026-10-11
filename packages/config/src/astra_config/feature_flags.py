"""Feature Flag — 定义 / 读取 / 覆盖合并（决策 D7，纯逻辑）。

设计要点（Phase0 设计 §2.3.4 / D7）：

- **默认全开**：注册表内所有 flag 默认 ``True``；未知 flag 亦返回 ``True``。
- **合并优先级（高 → 低）**：**配置覆盖（ENV / ``config.yaml``）→ 数据库覆盖 → 默认(全开)**。
- **纯逻辑、零 DB、零 mode**：本模块**不**读取 ``settings.mode``、**不**做环境分流、
  **不**直接访问数据库（数据库经 :class:`FeatureFlagStore` 注入）；因此不会破坏决策
  **D4**（``ASTRA_MODE`` 唯一分流点仍为 :mod:`astra_config.providers`）。
- **永不抛异常**：读取 store 失败（如 ``feature_flag`` 表缺失）时**降级为空覆盖**，
  保证关闭任一 / 全部 flag 时应用**仍可启动**（行为降级而非模块缺失，验收 §3-#14）。
- **非阉割**：flag 仅用于「开发期开关 / 风险功能灰度 / 未完成模块隐藏」，
  **不得**用于商业版解锁，**不得**导致模块 / 路由 / Provider 缺失。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "FeatureFlagDefinition",
    "FeatureFlagStore",
    "FeatureFlagService",
    "FEATURE_FLAGS",
    "feature_flag_defaults",
    "feature_flag_names",
    "is_known_feature_flag",
]


@dataclass(frozen=True)
class FeatureFlagDefinition:
    """单个 Feature Flag 的定义。

    Attributes:
        name: flag 唯一名称（如 ``registration``）。
        default: 默认是否启用（Phase 0 一律 ``True``，即「默认全开」）。
        description: 人类可读说明（用于观测 / 文档）。
    """

    name: str
    default: bool = True
    description: str = ""


#: Feature Flag 注册表：``name`` → :class:`FeatureFlagDefinition`。
#:
#: Phase 0 仅登记**行为开关**（不涉及模块 / 路由删除）。默认全部 ``True``。
FEATURE_FLAGS: dict[str, FeatureFlagDefinition] = {
    "registration": FeatureFlagDefinition(
        name="registration",
        default=True,
        description="新用户注册入口（关闭后注册路由返回降级行为，模块仍在）",
    ),
    "workspace": FeatureFlagDefinition(
        name="workspace",
        default=True,
        description="工作区功能（创建 / 列表 / 设置）",
    ),
    "credentials": FeatureFlagDefinition(
        name="credentials",
        default=True,
        description="API Key 凭证管理（填写 / 保存 / 掩码查看）",
    ),
    "organization": FeatureFlagDefinition(
        name="organization",
        default=True,
        description="组织信息展示（Phase 0 最小实现）",
    ),
}


def feature_flag_defaults() -> dict[str, bool]:
    """返回注册表内全部 flag 的默认值（``name`` → 默认布尔）。"""
    return {name: definition.default for name, definition in FEATURE_FLAGS.items()}


def feature_flag_names() -> tuple[str, ...]:
    """返回注册表中全部 flag 名称（稳定顺序）。"""
    return tuple(FEATURE_FLAGS)


def is_known_feature_flag(name: str) -> bool:
    """判断名称是否在注册表中。"""
    return name in FEATURE_FLAGS


@runtime_checkable
class FeatureFlagStore(Protocol):
    """Feature Flag 覆盖存储（数据库）协议。

    实现方（如 :class:`astra_database.SqlFeatureFlagStore`）**只需**提供
    :meth:`load_overrides`；任何读取异常都应被上游 :class:`FeatureFlagService`
    兜底，但实现方自身也应尽量以「返回 ``{}``」的方式降级。
    """

    def load_overrides(self) -> Mapping[str, bool]:
        """加载数据库中的 flag 覆盖。

        Returns:
            ``name`` → ``enabled`` 的映射；无覆盖 / 读取失败时返回空映射。
        """
        ...  # pragma: no cover - 协议方法，无实现


class FeatureFlagService:
    """Feature Flag 读取服务（覆盖合并，纯逻辑）。

    合并优先级（高 → 低）：**配置覆盖 → 数据库覆盖 → 默认(全开)**。

    Attributes:
        store: 数据库覆盖来源（可选；``None`` 表示无 DB 覆盖）。
    """

    def __init__(
        self,
        store: FeatureFlagStore | None = None,
        overrides: Mapping[str, bool] | None = None,
    ) -> None:
        """构造服务并**一次性**载入数据库覆盖（失败即降级为空）。

        Args:
            store: 数据库覆盖来源；``None`` 时视为无 DB 覆盖。
            overrides: 配置层覆盖（ENV / ``config.yaml``），优先级最高。
        """
        self._store = store
        self._config_overrides = self._normalize(overrides)
        self._db_overrides = self._load_store_overrides()

    @staticmethod
    def _normalize(raw: Mapping[str, bool] | None) -> dict[str, bool]:
        """将任意映射规范化为 ``dict[str, bool]``（跳过不可转换项，永不抛）。"""
        result: dict[str, bool] = {}
        if not raw:
            return result
        for key, value in raw.items():
            try:
                result[str(key)] = bool(value)
            except Exception:  # noqa: BLE001 - 单条异常不阻断整体
                continue
        return result

    def _load_store_overrides(self) -> dict[str, bool]:
        """从 store 载入覆盖；任何异常均降级为 ``{}``（不抛）。"""
        if self._store is None:
            return {}
        try:
            raw = self._store.load_overrides()
        except Exception:  # noqa: BLE001 - 表缺失 / 读异常 → 降级为空覆盖
            return {}
        return self._normalize(raw)

    @staticmethod
    def _default(name: str) -> bool:
        """返回某 flag 的默认值（未知 flag → ``True``）。"""
        definition = FEATURE_FLAGS.get(name)
        if definition is None:
            return True
        return definition.default

    def is_enabled(self, name: str) -> bool:
        """判断某 flag 是否启用（未知 flag → ``True``，永不抛）。

        合并优先级：默认(全开) → 数据库覆盖 → 配置覆盖（最高）。

        Args:
            name: flag 名称。

        Returns:
            flag 是否启用。
        """
        value = self._default(name)
        if name in self._db_overrides:
            value = self._db_overrides[name]
        if name in self._config_overrides:
            value = self._config_overrides[name]
        return bool(value)

    def all(self) -> dict[str, bool]:
        """返回全部已知 flag 的当前取值（含仅在覆盖中出现的自定义 flag）。

        Returns:
            ``name`` → 当前是否启用 的映射。
        """
        names = set(FEATURE_FLAGS) | set(self._db_overrides) | set(self._config_overrides)
        return {name: self.is_enabled(name) for name in sorted(names)}
