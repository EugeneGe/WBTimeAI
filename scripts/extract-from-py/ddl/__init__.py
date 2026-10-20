"""DDL 冻结面抽取子包（C-03）。

本文件存在的**唯一**目的是让 ``scripts/extract-from-py/run.py`` 按 C-01 的子包约定
（``scripts/extract-from-py/README.md`` §5：含 ``__init__.py`` 的子目录会尝试 import
``<pkg>.exporter``）发现并调用 :func:`ddl.exporter.export`。

四个脚本均**可独立运行**，不依赖本包被 import：

* ``export_ddl.py``   → 四件套（PG/SQLite 双侧 .sql + .normalized.json）
* ``gen_type_map.py`` → ``contracts/db/type-map.csv``
* ``_extract.py``     → 三源合并核心（纯函数）
* ``_env.py``         → 环境解析 + 解释器守卫（**全部委托** C-01 ``_bootstrap``，无重复实现）
"""

from __future__ import annotations

__all__ = ["__version__"]

#: 抽取器版本（与 ``schema_version = v0018`` 解耦：前者标识工具，后者标识被冻结的 schema）。
__version__ = "1.0.0"
