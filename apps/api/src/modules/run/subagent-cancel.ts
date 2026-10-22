/**
 * V0.3.1 · T031-02 · 子 run 发现与收敛的**叶模块**（零内部依赖，防循环）。
 *
 * 被 `coordinator.ts`（D3 的 HTTP 取消传播）与 `run/delegation.ts`（D3 机制面出口
 * `propagateCancel`）共用 —— 放叶模块是因为二者互为上下游（spawner → guardRunCreation
 * 在 coordinator，delegation → spawner），任何一边持有另一边都会成环。
 *
 * 发现机制（施工记录 T031-02.md 裁定 5，team-lead 2026-10-23 批准）：
 *   **tool_call 行查 + 应用层 JSON 解析** —— 普通列谓词 `(run_id, tool_name, status)`
 *   两侧索引已在，`output.child_run_id` 在应用层 `JSON.parse`，**不写方言 SQL JSON
 *   函数**（`json_extract` / `->>` 分叉在构造上不存在，PG parity 面零新增风险）。
 *   交叉验证：子 run 自身事件流首条 `subagent.started` 的 `payload.parent_run_id`
 *   必须指回父 run（双源一致性，不一致的子 id 剔除并交由调用方判红）。
 */

import {
  AgentEventRepo,
  AgentRunRepo,
  Scope,
  TERMINAL_AGENT_RUN_STATUSES,
  ToolCallRepo,
  type AgentRunRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

/** `spawn_agent` 成功调用的 `tool_call.output.child_run_id`（父侧还原源）。 */
function childRunIdsFromParent(
  db: DrizzleDatabase,
  scope: Scope,
  dialect: SqlDialect,
  parentRunId: string
): Promise<string[]> {
  const toolCalls = new ToolCallRepo(db, scope, scope.ref(parentRunId), dialect);
  return toolCalls
    .listByToolName("spawn_agent")
    .then((rows) =>
      rows
        .filter((row) => row.status === "SUCCESS")
        .map((row) => {
          const output = row.output;
          if (output === null || output === undefined || typeof output !== "object") return null;
          const childRunId = (output as Record<string, unknown>)["child_run_id"];
          return typeof childRunId === "string" && childRunId !== "" ? childRunId : null;
        })
        .filter((id): id is string => id !== null),
    );
}

/**
 * 发现 `parentRunId` 的全部子 run（双源：父侧 tool_call 主查 + 子侧事件交叉验证）。
 *
 * @returns 通过交叉验证的子 run id（去重、保序）。交叉验证失败的 id 被剔除 ——
 *          调用方若以此驱动取消，剔除即"宁可漏、不可错"（与 gap-aware 同哲学）。
 */
export async function discoverChildRunIds(
  db: DrizzleDatabase,
  dialect: SqlDialect,
  tenantId: string,
  parentRunId: string
): Promise<string[]> {
  const scope = new Scope(tenantId);
  const fromParent = await childRunIdsFromParent(db, scope, dialect, parentRunId);
  if (fromParent.length === 0) return [];

  const verified: string[] = [];
  for (const childRunId of new Set(fromParent)) {
    const events = new AgentEventRepo(db, scope, scope.ref(childRunId), dialect);
    const started = await events
      .list({ limit: 50 })
      .then((rows) => rows.find((row) => row.type === "subagent.started"));
    if (started === undefined) continue;
    const payload = started.payload;
    const parentBack = typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)["parent_run_id"]
      : undefined;
    if (parentBack === parentRunId) verified.push(childRunId);
  }
  return verified;
}

/**
 * 把一个 run 收敛到 `CANCELLED`（CAS：仅活跃态可写；已终态 ⇒ 幂等返回现状）。
 *
 * `stop_reason = "cancelled"`（域矩阵 `STOP_REASONS_BY_TERMINAL_STATUS.CANCELLED` 词表内），
 * `error_type = CANCELLED`（与 `RunCoordinator.cancel` 同口径）。
 *
 * @returns `"applied"`（本次写）/ `"already-terminal"`（先前已终态）/ `"missing"`（run 不可见）。
 */
export async function finalizeChildCancelled(
  db: DrizzleDatabase,
  dialect: SqlDialect,
  tenantId: string,
  childRunId: string,
  at: Date | string
): Promise<"applied" | "already-terminal" | "missing"> {
  const scope = new Scope(tenantId);
  const runs = new AgentRunRepo(db, scope, dialect);
  const ref = scope.ref(childRunId);
  const outcome = await runs.finalizeIfActive(ref, {
    status: "CANCELLED",
    stopReason: "cancelled",
    success: false,
    errorType: "CANCELLED",
    completedAt: at,
  });
  if (outcome.applied) return "applied";
  const row: AgentRunRow | null = outcome.row;
  if (row === null) return "missing";
  return (TERMINAL_AGENT_RUN_STATUSES as readonly string[]).includes(row.status)
    ? "already-terminal"
    : "missing";
}
