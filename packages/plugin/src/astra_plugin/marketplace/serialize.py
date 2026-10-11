"""确定性序列化（Marketplace 包格式的**唯一序列化出口**；W8 裁定 R7 / §3.2）。

冻结口径（R7）：

- **键序**：字典按键名**升序**（``sort_keys=True``，显式排序，不依赖插入序）；
- **缩进**：2 空格（``indent=2``）、块风格（``default_flow_style=False``）；
- **换行**：``\\n``（LF）——读时归一，写时 ``newline="\\n"``（避免 Windows CRLF 漂移）；
- **尾换行**：文件末**恰好一个** ``\\n``；
- **Unicode**：``allow_unicode=True``（中文原样，不转义）；
- 列表不额外缩进（``indent=2`` 默认），避免 PyYAML 悬挂缩进歧义。

:func:`canonical_dump` / :func:`load` / :func:`normalize` 由 ``export.py`` / ``publish.py``
与测试**共用**，保证 ``export → import → export`` 在**规范化后** ``diff == 空``
（``I-P2-18`` / ``D13``）。

🔴 本模块**零 Web / ORM**：仅依赖标准库 + ``astra_core`` +（函数级）``pyyaml``。
``pyyaml`` 采用**函数级延迟导入**（镜像 ``astra_skill/manifest.py``），保包可导入性。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

__all__ = [
    "canonical_dump",
    "load",
    "load_file",
    "read_text",
    "normalize",
    "write_canonical",
    "atomic_write_bytes",
]

#: PyYAML 折行宽度（取足够大值以避免长标量折行，保证跨运行字节稳定）。
_DUMP_WIDTH = 4096

#: 换行符（冻结：LF）。
_NEWLINE = "\n"


def _yaml() -> Any:
    """函数级延迟导入 ``pyyaml``（缺失 → ``DEPENDENCY_MISSING``，**非静默**）。"""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 依赖缺失分支
        raise DomainError(
            "缺少依赖 pyyaml（请安装 astra-plugin 完整依赖）",
            code=ErrorCode.DEPENDENCY_MISSING,
            data={"package": "astra-plugin", "dependency": "pyyaml"},
        ) from exc
    return yaml


def _to_lf(text: str) -> str:
    """把任意换行归一为 LF（``\\r\\n`` / ``\\r`` → ``\\n``）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical_dump(obj: Any) -> str:
    """把 Python 对象序列化为**规范化 YAML 文本**（R7 冻结口径）。

    Args:
        obj: 待序列化对象（映射 / 序列 / 标量）。

    Returns:
        规范化 YAML 文本：键序升序 / 2 空格缩进 / LF / **恰好一个尾换行** /
        ``allow_unicode=True``。

    Raises:
        DomainError: ``pyyaml`` 缺失（``DEPENDENCY_MISSING``）。
    """
    yaml = _yaml()
    text = yaml.safe_dump(
        obj,
        sort_keys=True,
        indent=2,
        default_flow_style=False,
        allow_unicode=True,
        width=_DUMP_WIDTH,
    )
    text = _to_lf(text)
    # 恰好一个尾换行（去净尾部多余换行后再补一个）。
    return text.rstrip("\n") + _NEWLINE


def load(text: str) -> Any:
    """解析 YAML 文本（``safe_load``）。

    Args:
        text: YAML 文本。

    Returns:
        解析结果（空文档 → ``None``）。

    Raises:
        DomainError: YAML 非法（``VALIDATION_ERROR``）或 ``pyyaml`` 缺失
            （``DEPENDENCY_MISSING``）。
    """
    yaml = _yaml()
    try:
        return yaml.safe_load(_to_lf(text))
    except yaml.YAMLError as exc:
        raise DomainError(
            "YAML 解析失败", code=ErrorCode.VALIDATION_ERROR, data={"reason": str(exc)}
        ) from exc


def read_text(path: Path) -> str:
    """以 UTF-8 读取文本文件（**统一收敛**编码 / IO 错误）。

    Args:
        path: 文件路径。

    Returns:
        文件全文（UTF-8 解码）。

    Raises:
        DomainError: 非 UTF-8 编码或读取失败（``VALIDATION_ERROR``）——**不产生半成品**
            （不抛出裸 ``UnicodeDecodeError`` / ``OSError``）。
    """
    target = Path(path)
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DomainError(
            "文件非 UTF-8 编码",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "invalid_encoding", "path": str(target)},
        ) from exc
    except OSError as exc:
        raise DomainError(
            "文件读取失败",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "io_error", "path": str(target)},
        ) from exc


def load_file(path: Path) -> Any:
    """读取并解析 YAML 文件（UTF-8 + LF 归一）。

    Raises:
        DomainError: 文件不存在 / 非 UTF-8 / 内容非法（``VALIDATION_ERROR``）。
    """
    target = Path(path)
    if not target.is_file():
        raise DomainError(
            "YAML 文件不存在", code=ErrorCode.VALIDATION_ERROR, data={"path": str(target)}
        )
    return load(read_text(target))


def normalize(text: str) -> str:
    """把 YAML 文本**规范化**为确定性文本（去格式差异后逐行可比）。

    口径 = :func:`load` 解析 + :func:`canonical_dump` 重新序列化（键序重排 +
    LF 归一 + 恰好一个尾换行）。``normalize(export_1) == normalize(export_2)``
    即「往返规范化后 ``diff == 空``」。

    Raises:
        DomainError: YAML 非法或 ``pyyaml`` 缺失。
    """
    data = load(text)
    if data is None:
        data = {}
    return canonical_dump(data)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """把字节**原子**写入 ``path``（临时文件 + ``os.replace``）。

    Args:
        path: 目标文件路径（父目录会被创建）。
        data: 待写入字节。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def write_canonical(obj: Any, path: Path) -> str:
    """把对象**规范化**序列化并原子写入 ``path``（UTF-8 + LF）。

    Returns:
        写入的规范化文本（便于调用方复用）。
    """
    text = canonical_dump(obj)
    atomic_write_bytes(Path(path), text.encode("utf-8"))
    return text
