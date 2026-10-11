#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Astra AI · 社区模式本地冒烟（Phase 0 T0-22 · Phase 1 W8 / T1-37 扩展）
#
# 流程：`astra init` → 后台 `astra run` → 轮询 `/health`（+ `/openapi.json`）→ 清理退出。
#
# 社区单容器约束（设计 A-5 / I-P1-18）：**无 Docker / 无 Redis** 仍可运行——
#   - 模式 = `local`（SQLite）；
#   - 沙箱 = `local_process`（LocalProcess，不探测 Docker）；
#   - 事件总线 / 任务队列 = 进程内（InProcess，无 Redis）。
# 本脚本仅用 `curl` + `uv`（无 docker / redis 依赖）；CI `community-smoke` job 复用。
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# 社区降级：local 模式 + SQLite + LocalProcess 沙箱（无 Docker / 无 Redis）。
export ASTRA_MODE="${ASTRA_MODE:-local}"
export ASTRA_DATABASE_URL="${ASTRA_DATABASE_URL:-sqlite:///./astra_local.db}"
export ASTRA_SECRET_KEY="${ASTRA_SECRET_KEY:-smoke-secret-key-0123456789abcdef0}"
export ASTRA_SANDBOX_PROVIDER="${ASTRA_SANDBOX_PROVIDER:-local_process}"
export ASTRA_HOST="${ASTRA_HOST:-127.0.0.1}"
export ASTRA_PORT="${ASTRA_PORT:-8080}"
# 显式剔除中间件依赖（若有）：社区冒烟不依赖 Redis。
unset ASTRA_REDIS_URL 2>/dev/null || true

echo "[smoke] 社区单容器冒烟：mode=${ASTRA_MODE} sandbox=${ASTRA_SANDBOX_PROVIDER}（无 Docker / 无 Redis）"

echo "[smoke] astra init"
uv run astra init

echo "[smoke] astra run (background on ${ASTRA_HOST}:${ASTRA_PORT})"
uv run astra run --host "${ASTRA_HOST}" --port "${ASTRA_PORT}" &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

echo "[smoke] probing /health ..."
for attempt in $(seq 1 30); do
  if curl -fsS "http://${ASTRA_HOST}:${ASTRA_PORT}/health" >/dev/null 2>&1; then
    echo "[smoke] /health OK"
    health_ok=1
    break
  fi
  sleep 1
done

if [ "${health_ok:-0}" != "1" ]; then
  echo "[smoke] /health 未就绪，失败" >&2
  exit 1
fi

echo "[smoke] probing /openapi.json（确认应用完整装配）..."
if curl -fsS "http://${ASTRA_HOST}:${ASTRA_PORT}/openapi.json" >/dev/null 2>&1; then
  echo "[smoke] /openapi.json OK"
else
  echo "[smoke] /openapi.json 未就绪，失败" >&2
  exit 1
fi

echo "[smoke] 社区冒烟通过（无 Docker / 无 Redis 仍可运行）"
exit 0
