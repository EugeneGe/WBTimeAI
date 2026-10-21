/**
 * T3-03 · 运行时夹具（`node:sqlite` 真库 + 仓内既有 DDL）。
 *
 * 两条**实测**约束（踩过一次，写在这里免得重复踩）：
 *   1. `node:sqlite` **默认开启外键**（`PRAGMA foreign_keys = 1`）⇒ 父行必须先插，
 *      且**造不出悬空引用**（所以「父不存在」只能用「父属别的租户」来构造）；
 *   2. 双档 DDL 里 `id` 列**无默认值** ⇒ 每一行都要显式给 id。
 *
 * 父链：`tenant → user → workspace → agent → agent_version → conversation → agent_run`，
 * 其中 `agent_run` 是 `agent_event` / `tool_call` 的父。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 用**相对路径**引自己的构建产物：包不能 import 自己（node_modules 里没有自己）。
import { createSqliteDb } from "../../dist/connection.js";

const DDL = readFileSync(
  fileURLToPath(new URL("../../../../output/ddl.sqlite.sql", import.meta.url)),
  "utf8",
);

export const DIALECT = "sqlite";

/** 灌整份 SQLite DDL 建内存库（顺带证明 DDL 可执行 + 连接工厂可用）。 */
export function freshConnection() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  return connection;
}

export const T_A = "11111111-1111-4111-8111-111111111111";
export const T_B = "22222222-2222-4222-8222-222222222222";

const IDS = Object.freeze({
  userA: "aaaa0000-0000-4000-8000-000000000001",
  userB: "bbbb0000-0000-4000-8000-000000000002",
  wsA: "aaaa0000-0000-4000-8000-000000000011",
  wsB: "bbbb0000-0000-4000-8000-000000000012",
  agentA: "aaaa0000-0000-4000-8000-000000000021",
  agentB: "bbbb0000-0000-4000-8000-000000000022",
  versionA: "aaaa0000-0000-4000-8000-000000000031",
  versionB: "bbbb0000-0000-4000-8000-000000000032",
  convA: "aaaa0000-0000-4000-8000-000000000041",
  convB: "bbbb0000-0000-4000-8000-000000000042",
  runA: "aaaa0000-0000-4000-8000-000000000051",
  runA2: "aaaa0000-0000-4000-8000-000000000052",
  runB: "bbbb0000-0000-4000-8000-000000000053",
});

export { IDS };

/**
 * 建两个租户的完整父链 + 三个 run（A 两个、B 一个）。
 *
 * 用**原生 SQL** 灌父链（不是被测仓储）：夹具必须独立于被测代码，
 * 否则"仓储写错了"会连带把夹具写坏，红得不知所云。
 *
 * @param connection {@link freshConnection} 的返回值（要用它的 `raw` 灌父链）。
 */
export function seedParents(connection) {
  const raw = connection.raw;
  const insert = (sql) => {
    raw.exec(sql);
  };

  // 租户
  for (const [id, name] of [
    [T_A, "tenant-a"],
    [T_B, "tenant-b"],
  ]) {
    insert(
      `insert into tenant (id, name, slug, is_active, created_at, updated_at) values ` +
        `('${id}', '${name}', '${name}', 1, '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
    );
  }

  // 用户
  for (const [id, tenant, name] of [
    [IDS.userA, T_A, "alice"],
    [IDS.userB, T_B, "bob"],
  ]) {
    insert(
      `insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser, created_at, updated_at) values ` +
        `('${id}', '${tenant}', '${name}', '${name}@example.test', 'x', '${name}', 1, 0, '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
    );
  }

  // 工作区（owner = 上面的 user）
  for (const [id, tenant, owner, name] of [
    [IDS.wsA, T_A, IDS.userA, "ws-a"],
    [IDS.wsB, T_B, IDS.userB, "ws-b"],
  ]) {
    insert(
      `insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type, settings, config, created_at, updated_at) values ` +
        `('${id}', '${tenant}', null, '${owner}', '${name}', 'personal', '{}', '{}', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
    );
  }

  // agent
  for (const [id, tenant, owner, name] of [
    [IDS.agentA, T_A, IDS.userA, "agent-a"],
    [IDS.agentB, T_B, IDS.userB, "agent-b"],
  ]) {
    insert(
      `insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status, current_version_id, created_by, created_at, updated_at) values ` +
        `('${id}', '${tenant}', null, null, '${name}', null, 'general', 'ACTIVE', null, '${owner}', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
    );
  }

  // agent_version（model_config / runtime_config NOT NULL）
  for (const [id, agent, owner] of [
    [IDS.versionA, IDS.agentA, IDS.userA],
    [IDS.versionB, IDS.agentB, IDS.userB],
  ]) {
    insert(
      `insert into agent_version (id, agent_id, version, system_prompt, model_config, runtime_config, status, created_by, created_at) values ` +
        `('${id}', '${agent}', 'v1', 'sys', '{}', '{}', 'DRAFT', '${owner}', '2026-10-22 00:00:00')`,
    );
  }

  // conversation（workspace_id NOT NULL）
  for (const [id, tenant, ws, agent, user] of [
    [IDS.convA, T_A, IDS.wsA, IDS.agentA, IDS.userA],
    [IDS.convB, T_B, IDS.wsB, IDS.agentB, IDS.userB],
  ]) {
    insert(
      `insert into conversation (id, tenant_id, organization_id, workspace_id, agent_id, user_id, title, status, created_at, updated_at) values ` +
        `('${id}', '${tenant}', null, '${ws}', '${agent}', '${user}', 'conv', 'ACTIVE', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
    );
  }

  // agent_run：A 两个（主链 + 隔离对照）、B 一个（跨租户对照）
  const runs = [
    { id: IDS.runA, tenant: T_A, agent: IDS.agentA, version: IDS.versionA, conv: IDS.convA, user: IDS.userA, key: "idem-a-1" },
    { id: IDS.runA2, tenant: T_A, agent: IDS.agentA, version: IDS.versionA, conv: IDS.convA, user: IDS.userA, key: "idem-a-2" },
    { id: IDS.runB, tenant: T_B, agent: IDS.agentB, version: IDS.versionB, conv: IDS.convB, user: IDS.userB, key: "idem-b-1" },
  ];
  for (const run of runs) {
    insert(
      `insert into agent_run (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id, task_id, trigger, run_mode, status, trace_id, span_id, last_heartbeat_at, idempotency_key, started_at, completed_at, duration_ms, token_usage, success, error_type, tool_error_count, cost, cost_currency, cost_price_version, cost_estimated, cost_breakdown, cost_status, error, stop_reason) values ` +
        `('${run.id}', '${run.tenant}', '${run.agent}', '${run.version}', '${run.conv}', '${run.user}', null, 'user', 'INLINE', 'QUEUED', null, null, null, '${run.key}', null, null, null, null, null, null, 0, null, null, null, 0, null, 'UNPRICED', null, null)`,
    );
  }

  return { runs };
}
