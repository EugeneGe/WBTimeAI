# V0.3.1 · 可分发包

> **版本**：`0.3.1`（产品版，按 `docs/README.md` N-3 与 `施工纪律.md` §4.2-2 必出包）
> **出包时间**：2026-10-23 12:48 GMT+8（首发）
> **形态裁定**：**方案 A — 基座包**（`pnpm pack` 库包 tarball + 前端构建归档），承 V0.1.0 / V0.3.0
> **裁定理由**：V0.3.1 与 V0.3.0 同为 **L1**（不升不降），仍**无 Electron 壳**（归 V0.9.0）、**无 CLI**（归 V0.8.0）；服务入口 `apps/api` 属**仓库运行形态**（`pnpm --filter @wbtime/api start`），本版不产出安装器。
> **本版主题**：**子 Agent 委派（M1）** —— 第 6 个内置工具 `spawn_agent` 派生子 `agent_run`；父子关系**零 DDL 双源还原**；**父流只含父 run 帧**。
> **台账（DoD / 风险 / 发布登记）**：`docs/V1.0/V0.3.1-子Agent委派M1/03-台账/`。

---

## 1. 产物清单（10 件 + 校验清单 + 本文件）

| # | 文件 | 大小 | 内含文件数 | 内容 |
|---|---|---|---|---|
| 1 | `wbtime-config-0.3.1.tgz` | 37.5 K | 18 | env 解析 + `WBTIME_AI_MODE=local\|server` |
| 2 | `wbtime-contracts-0.3.1.tgz` | 28.4 K | 51 | 9 个扩展点 interface + 冻结件派生类型 + 签名快照 |
| 3 | `wbtime-core-0.3.1.tgz` | 40.0 K | 26 | 30 错误码 / 响应壳 TypeBox / HTTP 状态映射 |
| 4 | `wbtime-db-0.3.1.tgz` | 296.0 K | 254 | 61 表双档 drizzle schema（v0019 = 630 列）+ `ScopedRepo<T>` 九仓储 |
| 5 | `wbtime-domain-0.3.1.tgz` | 54.7 K | 62 | `Task` + 运行时领域纯函数（7 值状态机 / 11 值 `stop_reason` 矩阵 / 预算账本 / tool-call 状态 / 5 端口 / `subagent` 常量与深度守卫） |
| 6 | `wbtime-event-0.3.1.tgz` | 43.3 K | 22 | **19 基线通道 + delta 2 通道**（`subagent.started` / `subagent.finished`）合并后的 21 项生成面 + 数值格式归一化 + golden 帧编码器 |
| 7 | `wbtime-logging-0.3.1.tgz` | 29.0 K | 14 | pino + AsyncLocalStorage `request_id` 贯通 |
| 8 | `wbtime-ports-0.3.1.tgz` | 19.8 K | 31 | 队列 / 调度端口空实现（登记「未启用」，归 V0.5.0） |
| 9 | `wbtime-security-0.3.1.tgz` | 48.4 K | 22 | 规则注册表（凭据 5 + PII 3 + 注入 2 + `baseline` 底线）+ `detectSensitive` / `redactSensitive` 同源 + `scanSensitive` |
| 10 | `web-dist-0.3.1.tar.gz` | 415.3 K | **44** | 前端构建产物（**已排除 35 个 sourcemap**；文件数与 V0.3.0 的 44 一致） |
| — | `SHA256SUMS` | 0.9 K | — | 上述 10 个文件的 sha256 |

**合计**：约 **1.0 M**（**1 036 746 B**）。

> **与 V0.3.0 的差异面（必须写明，防止「整包重打了」的误读）**：本版所有 9 个库包**都重新产出**（版本串 0.3.0 → 0.3.1 进了每个 `package.json`），因此 **10 件 sha256 与 V0.3.0 全部不同**。这与 V0.3.0「重出 #2」的性质不同（那次是同版本、只重打有变化的包）；**本次是升版出包，全量重打是预期**。

## 2. 如何验证

