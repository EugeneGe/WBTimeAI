# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Astra AI · API 镜像（基于 uv；多阶段构建；非 root 运行）
#
# - builder：`uv sync --locked`（离线锁定解析），安装运行期依赖（**不含** dev）；
# - runtime：精简镜像 + 非 root 用户；入口先 `alembic upgrade head`（幂等）再启动。
#
# ⚠️ 根工程（`package = false`）**未定义** `postgres` extra，故以
#    `--all-packages --all-extras` 等价安装 `astra-database[postgres]`（psycopg），
#    语义与设计 §2T.3 的 `--extra postgres` 一致，且 `--locked` 保证 uv.lock 零漂移。
# ---------------------------------------------------------------------------

# uv 官方镜像（仅取二进制）。
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

# ---- builder：解析并安装依赖 -------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 复制依赖清单与工作区成员（uv workspace 成员须就位方可解析）。
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
COPY migrations ./migrations
COPY alembic.ini ./
# 容器入口脚本（runtime ENTRYPOINT=/app/deployments/docker/entrypoint.sh 依赖此目录，
# 缺失将导致 `docker run` 启动即 file-not-found；`.dockerignore` 已声明其构建必需）。
COPY deployments ./deployments

RUN uv sync --locked --no-dev --all-packages --all-extras

# ---- runtime：精简运行镜像 --------------------------------------------------
FROM python:3.12-slim AS runtime
COPY --from=uv /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_SYNC=1 \
    UV_FROZEN=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app /app

# 非 root 用户；预建 /data 供社区模式 SQLite / 本地存储挂载（命名卷继承该属主）。
RUN useradd --create-home --uid 10001 astra \
    && mkdir -p /data \
    && chown -R astra:astra /app /data

USER astra

EXPOSE 8080

# 入口：先迁移（幂等），再 exec 应用命令。
ENTRYPOINT ["sh", "/app/deployments/docker/entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "astra_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
