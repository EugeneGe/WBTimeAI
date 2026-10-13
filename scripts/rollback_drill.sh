#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Astra AI · 回滚演练（DoD-D8 / 设计 §4；W8 / T1-38）
#
# 内容：
#   0. **§4 不可逆清单前置动作**（写操作前，一次实测）：
#      ① git 基线快照存在性（干净工作区或已 stash 点）；
#      ② 危险动作默认 dry-run（rm -rf / git push --force / 越界写）——复用 I-P1-10 套件实测。
#   1. **迁移回滚（双引擎）**：
#      SQLite 实跑；PG 受 `ASTRA_TEST_PG_URL` 门控（A17：本机无 PG 运行时 → CI nightly 实跑）。
#      链路：`upgrade head →（check @head：标准档零漂移 / 降级档已知差异白名单）
#            → downgrade 0002 →（断言 15 张表消失）→ upgrade head →（check @head，往返干净）`。
#
# 说明（对齐 CI 迁移 job）：`alembic check` 在**非 head** 修订下按设计报
#   "Target database is not up to date"（非零）；故「零漂移」断言于 **head** 执行，
#   而 `downgrade 0002` 之后的 `alembic check` **如实报非 head** 亦作为回滚状态的负向佐证。
#   正断言经 `scripts/check_migration_drift.py`（**降级感知**）：标准档（带 vector）→ 零漂移；
#   plain 档（无 vector 扩展，0013/0014 **设计内降级**为 jsonb）→ 放行**恰好 2 项**已知差异
#   （embedding.vector / memory.vector），多 1 项即 fail。负向断言与其余逻辑不变。
#
# 退出码：全绿 0；任一断言失败非零（防假绿，不用 `|| true`）。
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

#: Phase 1 新增表（设计 §2.15.1 逐列清单，共 15 张）。
PHASE1_TABLES="agent agent_version agent_tool model_provider model tool tool_version tool_permission conversation message agent_run tool_call agent_event sandbox_session audit_log"

log() { printf '\n[rollback] %s\n' "$*"; }

# -- 0. §4 不可逆清单前置动作（写操作前，一次实测） -------------------------

log "§4 前置动作 ①：写操作前 git 基线快照"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[rollback] ✗ 非 git 仓库：无法提供写操作前基线快照" >&2
  exit 1
fi
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
if [ -z "${HEAD_SHA}" ]; then
  echo "[rollback] ✗ 无 HEAD 提交：不满足「写操作前存在 git 基线快照」" >&2
  exit 1
fi
DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
#: 已跟踪文件的改动数（`--untracked-files=no` 排除未跟踪 `??` 行）。
#: `git stash create` **不**包含未跟踪文件：若工作树仅含未跟踪文件，它返回空串，
#: 会使脚本误判「无基线」而 EXIT=1。故此处单独识别「仅未跟踪」脏树并回退 HEAD。
TRACKED_DIRTY="$(git status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
STASHED="$(git stash list | wc -l | tr -d ' ')"
if [ "${DIRTY}" = "0" ]; then
  BASELINE="HEAD:${HEAD_SHA}"
  log "  工作区干净 → 基线快照=${BASELINE}"
elif [ "${TRACKED_DIRTY}" = "0" ]; then
  # 仅含未跟踪文件（无已跟踪改动）：`git stash create` 会产出空 → 回退 HEAD 作基线。
  BASELINE="HEAD:${HEAD_SHA}"
  log "  工作区仅含未跟踪文件（无已跟踪改动）→ 基线快照回退 HEAD=${BASELINE}"
elif [ "${STASHED}" != "0" ]; then
  BASELINE="$(git stash list | head -1 | cut -d: -f1)"
  log "  存在 stash 点 → 基线快照=${BASELINE}"
else
  # 工作区脏且无 stash 点：**现场创建**非破坏快照（不改动工作区）作为写操作前基线。
  BASELINE="$(git stash create || true)"
  if [ -z "${BASELINE}" ]; then
    echo "[rollback] ✗ 无法创建 git 基线快照：拒绝后续写操作" >&2
    exit 1
  fi
  log "  工作区脏且无 stash 点 → 现场创建快照 git stash create=${BASELINE}（非破坏）"
