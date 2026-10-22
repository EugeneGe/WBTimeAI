# V0.3.0 · 可分发包

> **版本**：`0.3.0`（产品版，按 `docs/README.md` N-3 与 `施工纪律.md` §4.2-2 必出包）
> **出包时间**：2026-10-22 20:04 GMT+8（首发）· **2026-10-22 23:2x GMT+8（重出 #2，同日复核修复批）**
> **重出原因**：闭版树收到独立复核审计（17 条：P1×3 / P2×7 / P3×7），用户裁定「全量修 + 重出包」。本包是**修复后重建**，与首发同名同版本、**字节不同**（见 §6.1 的「包内体现边界」）。
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
| 6 | `wbtime-db-0.3.0.tgz` | 293.9 K | 254 | 61 表双档 drizzle schema（v0019 = 630 列）+ `ScopedRepo<T>` 九仓储（**重出 #2 变更**：`finalizeIfActive` 条件终态写 + `listTail` 尾部窗口） |
| 7 | `wbtime-domain-0.3.0.tgz` | 50.4 K | 58 | `Task` + 运行时领域纯函数（7 值状态机 / 11 值 `stop_reason` 矩阵 / 预算账本 / tool-call 状态 / 5 端口） |
| 8 | `wbtime-ports-0.3.0.tgz` | 19.8 K | 31 | 队列/调度端口空实现（登记「未启用」，归 V0.5.0） |
| 9 | `wbtime-security-0.3.0.tgz` | 48.3 K | 22 | 规则注册表（凭据 5 + PII 3 + 注入 2 + `baseline` 底线）+ `detectSensitive`/`redactSensitive` 同源 + `scanSensitive` |
| 10 | `web-dist-0.3.0.tar.gz` | 415.3 K | 44 | 前端构建产物（19 页面分包，**已排除 35 个 sourcemap**；重出 #2 变更 = 聊天审批闭环，分包边界随之微调：46 → 44 文件） |
| — | `SHA256SUMS` | 0.9 K | — | 上述 10 个文件的 sha256 |

**合计**：约 **1.0 M**（**1 029 874 B**；首发 1 025 224 B，重出 #2 +4 650 B）。

> **重出 #2 的哈希变化面（必须写明，防止「以为整包重打了」）**：9 个库包中**只有 `wbtime-db` 变了**
> （`8c8e25e8…`）；config / contracts / core / domain / event / logging / ports / security **八个包的 sha256 与首发逐字节相同**
> —— 本批没有改它们的源码。`web-dist` 亦变（`915e0f58…`）。这是「只重打有变化的产物」的正常结果，不是漏打。

> **口径纠正（1 条，非偏离）**：卡面写「**8 库包**」是 **V0.1.0 的存量表述**、未随 `@wbtime/security` 入册同步；
> 本版实际分发集为 **9 个库包** —— `@wbtime/security` 是 V0.2.0 M-04 下沉、V0.3.0 起为 `apps/api` 的**直接依赖**，
> 且是 **DoD#7 安全链基线的承重件**；排除它会产出一个缺依赖、不可装配的分发集。
> **这是计划侧表述滞后，不是本包偏离计划。** 裁定见台账 `风险与决策.md` §D-2。

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

### 2.1 安装：**必须 9 个 tgz 一起装，不要单装**

`pnpm pack` 把内部的 `workspace:*` 重写成了**精确版本**（如 `wbtime-db` 依赖 `@wbtime/domain: "0.3.0"`，无 `^`）。因此：

```bash
# ✅ 正确：一次装整组，npm 会在同一次解析里满足内部依赖
npm install ./release/v0.3.0/*.tgz

# ❌ 错误：单装一个包
npm install ./release/v0.3.0/wbtime-db-0.3.0.tgz
#   → 404 Not Found - GET https://registry.npmjs.org/@wbtime%2fdomain
#   因为 @wbtime/* 未发布到 registry，只有本目录的 tarball 里才有
```

本轮实测（临时目录，`npm init -y` 后）：`npm install ./release/v0.3.0/*.tgz` ⇒ **`added 37 packages in 20s`，exit 0**；随后 ESM 导入自证：
`@wbtime/core` 导出 29 个符号 · `@wbtime/db` 132 个 · `@wbtime/security` 16 个；
`detectSensitive('key=sk-…')` ⇒ `[{"ruleId":"cred.openai_sk.v1","category":"credential",…}]`（安全包功能真跑，不只是能 import）。

> **另**：9 个包均 `private: true` ⇒ 本分发集是**整组 tarball 分发**形态（方案 A），**不能 `npm publish`**。若将来要上 registry，需独立发包波（去 `private` + 内部依赖改 `^` + 版本编排），见台账 `风险与决策.md` §R-9。

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
cd "$DEST" && sha256sum -b *.tgz *.tar.gz > SHA256SUMS   # `-b` ⇒ `*` 前缀，与随包发布的 SHA256SUMS 同格式
```

> `SHA256SUMS` 记录**产物哈希** ⇒ 重跑 pack 必然得到不同 sha256（tarball 含时间戳等元数据）。
> **可复现的是构建内容与版本串，不是 tarball 字节。**

## 6. 校验前置

出包前已确认：

- **版本串全栈一致**：**13 个 `package.json`（根 + 2 apps + 10 packages）全为 `0.3.0`**（重出 #2 未改版本号：同版本、不同字节，口径见 §6.1）
- **全包构建退出 0**：11 个单元 `Done`
- **门禁全绿**：`pnpm gate:all` exit 0（12 条脚本链）· `pnpm check` exit 0 · `pnpm typecheck` exit 0 · `check_docs.py` PASS
- **冻结面零变化**：DDL `61/630/176`（v0019）+ `61/629/176`（v0018）· OpenAPI `100/134/116` · SSE 19 帧 sha256 全等 · 前端 243 文件 + **9 个已登记例外**（F-4 四条 + AUD-06 五条；fdiff exit 0）
- **测试全绿**：api **`596/596`（files=70，带 `WBTIME_PY_ORACLE_PYTHON`）** · workspace `pnpm -r test` exit 0（db **186** / web **505**）· `pnpm test:e2e:all` 四组 `21 pass` · `run-runtime-e2e.mjs` `13/13` · i18n **1132/1132** 双向相等
- **未验证（如实登记）**：真实厂商连通性烟测（凭据不可得）· PG 运行时 e2e（依赖不可得）

### 6.1 重出 #2 的「包内体现边界」（**不要误读成「P1 修复在包里」**）

本批 12 条代码修复里，**多数落在 `apps/api`** —— 按方案 A，`apps/api` 是**仓库运行形态**，不进 9 个库包。因此：

| 修复 | 落在哪 | 是否在包内 |
|---|---|---|
| AUD-01 / AUD-03（`listTail` / `finalizeIfActive`） | `@wbtime/db` | ✅ **在包内**（`wbtime-db` 的 sha 已变） |
| AUD-06（审批闭环） | `apps/web` | ✅ **在包内**（`web-dist`） |
| AUD-02 / 04 / 05 / 07 / 09 / 10 / 11 / 14 / 17 | `apps/api` | ❌ **不在包内** —— 随仓库运行形态交付（`pnpm --filter @wbtime/api start`） |

**所以：只装这 9 个 tgz 的消费方拿到的是「库层 + 前端」的修复，拿不到运行时修复。** 这是方案 A 的形态结论，不是打包遗漏；要分发运行时，须等 V0.9.0 的壳 / V0.8.0 的 CLI。
