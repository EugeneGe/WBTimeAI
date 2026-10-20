"""外部 oracle 包（V0.0.2 · T03）。

⚠️ **独立性是硬约束**（见施工 §1.3 / §1.4）：

    oracle 的职责是「独立说出真值」。若 oracle 与被验对象共用同一个解析器，
    则该解析器的 bug 会同时污染两边 ⇒ 永远验不出来。

因此本包**不得** import：

* ``scripts/extract_from_py/**``（``export_*`` / ``ddl.exporter``）——那是产物的生成者；
* ``scripts/compare_openapi.py``——它自带一套 ast 扫路由的实现，但它属于**被验门禁**。

``scripts/oracle/legacy_scan.py --assert-independent`` 会把这条约束变成可断言事实
（静态 ast 扫 import 图 + 运行期 ``sys.modules`` 检查）。

模块清单：

* :mod:`oracle.legacy_scan` —— 只读扫描 ``_old``，产出 ``LegacyFacts``（F1–F4）；
* :mod:`oracle.snapshot` —— O-C 降级档快照读写 + ``DEGRADED`` 标记。

本文件不含判据，只做包声明与依赖自检的入口。
"""

from __future__ import annotations

__all__ = ["PACKAGE_NAME"]

#: 包名（供 ``--assert-independent`` 输出使用）。
PACKAGE_NAME: str = "oracle"
