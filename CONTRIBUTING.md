# 贡献指南（CONTRIBUTING）

感谢参与 Astra AI！本仓库处于 **开源阶段（100% 开源）**，欢迎社区贡献。

## 环境准备

1. 安装 [uv](https://docs.astral.sh/uv/)（Python 工作区/依赖工具）。
2. 确保 Python **3.12** 可用（见 `.python-version`）。
3. 安装后端依赖：`uv sync`。
4. **前端（可选，涉及 `apps/web` 时）**：安装 Node **≥20** 与 **pnpm 9**
   （见根 `package.json` 的 `packageManager`），随后 `pnpm install`。

## 分支与提交

- 主分支为 `main`，请通过特性分支 + Pull Request 提交。
- 提交信息建议遵循 [Conventional Commits](https://www.conventionalcommits.org/)：
  `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`。
- 一个 PR 聚焦一件事，保持可评审的体量。

## 代码规范

- **Python**：`ruff`（lint）+ `black`（格式，line-length 100）+ `mypy`（类型）+ `pytest`。
- **前端（`apps/web`）**：`eslint`（lint，flat config）+ `prettier`（格式）+ `tsc`（类型）。
- 提交前请本地执行（后端）：
  ```bash
  uv run ruff check .
  uv run black --check .
  uv run mypy packages apps
  uv run pytest -q
  ```
- 提交前请本地执行（前端，涉及 `apps/web` 时）：
  ```bash
  pnpm lint          # eslint . --max-warnings=0
  pnpm format:check  # prettier --check
  pnpm typecheck     # tsc -p tsconfig.app.json && tsc -p tsconfig.node.json
  ```
- **分层纪律**（务必遵守）：
  - `domain` 层**不得** import FastAPI / SQLAlchemy。
  - Router 只做「校验 → 调用 Application → 映射响应」，不得直调 ORM / 领域实体 / 外部服务。
  - 一切 ID 统一走 `astra_core.id.generate_id()`（UUIDv7），禁止 `uuid4()`。
  - `ASTRA_MODE` 的分流只允许出现在 `astra_config.providers.build_providers()`。
- **ORM 写入纪律（SQLAlchemy 2.1 起）**：本仓 ORM **无 `relationship()`**（全裸 FK），而 2.1 的
  unit-of-work **不再**对无 relationship 的跨表 FK 自动按表依赖排序 `INSERT`。故：
  - **禁止**「一个 session 里裸 `session.add(...)` 多个跨表父子对象 + 单次 `commit()`」——
    同一 flush 可能先发子表，在 **PostgreSQL**（强制 FK）上 `IntegrityError( ForeignKeyViolation )`，
    而 SQLite 不强制 FK、会掩盖问题；
  - 正确做法：**逐实体 `add` + `flush`**（本仓仓储既有口径，如 `BaseRepository.add`），
    或按 FK 拓扑**分阶段 `flush()`** 后再 `commit()`（参照 `tests/nfr/_support.seed_parent_graph`）；
  - 批量写入仅限**同表**（`add_all` + 一次 `flush`）。
  - 该行为已实测（2026-10）：产品写路径因「逐实体 flush」而免疫，但新增代码务必遵守本纪律。

## Git hooks（husky）

- 安装依赖（`pnpm install`）时由 `husky` 的 `prepare` 脚本自动装配 Git hooks。
- **`.husky/pre-commit` 仅对暂存的前端文件运行 `lint-staged`**（`eslint --fix` + `prettier --write`），
  失败即**阻断提交**；后端检查**不挂** pre-commit（husky 是 Node 工具，避免在无 Node / 无 uv 环境阻塞）。
- 跳过钩子（**仅紧急**，CI 仍会强门禁）：`HUSKY=0 git commit …` 或 `git commit --no-verify`。

## 本地门禁 ↔ CI 对齐

本地**一键命令**与 CI job 步骤**一一对应**（本地能跑绿 ⇒ CI 同 job 必绿，除 OS 差异）：

| 门禁项 | 本地命令 | CI |
|---|---|---|
| 后端 lint / 格式 / 类型 | `uv run ruff check .` / `uv run black --check .` / `uv run mypy packages apps` | `lint.yml · python-lint` |
| 前端 lint / 格式 / 类型 | `pnpm lint` / `pnpm format:check` / `pnpm typecheck` | `lint.yml · frontend-lint` |
| 测试 / 迁移往返 | `uv run pytest -q` / `uv run alembic upgrade head && uv run alembic downgrade base` | `test.yml · python-test` |
| 双引擎冒烟 / 社区冒烟 / 构建 | `uv run pytest tests/integration/test_postgres_smoke.py -q` / `bash scripts/smoke_community.sh` / `pnpm build` | `test.yml · postgres-smoke` / `community-smoke` / `frontend-build` |
| PG(pgvector) 迁移往返 / 真实语义召回 | `ASTRA_TEST_PG_URL=… ASTRA_TEST_REQUIRE_PG=1 uv run --with 'psycopg[binary]' --with pgvector pytest tests/integration/knowledge -q` | `test.yml · postgres-pgvector` |

> 本地门禁与 CI workflow 一一对应（见 `.github/workflows/`）。

## 安全

- **禁止**提交任何真实密钥 / 凭证；敏感值走环境变量（`ASTRA_*`）或 `secrets/` 目录。
- **禁止**将敏感值写入 `config.yaml` 明文、日志或数据库明文列。

## 多租户约定

- 核心表从第一天带 `tenant_id`；默认仅一个 `default` Tenant，社区体验无感。
- 演进路径：Community（1 Tenant）→ Team（多 User）→ Enterprise（多 Organization）→ SaaS。

## 提交 PR 前自检清单

- [ ] `uv sync` 通过
- [ ] `uv run pytest -q` 全绿
- [ ] `uv run mypy packages apps` **零 error**
- [ ] 迁移可 `upgrade` / `downgrade` 双向（`alembic check` 零漂移）
- [ ] `pnpm lint` 通过（涉及 `apps/web` 时）
- [ ] `pnpm build` 通过（涉及 `apps/web` 时）
- [ ] 未引入违规依赖方向或 `uuid4()`
- [ ] 未提交任何密钥 / 本地产物
