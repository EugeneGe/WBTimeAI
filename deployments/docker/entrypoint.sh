#!/bin/sh
# ---------------------------------------------------------------------------
# Astra AI 容器入口：启动前应用数据库迁移（幂等 + 并发安全），随后 exec 应用命令。
#
# 约定（设计 §2T.3 / 《TV1-修复范围补充裁定》§5.2）：
# - **只做**迁移 + exec，**不内联业务逻辑**；
# - 迁移编排交由 `deployments/docker/migrate.py`（**显式方言分支**）：
#     · PostgreSQL → **会话级 advisory lock 串行化**（消除 api/worker 并发
#       `alembic upgrade head` 创建 `alembic_version` 的 `UniqueViolation` 竞态）；
#     · SQLite / 其它 → **原样直连** `alembic upgrade head`（社区路径零回归）；
# - server 模式的 DB 就绪由 compose `depends_on: postgres(condition: service_healthy)` 保证。
# ---------------------------------------------------------------------------
set -eu

python /app/deployments/docker/migrate.py

echo "[astra] starting: $*"
exec "$@"