```bash
cd release/v0.3.1
sha256sum -c SHA256SUMS          # 10 个文件全部 OK

# 包内版本自证（防止"版本只改了仓内、没进包"）
for f in *.tgz; do tar xzOf "$f" package/package.json | python -c 'import json,sys;d=json.load(sys.stdin);print(d["name"], d["version"])'; done

# 抽查某个包的完整性
tar tzf wbtime-db-0.3.1.tgz | head -5
tar tzf wbtime-db-0.3.1.tgz | grep -c '^package/dist/'
```

本轮实测：`sha256sum -c SHA256SUMS` ⇒ **10/10 OK，exit 0**；9 个库包内 `version` 全部 `0.3.1`；`web-dist` 归档内**非目录条目 44 个**（与 V0.3.0 一致）。

### 2.1 安装：**必须 9 个 tgz 一起装，不要单装**

`pnpm pack` 把内部的 `workspace:*` 重写成了**精确版本**（如 `wbtime-db` 依赖 `@wbtime/domain: "0.3.1"`，无 `^`）。因此：

```bash
# ✅ 正确：一次装整组，npm 会在同一次解析里满足内部依赖
npm install ./release/v0.3.1/*.tgz

# ❌ 错误：单装一个包
npm install ./release/v0.3.1/wbtime-db-0.3.1.tgz
#   → 404 Not Found - GET https://registry.npmjs.org/@wbtime%2fdomain
#   因为 @wbtime/* 未发布到 registry，只有本目录的 tarball 里才有
```

> **另**：9 个包均 `private: true` ⇒ 本分发集是**整组 tarball 分发**形态（方案 A），**不能 `npm publish`**。

## 3. 与 V0.3.1 DoD 的对应

| DoD | 在本包中的体现 |
|---|---|
| **D1** 深度必拒 | `wbtime-domain`（`MAX_SUBAGENT_DEPTH` + 深度守卫纯判定）· `wbtime-db`（`agent_run` / `tool_call` 行） |
| **D2-a / D2-b** 归属不串流 | `wbtime-event`（通道面）+ `wbtime-db`（`agent_event.run_id` 列）—— **过滤逻辑在 `apps/api`（见 §4）** |
| **D3-2a / D3-2b** 取消向下传播 | `wbtime-domain`（状态机）+ `wbtime-db`（终态 CAS）；**HTTP 面在 `apps/api`** |
| **D4** 预算超限必中断 | `wbtime-domain`（预算账本 / `stop_reason` 词表）+ `wbtime-db`（`runtime_config.limits`） |
| **D5** 权限不越父 | `wbtime-domain`（交集 + 判权纯函数）；**应用面在 `apps/api`** |
| **D6** 19 帧字节不变 + 新增 2 帧 | **`wbtime-event`**（19 基线 + delta 2 = 21 项生成面；`golden/` 全在包内） |
| **D7** 委派可回放（双源） | `wbtime-db`（`tool_call.output.child_run_id` + `agent_event(subagent.started).payload.parent_run_id`）；**写入点在 `apps/api`** |
| **D8** 并发口径不顺手放宽 | `wbtime-db`（`guard_run_creation` + `agent_run.trigger`）；**单入口在 `apps/api`** |
| **D9** 前端不被误终止 | **`web-dist`**（既有 hook 零改动）+ `wbtime-event`（通道面）；**D9②③ 本版只有静态契约守卫，见 §5** |
| **D10** 豁免不可被客户端注入 | `wbtime-core`（`RunRequest` 契约面 4 键）；**判闸在 `apps/api`** |
| **S3** 安全派发挂点 | `wbtime-security`（规则注册表）+ `wbtime-db`（`policy_version` 快照） |

> 测试证据不在包内，在台账 `03-台账/DoD-V0.3.1.md`（逐条命令 + exit code + 红证编号）。

## 4. 本包**不**包含什么（刻意）