fi
log "  ✓ 存在可用 git 基线快照（${BASELINE}）"

log "§4 前置动作 ②：危险动作默认 dry-run 实测（rm -rf / git push --force / 越界写）"
uv run pytest tests/integration/test_dangerous_actions.py -q

# -- 表清单断言（方言无关，经 SQLAlchemy inspect） --------------------------

check_tables() {  # $1=db_url $2=present|gone $3=label
  DB_URL="$1" EXPECT="$2" LABEL="$3" PHASE1_TABLES="${PHASE1_TABLES}" uv run python - <<'PY'
import os

import sqlalchemy as sa

tables = set(os.environ["PHASE1_TABLES"].split())
engine = sa.create_engine(os.environ["DB_URL"])
try:
    names = set(sa.inspect(engine).get_table_names())
finally:
    engine.dispose()
label = os.environ["LABEL"]
if os.environ["EXPECT"] == "present":
    missing = tables - names
    assert not missing, f"[{label}] 缺少 Phase 1 表：{sorted(missing)}"
    print(f"[rollback] ✓ [{label}] 15 张 Phase 1 表全部存在")
else:
    survivors = tables & names
    assert not survivors, f"[{label}] 回滚后仍存在 Phase 1 表：{sorted(survivors)}"
    print(f"[rollback] ✓ [{label}] 15 张 Phase 1 表已消失")
PY
}

# -- 迁移回滚演练（upgrade → check → downgrade 0002 → 断言消失 → 往返） ----

drill() {  # $1=mode $2=db_url $3=label
  local mode="$1" url="$2" label="$3"
  export ASTRA_MODE="${mode}"
  export ASTRA_DATABASE_URL="${url}"

  log "[${label}] alembic upgrade head"
  uv run alembic upgrade head
  check_tables "${url}" present "${label}@head"

  log "[${label}] alembic check @head（标准档零漂移 / 降级档已知差异白名单）"
  uv run python scripts/check_migration_drift.py

  log "[${label}] alembic downgrade 0002"
  uv run alembic downgrade 0002
  check_tables "${url}" gone "${label}@0002"

  log "[${label}] alembic check @0002（预期报非 head）"
  if uv run alembic check >/dev/null 2>&1; then
    echo "[rollback] ✗ 预期 0002 下 alembic check 报「非 head」，但通过了" >&2
    exit 1
  fi
  log "  ✓ 0002 下 alembic check 如实报非 head（符合预期）"

  log "[${label}] 复位：upgrade head → check（往返干净；标准档零漂移 / 降级档已知差异白名单）"
  uv run alembic upgrade head
  check_tables "${url}" present "${label}@head-restored"
  uv run python scripts/check_migration_drift.py
}

# 环境基线（本地/SQLite 演练）。
export ASTRA_SECRET_KEY="${ASTRA_SECRET_KEY:-rollback-drill-secret-0123456789abcdef0}"
unset ASTRA_CONFIG_FILE 2>/dev/null || true

# -- 1. SQLite 双引擎演练（实跑） ------------------------------------------
SQL_DIR="$(uv run python -c 'import tempfile,pathlib;print(pathlib.Path(tempfile.mkdtemp()).as_posix())')"
trap 'rm -rf "${SQL_DIR:-}" 2>/dev/null || true' EXIT
drill local "sqlite:///${SQL_DIR}/rollback_drill.db" "sqlite"

# -- 2. PostgreSQL 演练（门控；A17） ----------------------------------------
if [ -n "${ASTRA_TEST_PG_URL:-}" ]; then
  drill server "${ASTRA_TEST_PG_URL}" "postgres"
else
  log "未设置 ASTRA_TEST_PG_URL → 跳过 PG 演练（A17：本机无 PG 运行时；经 CI nightly 实跑）"
fi

log "回滚演练通过（15 张表可逆 + §4 前置动作实测）"
exit 0
