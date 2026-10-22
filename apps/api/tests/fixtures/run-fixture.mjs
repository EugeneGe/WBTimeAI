/**
 * T3-08 · runs/SSE 测试的共用夹具。
 *
 * 为什么单独成件：`runs-lifecycle` / `runs-cancel` / `sse-dispatch` / `event-cursor`
 * 四个文件都要"造一条可跑的 run"，而 run 的父链（workspace → agent → agent_version →
 * conversation）有 4 层 FK。四份各写一次，任何一处漏一列都会以"FK constraint failed"
 * 的形式红在**别的**用例上，排障成本远高于找一个共享文件。
 *
 * 为什么 agent / conversation 走**真路由**、agent_version / agent_run 走**裸 SQL**
 * -------------------------------------------------------------------------------
 *   - agent 与 conversation 有创建 op（`POST /agents` / `POST /conversations`）⇒ 走真路由
 *     顺带证明"本卡的 run 能挂在真链路上"，比自己拼三张表更接近真实形态；
 *   - `agent_version` 只在 `POST /agents/{id}/publish` 时产生，而 publish 会带上版本
 *     快照（skill / model 配置），对本卡的判据是干扰 ⇒ 裸 SQL 插一行最小版本；
 *   - `agent_run` **没有创建 op**（契约无 `POST /runs`；run 由 `POST /agents/{id}/run`
 *     的入口回执创建，归 T3-05 的偏差登记）⇒ 测试必须自己插。
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

import { ORG_ID, request, TENANT_ID } from "../routes-harness.mjs";

/** 本族测试的工作区（与 conversation 测试分开，避免互相污染 id 空间）。 */
export const WORKSPACE_ID = "3d3d3d3d-0000-4000-8000-0000000000d3";

/** 别租户工作区（跨租户 404 的靶子）。 */
export const OTHER_WORKSPACE_ID = "4d4d4d4d-0000-4000-8000-0000000000d4";

/** 别租户 user / agent / version / conversation / run（跨租户用例整链）。 */
export const OTHER_GRAPH = Object.freeze({
  userId: "4e4e4e4e-0000-4000-8000-0000000000e4",
  agentId: "4a4a4a4a-0000-4000-8000-0000000000a4",
  versionId: "4b4b4b4b-0000-4000-8000-0000000000b4",
  conversationId: "4c4c4c4c-0000-4000-8000-0000000000c4",
  runId: "4f4f4f4f-0000-4000-8000-0000000000f4",
});

/** 插本租户工作区（`conversation.workspace_id` NOT NULL + FK 要求它存在）。 */
export function seedWorkspace(fixture) {
  fixture.raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, ?, ?, '工作区 R', 'PERSONAL')"
    )
    .run(WORKSPACE_ID, TENANT_ID, ORG_ID, fixture.userId);
}

/**
 * 走真路由造 agent + 裸 SQL 插一个最小 `agent_version`。
 *
 * @returns `{ agentId, versionId }`。
 */
export async function createAgentWithVersion(fixture, name = "run 测试 Agent") {
  const created = await request(fixture, "POST", "/api/v1/agents", { payload: { name } });
  assert.equal(created.statusCode, 201, created.body);
  const agentId = JSON.parse(created.body).data.id;

  const versionId = randomUUID();
  fixture.raw
    .prepare(
      `insert into agent_version
         (id, agent_id, version, system_prompt, model_config, runtime_config, status, created_by, created_at)
       values (?, ?, 'v1', '你是测试助手', '{}', '{}', 'DRAFT', ?, '2026-10-22 00:00:00')`
    )
    .run(versionId, agentId, fixture.userId);

  return { agentId, versionId };
}

/** 走真路由造 conversation。 */
export async function createConversation(fixture, agentId) {
  const created = await request(fixture, "POST", "/api/v1/conversations", {
    payload: { agent_id: agentId, workspace_id: WORKSPACE_ID },
  });
  assert.equal(created.statusCode, 201, created.body);
  return JSON.parse(created.body).data.id;
}

/**
 * 裸 SQL 插一条 `agent_run`。
 *
 * `options` 只暴露判据真正关心的字段（其余取建表默认 / 固定值）：
 * `agentId` / `versionId` / `conversationId` 必填，`status` 缺省 `QUEUED`，
 * `stopReason` / `completedAt` / `success` / `errorType` / `error` / `durationMs`
 * 缺省 `null`（进行中形态）。
 *
 * @returns 插入的 run id（`string`）。
 */
