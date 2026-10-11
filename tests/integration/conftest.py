"""``tests/integration`` 专用配置：按环境门控 PostgreSQL 冒烟测试的**收集**。

对齐 §2U.1（``test_postgres_smoke.py`` 受 ``ASTRA_TEST_PG_URL`` 门控）与 §2U.3
（``postgres-smoke`` job 防假绿），同时**不污染**默认的单元/集成测试计数：

- 设了 ``ASTRA_TEST_PG_URL``（CI ``postgres-smoke`` 或本地显式）→ **正常收集并运行**；
- 未设且 ``ASTRA_TEST_REQUIRE_PG=1`` → **仍收集**，使测试 **fail-fast**（防假绿）；
- 未设且未要求 → **不收集**，避免在默认测试 run 中产生无意义的 skip
  （默认 run 保持 ``175 passed / 1 skipped`` 的既有基线，零回归）。
"""

from __future__ import annotations

import os

collect_ignore: list[str] = []

if not os.environ.get("ASTRA_TEST_PG_URL") and os.environ.get("ASTRA_TEST_REQUIRE_PG") != "1":
    collect_ignore.append("test_postgres_smoke.py")