| 项 | 原因 |
|---|---|
| `apps/api/**`（服务宿主、5+1 内置工具实现、SSRF/路径守卫、安全六挂点、**`delegation.ts` / `subagent-spawner.ts` / `sse-stream.ts`**） | 属可运行的**仓库形态**，不是 npm 库；V0.8.0 才有 CLI 形态 |
| 测试与门禁脚本（`scripts/`、`*/tests/**`） | 仓库资产，随仓库分发，不进 npm 包 |
| `apps/web/src` | 源码随仓库；包内只有构建产物 |
| sourcemap（35 个） | 体积占 dist 的大头，属调试辅助；需要时 `pnpm --filter @wbtime/web build` 重建 |
| `@wbtime/e2e` | 测试包（零依赖是 S-1 判据前提），无运行时价值 |
| `output/` 自省产物 | gitignore 的可复现产物，由 `pnpm --filter @wbtime/db introspect` 重建 |
| Electron 安装器 / CLI 二进制 | 形态未到（V0.9.0 / V0.8.0） |
| `contracts/**` 原始冻结件 | 消费方经 `wbtime-contracts` 的派生类型 + `contracts/frontend-baseline/**` 投影使用 |

> **⚠️ 形态结论（必须读）**：本版的核心行为（委派执行链、流隔离、取消传播、并发单入口、S3 挂点）**实现都在 `apps/api`** —— 按方案 A，`apps/api` **不进这 10 件产物**。所以**只装这 9 个 tgz 的消费方拿到的是「库层 + 前端」，拿不到委派运行时**；要分发运行时，须等 V0.9.0 的壳 / V0.8.0 的 CLI。

## 5. 交付边界（**别读成「子 Agent 过程在 UI 上可见」**）

**本版新增的 2 帧 `subagent.started` / `subagent.finished`，前端一个都不认识。**

- 事实：`apps/web/src/types/phase1.ts` 的 `SSE_CHANNELS` 共 **12 条**（9 主链 + AUD-06 补 3），**不含** `subagent.*`；`apps/web/src/lib/chat.ts` 的 `if (channel === null || !isSseChannel(channel)) return null;` ⇒ 两帧在解析层**结构性静默丢弃**。
- 后果：**V0.3.1 的可观测面只到 SSE / API 层**；用户能看到的仍只是既有 `spawn_agent` **工具卡片**（`tool.started` / `tool.completed` 属 9 条主链，零改动可见）。**UI 上展示子 Agent 派生过程 = 归 `1.1+`**（与「客户端 SSE 背压 / 超时」同批）。
- 这是 **Q-5 前端零改动的必然结果，不是缺陷**；已登记于 `03-台账/DoD-V0.3.1.md` §5.11 与台账 `R-前端新帧不可见`。

## 6. 复现本包

```bash
pnpm install --frozen-lockfile
pnpm -r --filter '!@wbtime/e2e' build
DEST="$(pwd)/release/v0.3.1"
pnpm --filter './packages/*' --filter '!@wbtime/e2e' exec pnpm pack --pack-destination "$DEST"
tar czf "$DEST/web-dist-0.3.1.tar.gz" -C apps/web/dist --exclude='*.map' .
cd "$DEST" && sha256sum -b *.tgz *.tar.gz > SHA256SUMS   # `-b` ⇒ `*` 前缀，与随包发布的 SHA256SUMS 同格式
```

> `SHA256SUMS` 记录**产物哈希** ⇒ 重跑 pack 必然得到不同 sha256（tarball 含时间戳等元数据）。**可复现的是构建内容与版本串，不是 tarball 字节。**

### 6.1 ⚠️ 本版复现的一处前置：`apps/web` 需要 `tsconfig.app.json` 的 zod paths 修正

`apps/web/tsconfig.app.json` 的 `compilerOptions.paths` 在本版**新增一行**：

```json
"zod": ["./node_modules/zod"]
```

**为什么需要它（实测，不是猜测）**

