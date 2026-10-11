"""``astra data``——数据备份 / 恢复命令分组（W9 / T2-48；设计 §2.19 / 裁定 R10）。

经 **D5 核心分组** 注册（``main.py`` 调 ``register_command_group("data", data_app)``）：

- ``astra data backup [--out <path>]``：SQLite 经 ``VACUUM INTO`` 产出**一致性安全快照**
  （默认 ``~/.astra-ai/backups/astra-<ts>.db``）；
- ``astra data restore --from <path>``：以备份**替换当前库**（**要求先停服务**，否则可能
  覆盖到运行中连接；本命令不主动探测锁，务必停机后执行）。

🔴 **PG 显式不支持**（本机无 ``pg_dump`` / 无法安全快照）——返回**明确错误**，**不静默**。
🔴 **不改变** ``init`` / ``run`` / ``doctor`` 核心命令；**不新增顶级核心命令**。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import typer
from astra_common import utcnow
from astra_core import DomainError, ErrorCode

__all__ = [
    "DEFAULT_BACKUP_DIR",
    "BACKUP_FILE_SUFFIX",
    "DataReport",
    "data_app",
    "backup_command",
    "restore_command",
    "run_backup",
    "run_restore",
]

#: 默认备份目录（本地模式）。
DEFAULT_BACKUP_DIR = "~/.astra-ai/backups"

#: 备份文件后缀。
BACKUP_FILE_SUFFIX = ".db"

#: ``astra data`` 命令分组（D5 核心分组）。
data_app = typer.Typer(
    help="数据备份与恢复（SQLite VACUUM INTO 安全快照；PG 不支持）",
    no_args_is_help=True,
    add_completion=False,
)


@dataclass
class DataReport:
    """``astra data`` 命令结果。

    Attributes:
        action: ``backup`` / ``restore``。
        backend: 数据库后端（``sqlite``）。
        path: 本次产出的备份路径（``backup``）或目标库路径（``restore``）。
        source: 恢复来源路径（``restore``）；备份时为 ``None``。
    """

    action: str
    backend: str
    path: Path
    source: Path | None = None


def _sqlite_db_path(database_url: str) -> Path:
    """从连接串解析 SQLite 数据库文件路径（**显式报错**，不静默）。

    Raises:
        DomainError: 非 SQLite 或内存库（``CONFIGURATION_ERROR``）。
    """
    marker = ":///"
    index = database_url.find(marker)
    if not database_url.startswith("sqlite") or index < 0:
        raise DomainError(
            "仅 SQLite 支持 astra data backup/restore；PostgreSQL 请使用 pg_dump / pg_restore",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"database_url": database_url},
        )
    raw = database_url[index + len(marker) :]
    if raw in ("", ":memory:"):
        raise DomainError(
            "内存数据库不支持备份 / 恢复",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"database_url": database_url},
        )
    return Path(raw).expanduser()


def _resolve_out_path(out: str | None) -> Path:
    """解析 ``backup`` 输出路径（``--out`` 优先；否则默认目录 + 时间戳文件名）。"""
    if out:
        return Path(out).expanduser()
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    return Path(DEFAULT_BACKUP_DIR).expanduser() / f"astra-{stamp}{BACKUP_FILE_SUFFIX}"


def run_backup(out: str | None = None) -> DataReport:
    """执行 ``astra data backup``（SQLite ``VACUUM INTO`` 安全快照）。

    Args:
        out: 显式输出路径；``None`` → 默认 ``~/.astra-ai/backups/astra-<ts>.db``。

    Returns:
        :class:`DataReport`。

    Raises:
        DomainError: 非 SQLite（``CONFIGURATION_ERROR``）。
    """
    from astra_config import get_settings
    from astra_database import create_engine_from_settings
    from astra_database.maintenance.vacuum import vacuum_into

    settings = get_settings()
    # 先按连接串**显式校验**（非 SQLite → 立即报错，**不**建引擎、不触发驱动导入）。
    _sqlite_db_path(settings.database_url)
    target = _resolve_out_path(out)
    engine = create_engine_from_settings(settings)
    try:
        vacuum_into(engine, target)  # 非 SQLite 时内部亦显式报错（双保险）
    finally:
        engine.dispose()
    return DataReport(action="backup", backend="sqlite", path=target)


def run_restore(source: str, *, force: bool = False) -> DataReport:
    """执行 ``astra data restore``（以备份**替换当前库**；要求先停服务）。

    Args:
        source: 备份文件路径。
        force: 保留位；``True`` 时跳过「备份文件存在性之外的额外确认」（当前无交互确认）。

    Returns:
        :class:`DataReport`。

    Raises:
        DomainError: 非 SQLite（``CONFIGURATION_ERROR``）或备份文件不存在
            （``VALIDATION_ERROR``）。
    """
    from astra_config import get_settings

    settings = get_settings()
    _ = force  # 目前无交互确认；保留开关以便后续加严
    backup = Path(source).expanduser()
    if not backup.is_file():
        raise DomainError(
            "备份文件不存在",
            code=ErrorCode.VALIDATION_ERROR,
            data={"source": str(backup)},
        )
    db_path = _sqlite_db_path(settings.database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 原子替换：先写临时文件再 os.replace（避免半成品库）。
    tmp = db_path.with_name(f".{db_path.name}.restore.tmp")
    shutil.copy2(backup, tmp)
    os.replace(tmp, db_path)
    return DataReport(action="restore", backend="sqlite", path=db_path, source=backup)


@data_app.command("backup")
def backup_command(
    out: str | None = typer.Option(  # noqa: B008, UP007 - typer 需显式 Optional 默认值
        None,
        "--out",
        help="备份输出路径（默认 ~/.astra-ai/backups/astra-<ts>.db）",
    ),
) -> None:
    """备份当前 SQLite 库（VACUUM INTO 一致性安全快照）。"""
    report = run_backup(out)
    typer.echo(f"已备份：{report.path}")


@data_app.command("restore")
def restore_command(
    source: str = typer.Option(  # noqa: B008 - typer 需函数签名默认值
        ...,
        "--from",
        help="备份文件路径（替换当前库；请先停止服务）",
    ),
    force: bool = typer.Option(  # noqa: B008 - typer 需函数签名默认值
        False,
        "--force",
        help="跳过额外确认（当前无交互确认，保留）",
    ),
) -> None:
    """以备份替换当前库（**要求先停止服务**）。"""
    report = run_restore(source, force=force)
    typer.echo(f"已恢复：{report.path}（来源：{report.source}）")
