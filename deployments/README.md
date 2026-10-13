# Astra AI · 部署（Phase 0 · T0-22）

两种模式（设计 §2.13）：

| 模式 | 组成 | 命令 |
|---|---|---|
| **标准 / 开发** | `api` + `web` + `postgres` + `redis`（`ASTRA_MODE=server`） | `docker compose up --build` |
| **社区单容器** | 仅 `api`（`ASTRA_MODE=local`：SQLite + 本地文件 + 进程内任务，**零外部中间件**） | `docker compose -f deployments/compose/docker-compose.community.yml up --build` |

## 文件

| 文件 | 说明 |
|---|---|
| `../Dockerfile` | API 镜像（基于 uv，多阶段，非 root，入口先 `alembic upgrade head`） |
| `../.dockerignore` | 构建上下文排除项（保留 `apps/` `packages/` `migrations/` `pyproject.toml` `uv.lock` `alembic.ini` `deployments/docker/entrypoint.sh`） |
| `../docker-compose.yml` | 标准 / 开发模式编排 |
| `compose/docker-compose.community.yml` | 社区单容器编排 |
| `docker/entrypoint.sh` | 启动前迁移（幂等）→ `exec "$@"`（不内联业务逻辑） |

## 社区模式（验收 §3-#4）

```bash
docker compose -f deployments/compose/docker-compose.community.yml up --build
# 健康检查
curl http://localhost:8080/health   # {"status":"ok",...}
```

- 数据持久化在命名卷 `astra-data`（`/data` 下的 `astra.db` 与本地存储）；
- **无** Postgres / Redis / 对象存储依赖；
- **端口绑定默认仅本机**（`127.0.0.1:8080`，最小暴露面，拍 (b)）——同机 `http://localhost:8080` 访问；
  需**内网**访问时 `export ASTRA_BIND_ADDR=<内网IP>` 再启动（如 `export ASTRA_BIND_ADDR=192.168.1.3`）；
  **不建议**直接绑 `0.0.0.0`（暴露全部网卡）；
- `ASTRA_SECRET_KEY` 生产环境务必覆盖（示例默认值仅供本地）。

## 标准模式

```bash
export ASTRA_SECRET_KEY="$(openssl rand -hex 32)"   # 生产请使用强随机值
docker compose up --build
```

- `api` 启动前会等待 `postgres` healthy（`depends_on: condition: service_healthy`）；
- `web`（Phase 0）以 **node 镜像跑 `pnpm dev`**（开发态），Vite proxy 指向 `http://api:8080`；
- 前端 http://localhost:5173 ／ 后端 http://localhost:8080/docs。

> ⚠️ Phase 0 **不**提供前端生产镜像 / Nginx 静态托管，**不**包含 Kubernetes manifest（`deployments/kubernetes/` 留空）。
