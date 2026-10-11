"""日志获取工具。"""

from __future__ import annotations

import logging

__all__ = ["get_logger"]


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger。

    Args:
        name: logger 名称，惯例传 ``__name__``。

    Returns:
        标准库 :class:`logging.Logger` 实例。
    """
    return logging.getLogger(name)