`@hookform/resolvers@3.10.0` 的 `zod` 子路径在 `tsc` 里解析 `import "zod"` 时，pnpm 的 `.pnpm/@hookform+resolvers@3.10.0_.../node_modules/` 下**没有** `zod` 链接（该包**未把 `zod` 声明为 peer dependency**，lockfile 的对应条目里也没有 zod）。于是 TS 一路向上，找到 `.pnpm` 里的 **`zod@4.6.7`**（由 `@modelcontextprotocol/sdk@1.32.1` 带来），把 `zodResolver` 的形参解释成 **zod v4 的 `Schema`**；而我们冻结的表单 schema 是 **zod 3.23.8**（`apps/web` 的直接依赖）⇒ `LoginDialog.tsx:58` / `Login.tsx:48` / `Register.tsx:47` 三处 `TS2345`：

```
Argument of type 'ZodObject<{username; password}, "strip", …>' is not assignable to
parameter of type 'Schema<any, any, $ZodTypeInternals<any, any>>'
```

加这一行把 zod 的类型解析**钉回 v3.23.8**（即 resolvers 3.x 设计时的版本），`npx tsc -p apps/web/tsconfig.app.json --noEmit` ⇒ **exit 0**。

**性质与边界**

- 这是**构建配置修正，不是业务代码改动**：`apps/web/src/**` **零改动**，红线判据 `git diff --exit-code ts/v0.3.0...HEAD -- apps/web/src` **仍 exit 0**。
- **未动依赖图、未动 `pnpm-lock.yaml`**。
- **关于"V0.3.0 是否也会失败"——本包不作断言**。可确证的只有：`node_modules/.modules.yaml` 与 `apps/web/node_modules/zod` 的 mtime 均为 **2026-10-23 12:40**（本次收口期间 `pnpm install` 重写），而 V0.3.0 的 `web-dist` 构建于 **2026-10-22 23:12**；**V0.3.0 出包时的链接布局已不可回放，故无法确定当时是否同样失败**。本版按上述方式修复并如实登记，**不把本机状态推广成普遍事实**。

## 7. 校验前置（出包前已确认）

- **版本串全栈一致**：**13 个 `package.json`（根 + 2 apps + 10 packages）全为 `0.3.1`**（`grep -rn '"version"' --include=package.json` 实测 13/13）。
- **全包构建退出 0**：11 个单元 `Done`（含 `apps/web`；见 §6.1 的前置）。
- **门禁全绿**：`pnpm gate:all` **exit 0**（12 步；`[inject]` 12/12 真红、`[meta]` 4/4、`[selfproof]` PASS、`[manifest-semantics]` PASS）。
- **测试**：api **696/696**（带 `WBTIME_PY_ORACLE_PYTHON`，见下）· workspace `pnpm -r test` exit 0（web **505** / db **186** / event **43** / domain **35** / config **18** / contracts **14** / security **13** / core **10** / logging **7** / ports **5** / e2e **4**）· `test:e2e:runtime` **13/13** · `test:e2e:all` **21 pass / 4 组**。
- **冻结面零变化**：DDL `61/630/176`（v0019）+ `61/629/176`（v0018）· OpenAPI `100/134/116` · SSE **19 基线 sha 全等 + delta 2** · 前端 `apps/web/src` 零改动（G031-7 exit 0）。
- **版本基线自证**：`python scripts/check_baseline.py` ⇒ **PASS (14/14)**。
- **未验证（如实登记）**：真实厂商连通性烟测（凭据不可得）· PG 运行时 e2e（依赖不可得）· **`J-2②` 的等价性证据只在本机 venv（`D:/WBT/WBTimeAI_old/.venv`，`argon2-cffi 25.1.0`）上成立，换机须重跑**。

### 7.1 `J-2②` 的成立条件（不要把「绿」当成无条件绿）

```bash
WBTIME_PY_ORACLE_PYTHON="D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe" pnpm --filter @wbtime/api test
# ⇒ # tests 696 / # pass 696 / # fail 0
```

**不设该变量时 `J-2②` 按设计红并点名变量（fail loud，不静默跳过）—— CI 上出现这条红不是回归。** 详见 `03-台账/DoD-V0.3.1.md` §4.5 / §5.12。
