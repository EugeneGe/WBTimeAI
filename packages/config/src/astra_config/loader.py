"""配置加载器。

实现三级加载：**ENV → config.yaml → 默认值**，并提供进程级缓存的
:func:`get_settings`。

- ENV 优先于 config.yaml：由 :class:`~astra_config.settings.Settings` 的来源优先级保证；
- config.yaml 中的敏感键（见 :data:`astra_config.defaults.SENSITIVE_KEYS`）会被过滤，
  确保敏感值不从 yaml 明文读取。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_CONFIG_FILE_NAME, SENSITIVE_KEYS
from .settings import Settings

__all__ = [
    "resolve_config_file",
    "load_yaml_config",
    "yaml_settings_source",
    "get_settings",
    "reset_settings_cache",
]


def resolve_config_file() -> Path:
    """解析 config.yaml 路径。

    优先取环境变量 ``ASTRA_CONFIG_FILE``，否则取当前工作目录下的默认文件名。

    Returns:
        配置文件 :class:`~pathlib.Path`（可能不存在）。
    """
    env_path = os.environ.get("ASTRA_CONFIG_FILE")
    if env_path:
        return Path(env_path)
    return Path(DEFAULT_CONFIG_FILE_NAME)


def load_yaml_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """读取并净化 config.yaml。

    Args:
        path: 显式文件路径；为 ``None`` 时使用 :func:`resolve_config_file`。

    Returns:
        配置字典（已过滤敏感键）；文件不存在时返回空字典。

    Raises:
        ValueError: 当 YAML 内容非法或顶层不是映射时。
    """
    config_path = Path(path) if path is not None else resolve_config_file()
    if not config_path.is_file():
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 异常路径
        raise ValueError(f"Invalid YAML in config file: {config_path}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"config.yaml must contain a mapping at the top level: {config_path}")

    # 过滤敏感键：敏感值禁止从 yaml 明文读取。
    return {key: value for key, value in raw.items() if str(key).lower() not in SENSITIVE_KEYS}


def yaml_settings_source(settings_cls: type[Settings]) -> Any:  # noqa: ARG001 - 契约要求签名
    """构造 pydantic-settings 的 config.yaml 来源（返回可调用对象）。

    Args:
        settings_cls: pydantic-settings 传入的 Settings 类（未直接使用）。

    Returns:
        无参可调用对象，返回 config.yaml 净化后的字典。
    """

    def source() -> dict[str, Any]:
        return load_yaml_config()

    return source


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级缓存的 :class:`Settings` 单例。

    使用前若修改了环境变量，请调用 :func:`reset_settings_cache` 清除缓存。
    """
    return Settings()


def reset_settings_cache() -> None:
    """清除 :func:`get_settings` 的缓存（测试与热重载使用）。"""
    get_settings.cache_clear()
