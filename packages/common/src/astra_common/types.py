"""通用类型别名与类型约束。

本模块只声明类型，不含运行期逻辑，供跨包复用与静态检查。
"""

from __future__ import annotations

from typing import Any, TypeVar

# ---------------------------------------------------------------------------
# 基础别名
# ---------------------------------------------------------------------------

#: 平台内所有实体主键/外键的统一类型（UUIDv7 的字符串形式）。
ID = str

#: 泛型变量，供其他包复用。
T = TypeVar("T")

# ---------------------------------------------------------------------------
# JSON 值类型（递归）
# ---------------------------------------------------------------------------

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

#: JSON 对象别名（宽松键值）。
JSONDict = dict[str, Any]

#: JSON 数组别名。
JSONList = list[Any]

__all__ = ["ID", "T", "JSONScalar", "JSONValue", "JSONDict", "JSONList"]
