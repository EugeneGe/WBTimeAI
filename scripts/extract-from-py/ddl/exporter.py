"""``ddl/`` 子包的 ``run.py export`` 适配入口（C-03 提供给 C-01 的唯一挂钩）。

C-01 的 ``run.py`` 按约定发现可选子包：本目录若含 ``__init__.py``，会尝试 import
``ddl.exporter`` 并取其中的 ``EXPORTERS`` / ``exporters`` / ``EXPORTER`` / ``export``
（见 ``scripts/extract-from-py/README.md`` §5）。本文件只做**转发**，不复制任何抽取逻辑：

* DDL 四件套 → :func:`ddl.export_ddl.main`
* ``type-map.csv`` → :func:`ddl.gen_type_map.main`

两层职责保持分离：``export_ddl.py`` / ``gen_type_map.py`` 是独立 CLI（可单独跑、带 ``--check``），
本文件只是让 ``python scripts/extract-from-py/run.py export`` 一条命令覆盖 DDL。

抽取器失败时**抛异常**（而不是把退出码塞进返回值）：``run.py`` 只在抽取器抛错时才把
``export`` 判为失败，静默返回 ``{"exit": 1}`` 会让「DDL 没生成」被当成成功。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import export_ddl, gen_type_map

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查用，避免运行期依赖 _bootstrap
    from _bootstrap import ExtractContext

__all__ = ["DESCRIPTION", "NAME", "export"]

NAME = "ddl"
DESCRIPTION = "DDL freeze (three-source merge): pg/sqlite .sql + normalized.json + db/type-map.csv"


def export(ctx: ExtractContext) -> dict[str, Any]:
    """重生成 DDL 四件套与 ``type-map.csv``（供 ``run.py export`` 调用）。

    Args:
        ctx: ``_bootstrap.ExtractContext``，使用其中 ``source`` 与 ``contracts_dir``。

    Returns:
        摘要 dict（``ddl_exit`` / ``type_map_exit`` / ``out_dir``），供 ``run.py`` 打印。

    Raises:
        RuntimeError: 任一步退出码非 0（hnsw 抽取失败、未映射列、写入失败等）。
    """
    out_dir = str(ctx.contracts_dir)
    ddl_exit = export_ddl.main(["--source", ctx.source, "--out-dir", out_dir, "--quiet"])
    if ddl_exit != 0:
        raise RuntimeError(f"DDL 抽取失败：export_ddl.py 退出码 {ddl_exit}（source={ctx.source}）")

    type_map_exit = gen_type_map.main(
        ["--source", ctx.source, "--out", f"{out_dir}/db/type-map.csv"]
    )
    if type_map_exit != 0:
        raise RuntimeError(f"type-map 生成失败：gen_type_map.py 退出码 {type_map_exit}")

    return {"ddl_exit": ddl_exit, "type_map_exit": type_map_exit, "out_dir": out_dir}
