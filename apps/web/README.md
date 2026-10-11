# @astra/web · Astra AI 基础 Web（Phase 0 · T0-20）

React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui + **Zustand（客户端状态）** +
**TanStack Query（服务状态）**。**仅经 `/api/v1`** 与后端交互。

## 启动

```bash
# 1) 后端（仓库根，另一个终端）：默认 127.0.0.1:8080
uv run astra init      # 首次：初始化本地数据目录
uv run astra run       # 启动 API

# 2) 前端（仓库根）
pnpm install
pnpm --filter @astra/web dev     # http://localhost:5173
```

- **开发期跨域**：`vite.config.ts` 已把 `/api` **代理**到 `http://127.0.0.1:8080`，
  故前端请求同源、无需后端 CORS（后端 `ASTRA_CORS_ORIGINS` 默认含 `:5173` 作为直连兜底）。
- 环境变量：复制 `.env.example` 为 `.env`（`VITE_API_BASE=/api/v1`）。

## 脚本

| 命令                                 | 说明                                          |
| ------------------------------------ | --------------------------------------------- |
| `pnpm --filter @astra/web dev`       | 开发服务器（5173，`/api` 代理到后端）         |
| `pnpm --filter @astra/web build`     | `tsc` 类型检查 + `vite build`（产物 `dist/`） |
| `pnpm --filter @astra/web typecheck` | 仅类型检查（app + node）                      |
| `pnpm --filter @astra/web preview`   | 预览构建产物                                  |

## 结构与约定（D6）

- `src/lib/api.ts`：axios 实例（Bearer 注入 + **401 单飞去重刷新 → 重试一次**）；
- `src/lib/token.ts`：**access 存内存**（不落 localStorage）、**refresh 存 localStorage**；
- `src/lib/permission.ts`：`usePermission()` / `can(code)`，支持 `*` 通配（对齐后端 `admin=*`）；
- `src/stores/*`：Zustand（**仅客户端状态**：access token / 用户镜像 / 主题 / 提示）；
- `src/services/*` + `src/hooks/*`：TanStack Query（**服务状态**）；
- `src/components/guards/*`：`RequireAuth`（登录态）+ `RequirePermission`（权限码）。

> 前端**不含**任何后端 `mode` 判断；`pnpm-workspace.yaml` **仅**纳入 `apps/web`，
> 与根 `pyproject.toml`（uv workspace）并存互不污染（决策 D3）。
