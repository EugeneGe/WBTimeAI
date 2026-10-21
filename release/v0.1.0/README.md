# V0.1.0 · 可分发包

> **版本**：`0.1.0`（产品版，按 `docs/README.md` N-3 与 `施工纪律.md` §4.2-2 必出包）
> **出包时间**：2026-10-21 08:21 GMT+8
> **形态裁定**：**方案 A — 基座包**（`pnpm pack` 库包 tarball + 前端构建归档）
> **裁定理由**：V0.1.0 是 L0 基座版，无 Electron 壳（归 V0.9.0）、无 CLI（归 V0.8.0）、无服务入口（归 V0.2.0），
> 不产出安装器。其**可分发形态**就是 npm 生态的标准形态 —— 包 tarball + 构建产物归档。
> 选 A 而非"援引 `0.0.x` 豁免"（§4.2-3 明写那是**唯一**豁免档），因为产物**确实可分发**，无需放宽条款。

---

## 1. 产物清单

| # | 文件 | 大小 | 内容 |
|---|---|---|---|
| 1 | `wbtime-contracts-0.1.0.tgz` | 29 K | 9 个扩展点 interface + 冻结件派生类型 + 签名快照 |
| 2 | `wbtime-core-0.1.0.tgz` | 36 K | 30 错误码 / 响应壳 TypeBox / HTTP 状态映射 |
| 3 | `wbtime-config-0.1.0.tgz` | 30 K | env 解析 + `WBTIME_AI_MODE=local\|server` |
| 4 | `wbtime-logging-0.1.0.tgz` | 29 K | pino + AsyncLocalStorage `request_id` 贯通 |
| 5 | `wbtime-event-0.1.0.tgz` | 33 K | 19 个 SSE 通道 + 数值格式归一化 |
| 6 | `wbtime-db-0.1.0.tgz` | 127 K | 61 表双档 drizzle schema + `ScopedRepo<T>` 仓储 |
| 7 | `wbtime-domain-0.1.0.tgz` | 23 K | `Task` 实体（13 字段 ≡ 契约 13 列） |
| 8 | `wbtime-ports-0.1.0.tgz` | 20 K | 队列/调度端口空实现（登记「未启用」） |
| 9 | `web-dist-0.1.0.tar.gz` | 413 K | 前端构建产物（19 页面分包，**已排除 35 个 sourcemap**） |
| — | `SHA256SUMS` | 1 K | 上述 9 个文件的 sha256 |

**合计**：约 750 K。

## 2. 如何验证

```bash
cd release/v0.1.0
sha256sum -c SHA256SUMS          # 9 个文件全部 OK

# 抽查某个包的完整性
tar tzf wbtime-db-0.1.0.tgz | head -5
tar tzf wbtime-db-0.1.0.tgz | grep -c 'dist/'   # 内含编译后的 dist
```

## 3. 与 V0.1.0 DoD 的对应

| DoD | 在本包中的体现 |
|---|---|
| #1 双档 DDL 零差异（176 索引对象） | `wbtime-db` 内含 `dist/schema/{pg,sqlite}/**`（61 表生成物） |
| #2 `type-map.csv` 401/403 列 | `wbtime-db` 的 schema 生成器 + 门禁脚本（脚本不在包内，见 §4） |
| #3 ⑤-a 前端零改动 | `web-dist` 即由**未改动过的 `apps/web/src`** 构建而来 |
| #4 E-1/E-2/E-3 | `wbtime-domain`(Task) + `wbtime-ports`(空实现) + `wbtime-contracts`(9 接口) |
| #5 冒烟/退化/分层 | 见 `docs/V1.0/V0.1.0-.../03-台账/`（测试证据，非包内容） |

## 4. 本包**不**包含什么（刻意）

| 项 | 原因 |
|---|---|
| 测试与门禁脚本（`scripts/`） | 属**仓库资产**，不是运行时依赖；随仓库分发，不进 npm 包 |
| `apps/web/src` | 源码随仓库；包内只有构建产物 |
| sourcemap（35 个） | 体积占 dist 的 79%，且属调试辅助；如需可 `pnpm --filter @wbtime/web build` 重建 |
| `@wbtime/e2e` | 测试包，无运行时价值 |
| `output/` 自省产物 | gitignore 的可复现产物，由 `pnpm --filter @wbtime/db introspect` 重建 |

## 5. 复现本包

```bash
pnpm install --frozen-lockfile
pnpm -r --filter '!@wbtime/e2e' build
DEST="$(pwd)/release/v0.1.0"
pnpm --filter './packages/*' --filter '!@wbtime/e2e' exec pnpm pack --pack-destination "$DEST"
tar czf "$DEST/web-dist-0.1.0.tar.gz" -C apps/web/dist --exclude='*.map' .
cd "$DEST" && sha256sum *.tgz *.tar.gz > SHA256SUMS
```

## 6. 校验前置

出包前已确认：

- **版本串全栈一致**：11 个 `package.json`（根 + 1 app + 9 packages）全为 `0.1.0`
  （出包前实测发现 `@wbtime/e2e` 仍是 `0.0.2`，已修正；并给 `check_baseline` 补了
  `workspace/version一致` 检查项，反例注入已验证会红）
- **全包构建退出 0**：9 个包 `Done`
- **门禁全绿**：`gate:v010` 6/6、`check_baseline` 14/14、契约 42 项 + 双台账
