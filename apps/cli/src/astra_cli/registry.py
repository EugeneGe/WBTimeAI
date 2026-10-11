"""CLI 分组命令注册表（``astra <group> <cmd>``；D5 / W1b 裁定 §4）。

- :class:`CLICommandSpec`：CLI 命令声明（frozen）；
- :class:`CLIRegistry`：``register`` / ``build_groups`` / ``get``。

🔴 **接入方式（不破坏 Phase 1）**：``main.py::register_command_group(name, group)`` 签名不变；
   :meth:`CLIRegistry.build_groups` 的产物经其挂载。``init`` / ``run`` / ``doctor``
   **一字不动**；CLI **不判断 mode**（唯一分流点在 ``astra_config.providers``）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import typer
from astra_core import DomainError, ErrorCode

__all__ = ["CLICommandSpec", "CLIRegistry"]

#: 核心命令保留键（与 ``astra_plugin.cli_extension.RESERVED_CORE_COMMANDS`` 对齐；插件不得占用）。
_RESERVED_CORE_COMMANDS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("", "init"), ("", "run"), ("", "doctor")}
)


@dataclass(frozen=True)
class CLICommandSpec:
    """CLI 扩展命令声明（插件上报；W1b 裁定 §4）。

    Attributes:
        group: 命令分组（``astra <group> <cmd>``）。
        command: 命令名。
        summary: 一行说明（写入 Typer help）。
        params_schema: 参数声明（Phase 3 参数绑定用；此处仅承载）。
        required_permissions: 所需权限（默认空）。
        min_core_version: 最低核心版本约束（可空）。
    """

    group: str
    command: str
    summary: str
    params_schema: Mapping[str, Any] = field(default_factory=dict)
    required_permissions: tuple[str, ...] = ()
    min_core_version: str | None = None


class CLIRegistry:
    """CLI 分组命令注册表（冲突检测 + 分组装配）。"""

    def __init__(self) -> None:
        self._commands: dict[tuple[str, str], tuple[CLICommandSpec, Callable[..., Any]]] = {}
        self._owners: dict[tuple[str, str], str] = {
            key: "<core>" for key in _RESERVED_CORE_COMMANDS
        }

    def register(self, spec: CLICommandSpec, handler: Callable[..., Any]) -> None:
        """注册命令；键冲突（含核心保留键）→ ``CONFLICT``（**不静默覆盖**）。

        Raises:
            DomainError: ``(group, command)`` 已被占用（``CONFLICT``）。
        """
        key = (spec.group, spec.command)
        if key in self._commands or key in self._owners:
            existing = self._owners.get(key, "<unknown>")
            raise DomainError(
                f"CLI 命令冲突：{spec.group} {spec.command}（已由 {existing} 注册）",
                code=ErrorCode.CONFLICT,
                data={"group": spec.group, "command": spec.command, "existing_plugin": existing},
            )
        self._commands[key] = (spec, handler)
        self._owners[key] = spec.group or "<plugin>"

    def build_groups(self) -> dict[str, typer.Typer]:
        """把同 ``group`` 的命令聚成一个 :class:`typer.Typer` 子应用。

        Returns:
            ``{group: Typer}``（供 ``register_command_group`` 挂载）。
        """
        groups: dict[str, typer.Typer] = {}
        for spec, handler in self._commands.values():
            group_app = groups.get(spec.group)
            if group_app is None:
                group_app = typer.Typer(
                    help=f"{spec.group} 命令组", no_args_is_help=True, add_completion=False
                )
                groups[spec.group] = group_app
            group_app.command(name=spec.command, help=spec.summary)(handler)
        return groups

    def get(self, spec: CLICommandSpec) -> Callable[..., Any]:
        """返回命令的处理函数端点。

        Raises:
            DomainError: 未注册（``NOT_FOUND``）。
        """
        key = (spec.group, spec.command)
        try:
            return self._commands[key][1]
        except KeyError as exc:
            raise DomainError(
                f"CLI 命令未注册：{spec.group} {spec.command}",
                code=ErrorCode.NOT_FOUND,
                data={"group": spec.group, "command": spec.command},
            ) from exc

    def __len__(self) -> int:  # noqa: D105
        return len(self._commands)
