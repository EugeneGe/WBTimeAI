"""``PluginLoader``：entry points + 目录扫描（设计 §2.14；W1b 裁定 §3.2）。

两个来源：

1. **Python entry points**：group 名 :data:`PluginLoader.ENTRY_POINT_GROUP` ＝ ``"astra.plugins"``；
2. **目录扫描**：``plugins/{official,community}/`` 下**每子目录一插件**（读 ``plugin.toml`` +
   注入 ``sys.path`` 后 import）。

🔴 **失败降级**：单插件**加载 / 导入 / 注册**失败 → 结构化 ``ERROR``（含插件名与异常）
   + **跳过**，**不阻断应用启动**；但 ``DomainError(CONFLICT)``（命令冲突）**除外**
   ——**冲突必须启动失败**（裁定 §3.2 / §3.4）。
🔴 **零 ORM / 零能力包**：本模块不 import 任何 ORM / Web / 能力包（W1b 裁定 R2）。
"""

from __future__ import annotations

import importlib
import logging
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Final

from astra_core import DomainError, ErrorCode

from .metadata import Plugin
from .registry import PluginRegistry

__all__ = ["PluginLoader"]

_LOGGER = logging.getLogger("astra_plugin.loader")


def _looks_like_plugin(obj: object) -> bool:
    """结构判定：对象是否具备 ``metadata`` 与 ``register``（``Plugin`` 最小面）。"""
    return hasattr(obj, "metadata") and hasattr(obj, "register")


def _coerce_plugin(obj: object) -> Plugin:
    """把 entry point / 目录产物规约为 ``Plugin`` 实例。

    支持：Plugin 实例 / Plugin 类 / 返回 Plugin 的可调用。
    """
    resolved = obj
    if isinstance(resolved, type):
        resolved = resolved()
    if not _looks_like_plugin(resolved) and callable(resolved):
        resolved = resolved()
    if not _looks_like_plugin(resolved):
        raise TypeError(f"对象不符合 Plugin 契约：{type(resolved).__name__}")
    return resolved  # type: ignore[return-value]


class PluginLoader:
    """插件装载器（entry points + 目录扫描，失败降级）。

    Args:
        plugin_dirs: 目录扫描根列表（每根下每子目录一插件）；缺省为 ``None``。
        entry_points_provider: 自定义 entry point 提供者（测试注入用）。
        logger: 日志器（缺省模块级 logger）。
    """

    #: 插件 entry point group 名（W1b 裁定冻结）。
    ENTRY_POINT_GROUP: Final[str] = "astra.plugins"

    def __init__(
        self,
        *,
        plugin_dirs: Sequence[Path] | None = None,
        entry_points_provider: Callable[[], Iterable[Any]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._plugin_dirs = [Path(path) for path in plugin_dirs] if plugin_dirs else []
        self._entry_points_provider = entry_points_provider
        self._logger = logger if logger is not None else _LOGGER

    # -- 公共 API -----------------------------------------------------------

    def load(self) -> list[Plugin]:
        """装载全部可发现插件（单插件失败 → ERROR + 跳过，**不阻断**）。"""
        plugins: list[Plugin] = []
        plugins.extend(self._load_entry_point_plugins())
        plugins.extend(self._load_directory_plugins())
        return plugins

    def install(self, registry: PluginRegistry) -> list[str]:
        """装载并注册进 ``registry``，返回成功安装的插件名列表。

        单插件注册失败 → 结构化 ``ERROR`` + 跳过；``DomainError(CONFLICT)``
        （命令冲突）**向上抛出**（启动失败，裁定 §3.4）。
        """
        installed: list[str] = []
        for plugin in self.load():
            try:
                registry.register(plugin)
            except DomainError as exc:
                if exc.code is ErrorCode.CONFLICT:
                    raise
                self._log_failure(plugin, exc, stage="register")
                continue
            except Exception as exc:  # noqa: BLE001 - 单插件失败降级
                self._log_failure(plugin, exc, stage="register")
                continue
            installed.append(plugin.metadata.name)
        return installed

    # -- entry points -------------------------------------------------------

    def _load_entry_point_plugins(self) -> list[Plugin]:
        plugins: list[Plugin] = []
        for entry_point in self._iter_entry_points():
            name = getattr(entry_point, "name", "<unknown>")
            try:
                plugins.append(_coerce_plugin(entry_point.load()))
            except Exception as exc:  # noqa: BLE001 - 单插件失败降级
                self._logger.error(
                    "插件 entry point 加载失败：%s：%s",
                    name,
                    exc,
                    extra={
                        "plugin": name,
                        "stage": "load",
                        "entry_point_group": self.ENTRY_POINT_GROUP,
                    },
                )
        return plugins

    def _iter_entry_points(self) -> list[Any]:
        if self._entry_points_provider is not None:
            return list(self._entry_points_provider())
        from importlib.metadata import entry_points

        try:
            return list(entry_points(group=self.ENTRY_POINT_GROUP))
        except TypeError:  # pragma: no cover - 旧版 importlib 兼容
            discovered = entry_points()
            return list(discovered.get(self.ENTRY_POINT_GROUP, []))  # type: ignore[attr-defined]

    # -- 目录扫描 -----------------------------------------------------------

    def _load_directory_plugins(self) -> list[Plugin]:
        plugins: list[Plugin] = []
        for base in self._plugin_dirs:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir() or not (child / "plugin.toml").is_file():
                    continue
                try:
                    plugins.append(self._load_directory_plugin(child))
                except Exception as exc:  # noqa: BLE001 - 单插件失败降级
                    self._logger.error(
                        "目录插件加载失败：%s：%s",
                        child.name,
                        exc,
                        extra={"plugin": child.name, "stage": "load", "path": str(child)},
                    )
        return plugins

    def _load_directory_plugin(self, plugin_dir: Path) -> Plugin:
        manifest = tomllib.loads((plugin_dir / "plugin.toml").read_text(encoding="utf-8"))
        module_name, attr = self._resolve_target(manifest)
        if str(plugin_dir) not in sys.path:
            sys.path.insert(0, str(plugin_dir))
        module = importlib.import_module(module_name)
        target = getattr(module, attr)
        return _coerce_plugin(target)

    @staticmethod
    def _resolve_target(manifest: dict[str, Any]) -> tuple[str, str]:
        """从 ``plugin.toml`` 解析 ``(module_name, attr)``。

        约定：优先 ``entry_point = "module:attr"``；否则 ``module`` + 可选 ``attr``
        （缺省 ``"plugin"``）。
        """
        entry_point = manifest.get("entry_point")
        if isinstance(entry_point, str) and ":" in entry_point:
            module_ref, attr_ref = entry_point.split(":", 1)
            return module_ref.strip(), attr_ref.strip()
        module = manifest.get("module")
        if not isinstance(module, str) or not module:
            raise ValueError("plugin.toml 缺少 'module' 或 'entry_point'")
        attr_value = manifest.get("attr")
        attr = attr_value.strip() if isinstance(attr_value, str) and attr_value else "plugin"
        return module.strip(), attr

    # -- 日志 ---------------------------------------------------------------

    def _log_failure(self, plugin: Plugin, exc: Exception, *, stage: str) -> None:
        name = getattr(getattr(plugin, "metadata", None), "name", "<unknown>")
        self._logger.error(
            "插件 %s 失败（%s）：%s",
            name,
            stage,
            exc,
            extra={"plugin": name, "stage": stage},
        )
