# Astra AI 桌面壳（`apps/desktop`）

> **波次**：M2 · **工作流**：WS3（发行形态 B：桌面壳 + 安装包）
> **设计**：`docs/施工方案/发行形态/M2-WS3-桌面壳-增量设计.md`
> **选型**：Electron（`electron ^43` + `electron-builder ^26`）
> **冻结边界**：本目录**完全隔离**；**不改**任何核心包 / `apps/web` / `apps/api` / `apps/cli` / 根配置。

## 说明

桌面壳是一个 Electron 应用，加载 Astra 的 Web UI，并按优先级链解析后端：

```
1) 设置中的远端 URL                → kind=remote
2) spawn 本地 `astra run`（PATH 有）→ kind=spawned（探测 /health 就绪）
3) 探测 127.0.0.1:8080/health 通    → kind=existing
4) 均不可用                        → kind=none（显示"连接后端"引导页）
```

渲染层默认 **`bundled`**：壳内自带 HTTP 服务（`RendererServer`）托管构建期拷贝的
`renderer/`（= `apps/web/dist`），并把 `/api`、`/health`、`/docs`、`/openapi.json`、
`/metrics` **同源反代**到后端（**SSE 逐块 flush、不缓冲**）。

> ⚠️ 本包**不纳入** pnpm workspace（独立 `package.json` + 独立安装），避免把
> Electron（~200MB 二进制）拉进 web CI，也避免抖动根 `pnpm-workspace.yaml` / lock。

## 目录

```
apps/desktop/
├─ electron-builder.yml   # 打包配置（nsis / AppImage / deb）
├─ tsconfig.json          # src/ → out/（CommonJS）
├─ scripts/
│  ├─ sync-renderer.mjs   # apps/web/dist → renderer/
│  ├─ generate-icons.mjs  # 生成占位图标 build/icon.png|ico
│  └─ build-linux-docker.sh   # 服务器出 Linux 包（T-05）
├─ build/                 # 图标资源（icon.ico / icon.png）
├─ src/                   # 主进程 / 预加载 TS 源码（out/ 为编译产物，不入库）
└─ renderer/              # 构建期同步的前端产物（不入库）
```

## 快速开始（Windows 本机）

```bash
# 0) 前置：构建前端（产出 apps/web/dist）
pnpm --filter @astra/web build

# 1) 安装桌面壳依赖（独立于根 workspace）
cd apps/desktop
npm install          # 或 pnpm install

# 2) 生成占位图标（首次；或将正式图标放入 build/）
npm run icons

# 3) 同步前端产物 → renderer/
npm run sync:renderer

# 4) 开发运行 / 打包 / 冒烟
npm run dev          # 编译 + 同步 + electron .
npm run dist:dir     # 免安装目录包（便于冒烟）→ release/win-unpacked/
npm run dist:win     # Windows 安装包 → release/Astra-AI-Setup-<v>.exe
npm run smoke        # 以 --dir 产物做无交互启动冒烟（断言启动 + 退出码 0）
```

## 打包与冒烟（T-04 / T-05）

### Windows（本机可出）

```bash
cd apps/desktop
npm run dist:dir     # 免安装目录包：release/win-unpacked/Astra AI.exe
npm run smoke        # 冒烟：以 ASTRA_DESKTOP_SMOKE=1 启动产物，置窗口就绪标记后自动退出
npm run dist:win     # nsis 安装包：release/Astra-AI-Setup-<version>.exe
```

> 冒烟脚本（`scripts/smoke-packaged.mjs`）**不伪造成功**：超时 / 非零退出 / 缺标记
> 均判失败。主进程在 `ASTRA_DESKTOP_SMOKE=1` 时于窗口就绪后写标记并 `app.quit()`。
> 首发出包需外网下载 electron 二进制与 electron-builder 资源（nsis / winCodeSign）；
> 内网受限可设 `ELECTRON_MIRROR` / `ELECTRON_BUILDER_BINARIES_MIRROR`（见设计 §11 D-7）。

### Linux（须在 Linux + Docker 宿主）

```bash
# 在 Linux 服务器（如内网 192.168.1.3）上，于仓库根执行：
bash apps/desktop/scripts/build-linux-docker.sh
# 产物：apps/desktop/release/Astra-AI-<v>.AppImage  +  astra-ai_<v>_amd64.deb
```

> 本机（Windows）**不能**交叉出 Linux 包（无 Docker/WSL；`service.electron.build` 已停）。
> 脚本在 `electronuserland/builder` 容器内先构建前端（pnpm）再打包桌面壳（npm）。
> Linux 包**运行**前提：AppImage 需 FUSE；deb 用系统包管理器安装。

## 产物

| 产物 | 命令 | 环境 |
|---|---|---|
| Windows nsis 安装包 `Astra-AI-Setup-<v>.exe` | `npm run dist:win` | Windows 本机 |
| 免安装目录包（`release/win-unpacked/`） | `npm run dist:dir` | Windows 本机 |
| Linux AppImage / deb | `npm run dist:linux`（或 `scripts/build-linux-docker.sh`） | **须在 Linux 宿主 / Docker** |

> 内网 / 镜像受限时，electron 与 electron-builder 资源可经环境变量走镜像：
> `ELECTRON_MIRROR`、`ELECTRON_BUILDER_BINARIES_MIRROR`。

## 出 Linux 包（服务器 / Docker）

本机（Windows）**不能**出 Linux 包（无 Docker/WSL；`service.electron.build` 已停）。
在 Linux + Docker 宿主（内网 `192.168.1.3`）上：

```bash
bash apps/desktop/scripts/build-linux-docker.sh
# 产物：apps/desktop/release/Astra-AI-<v>.AppImage  +  astra-ai_<v>_amd64.deb
```

## 安全基线

- `contextIsolation: true` / `nodeIntegration: false` / `sandbox: true`；
- `window.open` 一律 `shell.openExternal`（系统浏览器）；
- 桌面设置文件**只存非敏感项**（后端 URL / 渲染模式 / 端口）；
  **API Key / 凭证一律走后端既有 credential 体系**，绝不写入桌面设置或日志。

## 构建脚本速查

| 脚本 | 作用 |
|---|---|
| `build` | `tsc` 编译 `src/` → `out/` |
| `sync:renderer` | 同步 `apps/web/dist` → `renderer/` |
| `icons` | 生成占位图标 |
| `dev` / `start` | 编译（+同步）后运行 Electron |
| `dist:dir` / `dist:win` / `dist:linux` | electron-builder 打包 |
| `test` | 编译后跑 `node --test`（主进程单测） |
