# Astra AI

> 开源 AI Agent 平台 · **v0.4.0（社区版）**

Astra AI 是一个分层清晰、可替换、多租户就绪（Tenant-ready）的 AI Agent 平台，
覆盖 Agent 编排、Skill / Tool / MCP 能力、知识库与记忆、工作流运行时、沙箱隔离与工作区管理。

当前版本 **v0.4.0**：核心平台能力已全部落地，含完整的 API 服务、Web 前端、CLI 与 Worker 运行时。
社区形态开箱即用——单机单容器，零外部中间件（SQLite + 进程内能力）。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 运行时 | Python **3.12** |
| 工作区 / 依赖 | **uv**（Python workspace） |
| Web 框架 | FastAPI + Uvicorn |
| ORM / 迁移 | SQLAlchemy 2.x + Alembic（单链迁移） |
| 配置 | pydantic-settings（`ASTRA_*`，ENV → config.yaml → 默认） |
| 数据库 | SQLite（社区默认）/ PostgreSQL（标准），方言差异隔离于 `astra_database.types` |
| ID 方案 | **UUIDv7**（统一生成入口 `astra_core.id.generate_id()`） |
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Zustand + TanStack Query |
| 部署 | Docker（多阶段构建）+ Docker Compose（社区单容器） |
| CI/CD | GitHub Actions（`lint` / `test` / `docker` / `nfr` 四条 workflow） |
| 质量工具 | 后端 ruff + black + mypy + pytest；前端 eslint + prettier + husky + lint-staged |

## 目录结构（根目录平铺）

```text
astra-ai/
├── apps/
│   ├── api/            # FastAPI 应用入口（routers / dependencies / lifespan）
│   ├── cli/            # astra CLI（init / run / doctor / marketplace / data）
│   ├── web/            # 前端（React + TS + Vite + Tailwind + shadcn/ui + Zustand + TanStack Query）
│   └── worker/         # 任务 Worker 运行时
├── packages/           # 能力包（uv workspace，共 27 个）
│   ├── 基础层：core / common / config / logging / database
│   ├── 身份与应用层：identity / security / application / domain
│   ├── Agent 与能力层：agent / skill / tool / mcp / model
│   ├── 知识与会话层：knowledge / memory / conversation
│   ├── 运行支撑层：workflow / runtime / sandbox / workspace / task / event / storage / audit
│   └── 扩展与评测：plugin / evaluation
├── migrations/         # Alembic 迁移（单链）
├── deployments/        # docker / compose（社区单容器）/ kubernetes（预留）
├── plugins/            # official / community（扩展点）
├── scripts/            # 运维脚本（smoke_community.sh / rollback_drill.sh 等）
├── tests/              # unit / integration / e2e / nfr
├── .github/workflows/  # CI：lint / test / docker / nfr
├── pyproject.toml      # uv workspace 根配置
└── alembic.ini
```

## 快速开始

```bash
# 1. 安装依赖（uv workspace）
uv sync

# 2. 验证包可导入
uv run python -c "import astra_core, astra_api"

# 3. 初始化数据库迁移
uv run alembic upgrade head

# 4. 启动 API
uv run uvicorn astra_api.main:app --reload
# 访问 http://127.0.0.1:8080/health

# 5. 运行测试
uv run pytest -q

# 6. 前端（pnpm workspace，与 uv 工作区并存）
pnpm install && pnpm build

# 7. 社区模式一条命令启动（SQLite + 进程内能力，零外部中间件）
docker compose -f deployments/compose/docker-compose.community.yml up

# 8. 或本地不放容器：社区启动冒烟（init → run → /health）
bash scripts/smoke_community.sh
```

## 质量门禁（本地 ↔ CI 对齐）

```bash
# 后端：lint / 格式 / 类型 / 测试
uv run ruff check .
uv run black --check .
uv run mypy packages apps
uv run pytest -q -o tmp_path_retention_policy=all

# 前端：lint / 格式 / 类型 / 构建
pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
```

## CI 说明

四条 workflow（`.github/workflows/`）：

- `lint.yml` —— 后端 `ruff` + `black --check` + `mypy packages apps` 零 error；前端 `eslint --max-warnings=0` + `prettier --check` + `tsc`；
- `test.yml` —— 迁移双向（`upgrade head` ↔ `downgrade base` + `alembic check` 零漂移）+ `pytest` + PostgreSQL 双引擎冒烟 + 社区启动冒烟 + 前端构建；
- `docker.yml` —— 命中 docker 相关 `paths` 时 `docker build`（**仅构建、不推送**）；
- `nfr.yml` —— 非功能要求（NFR）门禁。

## 关键设计约束

- **唯一 ID 入口**：一切 ID 均来自 `astra_core.id.generate_id()`（UUIDv7），不得在别处调用 `uuid4()`。
- **不判断环境**：`ASTRA_MODE=local|server` 的分流**只**存在于 `astra_config.providers.build_providers(settings)`；
  API 业务代码仅通过 `dependencies/container.py` 取用 Providers，不出现 `if mode == ...`。
- **分层纪律**：`domain` 层不依赖 FastAPI / SQLAlchemy；能力包边界由测试断言持续守护。
- **敏感值**：不落库、不落日志；`.env` 只放占位，无真实密钥。

## 许可证

[MIT](./LICENSE)
