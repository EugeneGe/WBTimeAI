# V0.3.0 · 可分发包

> **版本**：`0.3.0`（产品版，按 `docs/README.md` N-3 与 `施工纪律.md` §4.2-2 必出包）
> **出包时间**：2026-10-22 20:04 GMT+8
> **形态裁定**：**方案 A — 基座包**（`pnpm pack` 库包 tarball + 前端构建归档）
> **裁定理由**：V0.3.0 是 **L1 首个产品可用点**（能对话 + 能看到 Agent 调工具），但仍**无 Electron 壳**（归 V0.9.0）、
> **无 CLI**（归 V0.8.0）；服务入口 `apps/api` 属仓库运行形态（`pnpm --filter @wbtime/api start`），不产出安装器。
> 其可分发形态就是 npm 生态的标准形态 —— **库包 tarball + 构建产物归档**。
> 选 A 而非"援引 `0.0.x` 豁免"（§4.2-3 明写那是**唯一**豁免档），因为产物**确实可分发**，无需放宽条款。
> **台账（DoD / 风险 / 发布登记）**：`docs/V1.0/V0.3.0-Agent运行时/03-台账/`。

---

## 1. 产物清单

| # | 文件 | 大小 | 内含文件数 | 内容 |
|---|---|---|---|---|
| 1 | `wbtime-contracts-0.3.0.tgz` | 28.4 K | 51 | 9 个扩展点 interface + 冻结件派生类型 + 签名快照 |
| 2 | `wbtime-core-0.3.0.tgz` | 40.0 K | 26 | 30 错误码 / 响应壳 TypeBox / HTTP 状态映射 |
| 3 | `wbtime-config-0.3.0.tgz` | 37.5 K | 18 | env 解析 + `WBTIME_AI_MODE=local\|server` |
| 4 | `wbtime-logging-0.3.0.tgz` | 29.0 K | 14 | pino + AsyncLocalStorage `request_id` 贯通 |
| 5 | `wbtime-event-0.3.0.tgz` | 43.0 K | 22 | 19 个 SSE 通道 + 数值格式归一化 + golden 帧编码器 |
| 6 | `wbtime-db-0.3.0.tgz` | 290.0 K | 254 | 61 表双档 drizzle schema（v0019 = 630 列）+ `ScopedRepo<T>` 九仓储 |
| 7 | `wbtime-domain-0.3.0.tgz` | 50.4 K | 58 | `Task` + 运行时领域纯函数（7 值状态机 / 11 值 `stop_reason` 矩阵 / 预算账本 / tool-call 状态 / 5 端口） |
| 8 | `wbtime-ports-0.3.0.tgz` | 19.8 K | 31 | 队列/调度端口空实现（登记「未启用」，归 V0.5.0） |
| 9 | `wbtime-security-0.3.0.tgz` | 48.3 K | 22 | 规则注册表（凭据 5 + PII 3 + 注入 2 + `baseline` 底线）+ `detectSensitive`/`redactSensitive` 同源 + `scanSensitive` |
| 10 | `web-dist-0.3.0.tar.gz` | 414.7 K | 46 | 前端构建产物（19 页面分包，**已排除 35 个 sourcemap**） |
| — | `SHA256SUMS` | 0.9 K | — | 上述 10 个文件的 sha256 |

**合计**：约 **1.0 M**（1 025 224 B）。

> **与卡面的 1 处偏离**：卡面写「**8 库包**」（沿用 v0.1.0 口径），本目录实际 **9 个库包** ——
> `@wbtime/security` 是 V0.2.0 M-04 下沉、V0.3.0 起为 `apps/api` 的**直接依赖**，且是 **DoD#7 安全链基线的承重件**；
> 排除它会产出一个缺依赖、不可装配的分发集。裁定见台账 `风险与决策.md` §D-2。

## 2. 如何验证

```bash
cd release/v0.3.0
sha256sum -c SHA256SUMS          # 10 个文件全部 OK

# 包内版本自证（防止"版本只改了仓内、没进包"）
for f in *.tgz; do tar xzOf "$f" package/package.json | python -c 'import json,sys;d=json.load(sys.stdin);print(d["name"], d["version"])'; done

# 抽查某个包的完整性
tar tzf wbtime-db-0.3.0.tgz | head -5
tar tzf wbtime-db-0.3.0.tgz | grep -c '^package/dist/'   # 253
```

本轮实测：`sha256sum -c SHA256SUMS` ⇒ **10/10 OK，exit 0**；9 个库包内 `version` 全部 `0.3.0`。

## 3. 与 V0.3.0 DoD 的对应

