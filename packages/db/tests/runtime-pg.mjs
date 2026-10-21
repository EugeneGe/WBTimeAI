#!/usr/bin/env node
/**
 * T3-03 · 运行时三仓的 **PG 档显式复跑入口**（R3-20）。
 *
 * 为什么单列一个脚本（与 `scripts/run-parity-pg.mjs` 同一套路）：
 *   * CI 无 PG service ⇒ 塞进默认测试链会**长期常红**，从而诱导后人加
 *     `continue-on-error`（把门禁变成摆设）；
 *   * 但"没跑 PG"绝不等于"PG 通过"⇒ 缺环境必须 **exit 1 + 明确话术**（fail loud），
 *     **禁止** skip / exit 0 / 悄悄退回 SQLite。
 *
 * 判据：SQLite 档与 PG 档**同一组仓储代码**（`dialect` 参数化），只是表对象与
 * 连接不同 —— 本脚本不复制任何断言逻辑，只做"PG 上真跑一遍"的最小闭环。
 *
 * | 情形 | 行为 |
 * |---|---|
 * | 缺 `WBTIME_PG_URL` | **exit 1** + 起隧道/设 env 的提示 + 「未验证（依赖不可得）」 |
 * | URL 有但连不上 / 库里没 schema | exit 1（红得真实，不谎报） |
 * | 库里没有 `agent_run` 行 | exit 1 + 「子表断言未执行（依赖不可得）」 |
 * | 全部跑通 | exit 0 + 实测数字 |
 *
 * 用法：`node packages/db/tests/runtime-pg.mjs`
 */

import { AgentEventRepo, AgentRunRepo, Scope, ToolCallRepo } from "../dist/repositories/index.js";
import { createPgDb } from "../dist/connection.js";

const PG_URL_ENV = "WBTIME_PG_URL";

/** PG 档断言用的租户（PG 库里若无该租户，下面的 run 列表会是空 ⇒ fail loud）。 */
const TENANT = process.env.WBTIME_PG_TENANT_ID ?? "00000000-0000-4000-8000-000000000001";

function failLoud(title, lines) {
  process.stderr.write(`\n[db:pg] FAIL LOUD — ${title}\n`);
  for (const line of lines) process.stderr.write(`  · ${line}\n`);
  process.stderr.write("  ⇒ 结论：**未验证（依赖不可得）**，不得以任何形式记为通过。\n");
  process.exit(1);
}

const url = process.env[PG_URL_ENV] ?? "";
if (url.trim() === "") {
  failLoud("PG 环境不可得", [
    `未设置 ${PG_URL_ENV}`,
    "设置方式（口令见 gitignored 的 `docs/*服务器总览.md`，**不入库**）：",
    `  export ${PG_URL_ENV}='postgres://<USER>:<PASSWORD>@127.0.0.1:5433/wbtime_ai_parity'`,
    "PG 只监听远端 127.0.0.1:5432 ⇒ 需先起 SSH 隧道（本地 5433 → 远端 5432）。",
    "本脚本**不会**自动退回 SQLite —— 那会让「PG 档」这个词失去意义。",
  ]);
}

const handle = createPgDb(url);
const scope = new Scope(TENANT);

try {
  const runs = new AgentRunRepo(handle.db, scope, "pg");
  const rows = await runs.list({ limit: 1 });
  if (rows.length === 0) {
    failLoud("PG 库里没有 agent_run 行 ⇒ 子表断言无法执行", [
      `tenant=${TENANT}`,
      "先在 PG 库灌入运行时父链（tenant / agent / agent_version / conversation / agent_run），",
      `或换一个已有 run 的租户（${PG_URL_ENV} + WBTIME_PG_TENANT_ID）。`,
    ]);
  }

  const runRef = scope.ref(rows[0].id);
  const events = new AgentEventRepo(handle.db, scope, runRef, "pg");
  const calls = new ToolCallRepo(handle.db, scope, runRef, "pg");

  const eventRows = await events.list({ limit: 5 });
  const callRows = await calls.list({ limit: 5 });
  const maxSeq = await events.maxSeq();

  process.stdout.write(
    `\n[db:pg] PASS — 运行时三仓在 PG 档跑通（dialect=pg）\n` +
      `  agent_run: 1 行可读（id=${rows[0].id}）\n` +
      `  agent_event: ${eventRows.length} 行可读，maxSeq=${maxSeq}\n` +
      `  tool_call: ${callRows.length} 行可读\n`,
  );
} finally {
  await handle.close();
}

process.exit(0);