export function seedRun(fixture, options) {
  const id = randomUUID();
  fixture.raw
    .prepare(
      `insert into agent_run
         (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id,
          trigger, run_mode, status, started_at, completed_at, duration_ms,
          token_usage, success, error_type, error, stop_reason,
          tool_error_count, cost_estimated, cost_status)
       values (?, ?, ?, ?, ?, ?, 'user', 'INLINE', ?, ?, ?, ?, '{}', ?, ?, ?, ?, 0, 0, 'UNPRICED')`
    )
    .run(
      id,
      options.tenantId ?? TENANT_ID,
      options.agentId,
      options.versionId,
      options.conversationId,
      options.userId === undefined ? fixture.userId : options.userId,
      options.status ?? "QUEUED",
      options.startedAt ?? "2026-10-22 00:00:00",
      options.completedAt ?? null,
      options.durationMs ?? null,
      options.success ?? null,
      options.errorType ?? null,
      options.error ?? null,
      options.stopReason ?? null
    );
  return id;
}

/**
 * 裸 SQL 插一条 `agent_event`（**指定 seq** —— 续读用例要精确造洞）。
 *
 * @param payload 事件 payload（会原样写成 JSON 文本）。
 */
export function seedEvent(fixture, runId, seq, type, payload) {
  fixture.raw
    .prepare(
      "insert into agent_event (id, run_id, type, payload, seq) values (?, ?, ?, ?, ?)"
    )
    .run(randomUUID(), runId, type, JSON.stringify(payload), seq);
}

/**
 * 造一整条**别租户**的 run 链（跨租户 404 用）。
 *
 * 四层 FK 全都要存在，否则插 run 会先去撞 FK 而不是撞 scope —— 那样的红说明不了隔离。
 */
export function seedOtherTenantRun(fixture) {
  const raw = fixture.raw;
  raw
    .prepare(
      "insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
        "values (?, ?, 'other-run-user', 'other-run@example.test', 'x', 'other', 1, 0)"
    )
    .run(OTHER_GRAPH.userId, OTHER_GRAPH_TENANT);

  raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, NULL, ?, '别租户工作区', 'PERSONAL')"
    )
    .run(OTHER_WORKSPACE_ID, OTHER_GRAPH_TENANT, OTHER_GRAPH.userId);

  raw
    .prepare(
      `insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status,
                          current_version_id, created_by, created_at, updated_at)
       values (?, ?, NULL, ?, 'other-agent', NULL, 'general', 'ACTIVE', NULL, ?, '2026-10-22 00:00:00', '2026-10-22 00:00:00')`
    )
    .run(OTHER_GRAPH.agentId, OTHER_GRAPH_TENANT, OTHER_WORKSPACE_ID, OTHER_GRAPH.userId);

  raw
    .prepare(
      `insert into agent_version (id, agent_id, version, system_prompt, model_config, runtime_config, status, created_by, created_at)
       values (?, ?, 'v1', 'x', '{}', '{}', 'DRAFT', ?, '2026-10-22 00:00:00')`
    )
    .run(OTHER_GRAPH.versionId, OTHER_GRAPH.agentId, OTHER_GRAPH.userId);

  raw
    .prepare(
      `insert into conversation (id, tenant_id, workspace_id, agent_id, user_id, title, status,
                                 created_at, updated_at)
       values (?, ?, ?, ?, ?, 'other-conv', 'ACTIVE', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`
    )
    .run(
      OTHER_GRAPH.conversationId,
      OTHER_GRAPH_TENANT,
      OTHER_WORKSPACE_ID,
      OTHER_GRAPH.agentId,
      OTHER_GRAPH.userId
    );

  raw
    .prepare(
      `insert into agent_run
         (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id,
          trigger, run_mode, status, tool_error_count, cost_estimated, cost_status)
       values (?, ?, ?, ?, ?, ?, 'user', 'INLINE', 'RUNNING', 0, 0, 'UNPRICED')`
    )
    .run(
      OTHER_GRAPH.runId,
      OTHER_GRAPH_TENANT,
      OTHER_GRAPH.agentId,
      OTHER_GRAPH.versionId,
      OTHER_GRAPH.conversationId,
      OTHER_GRAPH.userId
    );

  return OTHER_GRAPH.runId;
}

/** 别租户 id（与 `routes-harness.OTHER_TENANT_ID` 同值，此处显式命名以便阅读）。 */
const OTHER_GRAPH_TENANT = "22222222-2222-4222-8222-222222222222";

/** 取某表行数（独立读数）。 */
export function countRows(fixture, table, where = "") {
  const sql = `select count(*) as n from ${table}${where === "" ? "" : ` where ${where}`}`;
  return fixture.raw.prepare(sql).get().n;
}

/** 取某 run 的事件 seq 列表（升序）。 */
export function eventSeqs(fixture, runId) {
  return fixture.raw
    .prepare("select seq from agent_event where run_id = ? order by seq asc")
    .all(runId)
    .map((row) => row.seq);
}
