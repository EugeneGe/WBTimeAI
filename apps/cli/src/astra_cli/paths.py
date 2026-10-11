"""数据目录解析与 ``config.yaml`` 模板（决策 D5）。

``~/.astra-ai/{data,workspace,storage,logs,secrets}/`` 为本地模式的标准目录树；
生成的 ``config.yaml`` **仅含非敏感项**（与既有「ENV → config.yaml → 默认值」
三级加载兼容），敏感键（``secret_key`` 等）**不写入**。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "DEFAULT_SUBDIRS",
    "CONFIG_FILE_NAME",
    "CONFIG_YAML_TEMPLATE",
    "resolve_data_dir",
    "ensure_directories",
    "write_config_yaml",
    "bind_config_file",
    "locate_alembic_ini",
]

#: 标准子目录（``init`` 建立）。
DEFAULT_SUBDIRS: tuple[str, ...] = ("data", "workspace", "storage", "logs", "secrets")

#: 生成配置文件文件名。
CONFIG_FILE_NAME = "config.yaml"

#: ``config.yaml`` 模板（**无真实密钥**；敏感键一律省略）。
CONFIG_YAML_TEMPLATE = """# Astra AI config.yaml —— 由 `astra init` 生成（幂等）。
#
# 三级加载优先级：ENV(ASTRA_*) -> config.yaml -> 默认值；ENV 覆盖本文件。
# 敏感键（secret_key 等）禁止写入本文件，请通过环境变量或 secrets/ 目录提供。
mode: local
host: 127.0.0.1
port: 8080
log_level: INFO
log_format: console
data_dir: {data_dir}
# 数据库连接串：local 模式默认 SQLite；如含密码请改用 ENV（ASTRA_DATABASE_URL）。
# database_url: sqlite:///./astra_local.db
"""


def resolve_data_dir(data_dir: str | None = None) -> Path:
    """解析数据目录（``~`` 展开）。

    Args:
        data_dir: 显式数据目录；为 ``None`` 时取配置 ``ASTRA_DATA_DIR``。

    Returns:
        展开后的 :class:`~pathlib.Path`。
    """
    if data_dir:
        return Path(data_dir).expanduser()
    from astra_config import get_settings

    return Path(get_settings().data_dir).expanduser()


def ensure_directories(base: Path) -> tuple[list[Path], list[Path]]:
    """建立标准目录树（幂等）。

    Args:
        base: 数据根目录。

    Returns:
        ``(created, existing)``：本次新建 / 已存在的子目录列表。
    """
    base.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    existing: list[Path] = []
    for name in DEFAULT_SUBDIRS:
        sub = base / name
        if sub.exists():
            existing.append(sub)
        else:
            sub.mkdir(parents=True, exist_ok=True)
            created.append(sub)
    return created, existing


def write_config_yaml(base: Path, *, data_dir: str) -> tuple[Path, bool]:
    """写入 ``config.yaml``（**幂等**：已存在则不覆盖）。

    Args:
        base: 数据根目录。
        data_dir: 写入文件中的 ``data_dir`` 值。

    Returns:
        ``(配置文件路径, 是否新写入)``。
    """
    path = base / CONFIG_FILE_NAME
    if path.exists():
        return path, False
    path.write_text(CONFIG_YAML_TEMPLATE.format(data_dir=data_dir), encoding="utf-8")
    return path, True


def bind_config_file(base: Path) -> None:
    """将 ``<base>/config.yaml`` 绑定为进程配置来源并清缓存（若文件存在）。

    使后续 ``get_settings()`` 能读到生成的 ``config.yaml``（ENV 仍优先）。
    """
    config_path = base / CONFIG_FILE_NAME
    if config_path.is_file():
        os.environ["ASTRA_CONFIG_FILE"] = str(config_path)
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()


def locate_alembic_ini() -> Path | None:
    """定位 ``alembic.ini``（先搜当前工作目录祖先，再搜本包祖先）。

    Returns:
        ``alembic.ini`` 路径；未找到返回 ``None``。
    """
    searched: list[Path] = []
    cwd = Path.cwd()
    searched.extend([cwd, *cwd.parents])
    module_dir = Path(__file__).resolve()
    searched.extend(module_dir.parents)
    for parent in searched:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    return None