| DoD | 在本包中的体现 |
|---|---|
| #1 主链 e2e + 19 通道 + 前 5 条不变量 | `wbtime-event`（19 通道 + golden 编码器）+ `wbtime-db`（run / tool_call / agent_event 仓储）+ `wbtime-domain`（状态机 / 预算）+ `web-dist`（Chat 流式前端） |
| #2 SSRF / 路径逃逸负向 | 守卫实现属 `apps/api`（应用层，见 §4）；包内不含属形态决定 |
| #3 5 内置工具契约 | 契约真源 `BUILTIN_TOOLS` 在 `wbtime-db`；实现同 #2 |
| #4 回放 + `Last-Event-ID` 续传 | `wbtime-event`（游标语义）+ `wbtime-db`（`agent_event` 仓储） |
| #5 `code_exec` 等价 | 实现属 `apps/api`（应用层） |
| #6 四段事务边界 | `wbtime-db`（`tool_call` 状态迁移）+ `wbtime-domain`（终态判定） |
| #7 安全链基线 | **`wbtime-security`**（规则注册表 / REDACT 同源）+ `wbtime-db`（`audit_log` / `feature_flag` 仓储） |
| #8 v0019 | **`wbtime-db`**（`dist/schema/{pg,sqlite}/**`：61 表 / 630 列 / `agent_run.stop_reason`）+ `wbtime-domain`（11 值 `stop_reason` / 7 值 `status`） |

> 测试证据不在包内，在台账 `03-台账/DoD-V0.3.0.md`（逐条命令 + exit code）。

## 4. 本包**不**包含什么（刻意）

| 项 | 原因 |
|---|---|
| `apps/api/**`（服务宿主、5 内置工具实现、SSRF/路径守卫、安全六挂点） | 属可运行的**仓库形态**，不是 npm 库；V0.8.0 才有 CLI 形态 |
| 测试与门禁脚本（`scripts/`、`*/tests/**`） | 仓库资产，随仓库分发，不进 npm 包 |
| `apps/web/src` | 源码随仓库；包内只有构建产物 |
| sourcemap（35 个） | 体积占 dist 的大头，属调试辅助；需要时 `pnpm --filter @wbtime/web build` 重建 |
| `@wbtime/e2e` | 测试包（零依赖是 S-1 判据前提），无运行时价值 |
| `output/` 自省产物 | gitignore 的可复现产物，由 `pnpm --filter @wbtime/db introspect` 重建 |
| Electron 安装器 / CLI 二进制 | 形态未到（V0.9.0 / V0.8.0） |
| **V0.2.0 的包** | V0.2.0 未出包（欠账 D-1），已并入本版；理由见台账 `发布登记.md` §7 |
| `contracts/**` 原始冻结件 | 消费方经 `wbtime-contracts` 的派生类型 + `contracts/frontend-baseline/**` 投影使用；原始件随仓库（证据与 sha256 台账在仓库侧） |

## 5. 复现本包

```bash
pnpm install --frozen-lockfile
pnpm -r --filter '!@wbtime/e2e' build
DEST="$(pwd)/release/v0.3.0"
pnpm --filter './packages/*' --filter '!@wbtime/e2e' exec pnpm pack --pack-destination "$DEST"
tar czf "$DEST/web-dist-0.3.0.tar.gz" -C apps/web/dist --exclude='*.map' .
cd "$DEST" && sha256sum *.tgz *.tar.gz > SHA256SUMS
```

> `SHA256SUMS` 记录**产物哈希** ⇒ 重跑 pack 必然得到不同 sha256（tarball 含时间戳等元数据）。
> **可复现的是构建内容与版本串，不是 tarball 字节。**

## 6. 校验前置

出包前已确认：

- **版本串全栈一致**：**13 个 `package.json`（根 + 2 apps + 10 packages）全为 `0.3.0`**；`git diff --stat` = 13 files / +13 / −13（只动 `version` 行）
- **全包构建退出 0**：11 个单元 `Done`（含 `web: ✓ 2089 modules transformed`）
- **门禁全绿**：`pnpm gate:all` exit 0（12 条脚本链）· `pnpm check` exit 0 · `pnpm typecheck` exit 0 · `check_docs.py` PASS
- **冻结面零变化**：DDL `61/630/176`（v0019）+ `61/629/176`（v0018）· OpenAPI `100/134/116` · SSE 19 帧 sha256 全等 · 前端 243 文件 + 4 个已登记例外（fdiff exit 0）
- **测试全绿**：api `566/566`（files=66，带 `WBTIME_PY_ORACLE_PYTHON`）· workspace `pnpm -r test` exit 0 · `pnpm test:e2e:all` 四组 `21 pass` · `run-runtime-e2e.mjs` `13/13`
- **未验证（如实登记）**：真实厂商连通性烟测（凭据不可得）· PG 运行时 e2e（依赖不可得）
