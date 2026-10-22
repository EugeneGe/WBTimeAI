/**
 * V0.3.1 · T031-02 · 委派执行链宿主（D3 / D4 / D5 + S3 附加判据）。
 *
 * 《调用契约》六导出（apps/api/tests/subagent-delegation.test.mjs 文件头，签名逐字钉死）：
 *   1. {@link delegateSpawn} —— 派生单入口（S3 闸 → 深度闸 → 并发闸 → 建子 run → 双源写行）
 *   2. {@link resolveChildBudget} —— 预算下拨（纯函数，逐维 ≤ 父）
 *   3. {@link applyChildBudget} —— 预算闸（纯函数，复用域判定 `pickBudgetStopReason`）
 *   4. {@link intersectPermissionScope} —— 权限收窄（纯函数，**形参名钉死**：
 *      `parentScope` / `targetScope` —— `v031-scope-passthrough` 反例锚点依赖形参名）
 *   5. {@link isToolAllowedInScope} —— 判权（纯函数）
 *   6. {@link propagateCancel} —— D3 机制面出口（行为判据走 HTTP，本函数是接口契约）
 *
 * 八裁定落点（施工记录 `docs/.../施工记录/T031-02.md`）：
 *   - 裁定 1：子 run 执行**复用 RunDriver**（禁内联）—— 生产装配（T031-04）把驱动
 *     面接进 {@link delegateSpawn} 的调用方；本文件不含任何自建执行循环。
 *   - 裁定 2：父流侧 `subagent.started / finished` **事件行**由本链写入（T031-05 只做
 *     下发注册 + 关门比对）。事件行 payload ⊇ 帧冻结键序（`policy_version` 是行级
 *     域字段；帧组装时由 T031-05 按 `channels.delta.json` 的 `payload_keys_in_order`
 *     选键——行与帧是两层，见 spawner 的同款注释）。
 *   - 裁定 4：`CONCURRENCY_LIMIT` 为防御位（可达条件 = T031-04 接线后 origin 误传）。
 *   - 裁定 5：子 run 发现 = tool_call 行查 + 应用层 JSON 解析（零方言分叉），见
 *     `subagent-cancel.ts`。
 */

import { randomUUID } from "node:crypto";

import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";
import {
  DEPTH_EXCEEDED_REASON,
  MAX_SUBAGENT_DEPTH,
  pickBudgetStopReason,
} from "@wbtime/domain";

import { SafetyGate, type SafetyVerdict } from "../safety/gate.js";
import { evaluateDelegation } from "../safety/stages/delegation.js";
import { isDepthAllowed } from "./subagent-guard.js";
import { discoverChildRunIds, finalizeChildCancelled } from "./subagent-cancel.js";
import { SubAgentSpawner, type SpawnRejectReason } from "./subagent-spawner.js";

// ---------------------------------------------------------------------------
// D4 · 预算下拨与预算闸（纯函数）
// ---------------------------------------------------------------------------

/** 子 run 预算形状（四维，可部分缺省；与判据 `BUDGET_DIMENSIONS` 一一对应）。 */
export interface ChildBudget {
  readonly maxTokens?: number;
  readonly maxCost?: number;
  readonly maxTurns?: number;
  readonly maxTools?: number;
}

/** 预算闸的输入（`usage` 键 = 消耗计数，与判据 `usageKey` 对齐）。 */
export interface ChildBudgetUsage {
  readonly tokens?: number;
  readonly cost?: number;
  readonly turns?: number;
  readonly tools?: number;
}

const BUDGET_KEYS = ["maxTokens", "maxCost", "maxTurns", "maxTools"] as const;
const USAGE_KEY_OF: Record<(typeof BUDGET_KEYS)[number], keyof ChildBudgetUsage> = {
  maxTokens: "tokens",
  maxCost: "cost",
  maxTurns: "turns",
  maxTools: "tools",
};

function isPositiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * D4 · 预算下拨：**逐维 ≤ 父**（双向钉死）。
 *
 * - `hint` 给了某维 ⇒ `min(hint, 父)`（hint 超父必须 cap，不得上调）；
 * - `hint` 缺某维 ⇒ 继承父该维（缺 hint 不得超父 —— 恒等继承天然满足）；
 * - **父缺某维 ⇒ 结果不含该维**（无法验证「≤ 父」就 fail-closed 不下拨，
 *   而不是猜一个上限 —— 静默猜值会把编程错误变成“看起来正常的多拨”）；
 * - hint 值非法（非正有限数）⇒ 视同缺省（继承父），不抛错（下拨是纯函数）。
 *
 * @param parentBudget 父 run 的预算（逐维）。
 * @param hint 派生请求附带的预算 hint（`spawn_agent.budget_hint` 的解析结果；可缺省）。
 */
export function resolveChildBudget(parentBudget: ChildBudget, hint?: ChildBudget): ChildBudget {
  const parent = parentBudget ?? {};
  const result: Record<string, number> = {};
  for (const key of BUDGET_KEYS) {
    const parentValue = (parent as Record<string, unknown>)[key];
    if (!isPositiveFinite(parentValue)) continue;
    const hintValue = hint === undefined ? undefined : (hint as Record<string, unknown>)[key];
    result[key] = isPositiveFinite(hintValue) ? Math.min(hintValue, parentValue) : parentValue;
  }
  return result;
}

/**
 * `ChildBudget` → `Record<string, number>`（**显式映射**，不是 `as` 硬抹）。
 *
 * 为什么安全、为什么必须显式：
 *   - `ChildBudget` 的四维是**闭集**（`BUDGET_KEYS`），每维类型收窄为 `number`；
 *     这里按闭集逐键挑选、非正有限值剔除，产出对象的**键集 ⊆ `BUDGET_KEYS`**、
 *     值集 ⊆ `number` —— 是构造上的收窄，不是断言上的绕过。
 *   - 直接 `as Record<string, number>` 会把**未来新增的非数值字段也放行**进 JSON
 *     列（`subagent.started.payload.budget`），把一次类型漂移变成静默的脏数据；
 *     显式映射把"新增维度"变成"必须回来加一行"的编译期提醒。
 *
 * @returns 预算快照（`Record<string, number>`）；入参 `undefined` ⇒ `undefined`（不下拨）。
 */
export function toBudgetRecord(budget: ChildBudget | undefined): Record<string, number> | undefined {
  if (budget === undefined || budget === null) return undefined;
  const source = budget as Record<string, unknown>;
  const record: Record<string, number> = {};
  for (const key of BUDGET_KEYS) {
    const value = source[key];
    if (isPositiveFinite(value)) record[key] = value;
  }
  return record;
}

/**
 * S3 拒绝的原因码（**取自 `SafetyVerdict` 的真实字段** —— `SafetyVerdict` 没有
 * `reasonCode`，命中的规则 id 在 `hits[].ruleId`；不存在的字段不得凭空引用）。
 */
function safetyDenyDetail(verdict: SafetyVerdict): string {
  const first = verdict.hits.length > 0 ? verdict.hits[0] : undefined;
  const ruleId = first === undefined ? null : String(first.ruleId ?? "");
  return ruleId === null || ruleId === "" ? "SAFETY_RULE_HIT" : ruleId;
}

/**
 * D4 · 预算闸：消耗触顶（**≥ 上限**）⇒ 必中断，`stopReason` 与触发维度一致（K-4：
 * 复用域判定 `pickBudgetStopReason`，`budget_*` 四值都在 11 值 `STOP_REASONS` 词表内，
 * **不自造** `BUDGET_EXCEEDED`）。
 *
 * 「触顶」取 `>=`（消耗抵达上限即停 —— 保证 `token_usage ≤ B` 恒成立）；四维按
 * 域优先序（R3-01）挑出唯一 `stopReason`。未触顶 ⇒ `{ exceeded: false }`（无
 * `stopReason` 键 —— “未停就不该有停因”，防调用方误读）。
 */
export function applyChildBudget(input: {
  readonly budget: ChildBudget;
  readonly usage: ChildBudgetUsage;
}): { readonly exceeded: true; readonly stopReason: "budget_tokens" | "budget_cost" | "budget_turns" | "budget_tools" } | { readonly exceeded: false } {
  const budget = (input?.budget ?? {}) as Record<string, unknown>;
  const usage = (input?.usage ?? {}) as Record<string, unknown>;
  const flags: { tokens?: boolean; cost?: boolean; turns?: boolean; tools?: boolean } = {};
  for (const key of BUDGET_KEYS) {
    const limit = budget[key];
    if (!isPositiveFinite(limit)) continue;
    const used = usage[USAGE_KEY_OF[key]];
    if (typeof used === "number" && Number.isFinite(used) && used >= limit) {
      flags[USAGE_KEY_OF[key]] = true;
    }
  }
  const stopReason = pickBudgetStopReason(flags);
  if (stopReason === null) return { exceeded: false };
  return { exceeded: true, stopReason };
}

// ---------------------------------------------------------------------------
// D5 · 权限收窄与判权（纯函数；形参名钉死 —— 反例锚点依赖）
// ---------------------------------------------------------------------------

function scopeCodeSet(scope: readonly string[] | ReadonlySet<string> | null | undefined): Set<string> {
  if (scope === null || scope === undefined) return new Set();
  return new Set([...scope].map(String));
}

/**
 * D5 · 权限收窄 = **父 ∩ 目标**（结果 ⊆ 父；target ⊆ 父时 == target —— 防恒空集）。
 *
 * ⚠️ 形参名 `parentScope` / `targetScope` 是判据锚点（`v031-scope-passthrough`
 * 反例按形参名注入），**不得改名**。
 */
export function intersectPermissionScope(
  parentScope: readonly string[] | ReadonlySet<string>,
  targetScope: readonly string[] | ReadonlySet<string>
): string[] {
  const parent = scopeCodeSet(parentScope);
  const target = scopeCodeSet(targetScope);
  return [...target].filter((code) => parent.has(code)).sort();
}

/** D5 · 判权：工具名在 scope 内 ⇒ true。空 scope 不放行任何工具。 */
export function isToolAllowedInScope(
  scope: readonly string[] | ReadonlySet<string>,
  toolName: string
): boolean {
  return scopeCodeSet(scope).has(toolName);
}

// ---------------------------------------------------------------------------
// D3 · 取消向下传播（机制面出口；行为判据走 HTTP）
// ---------------------------------------------------------------------------

/** 进程内辅助索引：`parentRunId → 本进程经 {@link delegateSpawn} 创建的子 run`。 */
const DELEGATED_CHILDREN = new Map<string, Set<string>>();

/**
 * D3 · 机制面出口：把父 run 的取消传播到子集合。
 *
 * - `childRunIds` 缺省 ⇒ 双源发现（tool_call 行查 + agent_event 交叉验证，裁定 5）；
 *   进程内索引只作**加速缓存**（丢失时双源查询独立成立 —— 非正确性依赖）；
 * - 每个子 run：CAS 收敛 `CANCELLED`（`stop_reason="cancelled"`，词表内）；
 * - `cancelled` = 本次收敛成功或先前已终态；`pending` = 超时仍未终态（正常路径
 *   CAS 即时收敛，pending 仅在 db 不可用时出现）；
 * - `timeoutS` 缺省 30（对齐 py `DEFAULT_RECLAIM_TIMEOUT_S`）。
 */
export async function propagateCancel(input: {
  readonly parentRunId: string;
  readonly childRunIds?: readonly string[];
  readonly timeoutS?: number;
  readonly db?: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId?: string;
}): Promise<{ readonly cancelled: string[]; readonly pending: string[] }> {
  const timeoutS = input.timeoutS ?? 30;
  const deadline = Date.now() + timeoutS * 1000;

  let childRunIds = input.childRunIds === undefined ? undefined : [...input.childRunIds];
  if (childRunIds === undefined && input.db !== undefined && input.tenantId !== undefined) {
    childRunIds = await discoverChildRunIds(input.db, input.dialect ?? "pg", input.tenantId, input.parentRunId);
  }
  const fromRegistry = DELEGATED_CHILDREN.get(input.parentRunId);
  if (fromRegistry !== undefined) {
    const merged = new Set([...(childRunIds ?? []), ...fromRegistry]);
    childRunIds = [...merged];
  }
  if (childRunIds === undefined || childRunIds.length === 0) {
    return { cancelled: [], pending: [] };
  }

  const cancelled: string[] = [];
  const pending: string[] = [];
  for (const childRunId of childRunIds) {
    if (input.db === undefined || input.tenantId === undefined) {
      pending.push(childRunId);
      continue;
    }
    const outcome = await finalizeChildCancelled(
      input.db,
      input.dialect ?? "pg",
      input.tenantId,
      childRunId,
      new Date()
    );
    if (outcome === "applied" || outcome === "already-terminal") {
      cancelled.push(childRunId);
      continue;
    }
    pending.push(childRunId);
  }

  // 正常路径上 CAS 即时收敛；此循环只为“收敛依赖外部释放”的形态兜底到 deadline。
  if (pending.length > 0 && input.db !== undefined && input.tenantId !== undefined) {
    while (Date.now() < deadline && pending.length > 0) {
      await new Promise((resolve) => {
        setTimeout(resolve, 100);
      });
      const stillPending: string[] = [];
      for (const childRunId of pending) {
        const outcome = await finalizeChildCancelled(
          input.db,
          input.dialect ?? "pg",
          input.tenantId,
          childRunId,
          new Date()
        );
        if (outcome === "applied" || outcome === "already-terminal") cancelled.push(childRunId);
        else stillPending.push(childRunId);
      }
      pending.splice(0, pending.length, ...stillPending);
    }
  }
  return { cancelled, pending };
}

// ---------------------------------------------------------------------------
// 派生单入口（S3 闸 → 深度闸 → 并发闸 → 建 run → 双源写行）
// ---------------------------------------------------------------------------

/** {@link delegateSpawn} 的入参（判据《调用契约》① 逐字；可缺省字段按契约标注）。 */
export interface DelegateSpawnInput {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  readonly parentRunId: string;
  readonly targetAgentId: string;
  readonly targetVersionId: string;
  readonly conversationId: string;
  readonly task: string;
  readonly depth?: number;
  readonly maxDepth?: number;
  /** 父下拨给子 run 的预算 B（已按 {@link resolveChildBudget} 口径解析的子预算）。 */
  readonly budget?: ChildBudget;
  /** 父 run 的 policy_version 快照（S3：子 run 必须继承；缺省回落当前策略版本）。 */
  readonly parentPolicyVersion?: string;
  /** 沙箱端口（子 run 执行 `code_exec` 用；生产装配注入，缺省 ⇒ 子 run 不预占沙箱）。 */
  readonly sandbox?: unknown;
}

/** 派生结果（判据归一器认 `accepted` 布尔形态）。 */
export type DelegateSpawnOutcome =
  | { readonly accepted: true; readonly childRunId: string; readonly policyVersion: string }
  | { readonly accepted: false; readonly reason: string; readonly stage?: string };

/** 拒绝事件的挂点标记（S3：`SafetyStage = "delegation"`）。 */
const DELEGATION_STAGE = "delegation";

/**
 * 派生单入口：**只经应用层建子 run**（`origin = SUBAGENT`，D8/D10），拒绝一律走
 * **拒绝型 result**（返回值形态，不抛异常、不产生 4xx —— S3-2）。
 *
 * 次序（每一步拒绝都落 D1 式观察面：父 run 的 tool_call FAILED + `subagent.rejected`，
 * 且 **子 run 行数 == 0**）：
 *   1. **S3 闸**（`SafetyStage = delegation`，子任务文本过闸；`REDACT` 就地取脱敏文本，
 *      `ALLOW` 放行，`DENY` 拒绝）；
 *   2. **深度闸**（`max_subagent_depth` 缺省 1，超限必拒 —— D1）；
 *   3. **并发闸 + 建 run + 双源写行**（复用 `SubAgentSpawner.delegate`，`origin=SUBAGENT`
 *      豁免并发计数；父 run 的 `spawn_agent` tool_call 记 SUCCESS(child_run_id)）。
 */
export async function delegateSpawn(input: DelegateSpawnInput): Promise<DelegateSpawnOutcome> {
  const dialect = input.dialect ?? "pg";
  const spawner = new SubAgentSpawner({
    db: input.db,
    dialect,
    tenantId: input.tenantId,
    maxDepth: input.maxDepth ?? MAX_SUBAGENT_DEPTH,
  });
  const depth = input.depth ?? 0;
  const maxDepth = input.maxDepth ?? MAX_SUBAGENT_DEPTH;

  // ---- 1. S3 闸（delegation stage；拒绝即返回，不落任何子 run 行）-------------
  const gate = new SafetyGate({ db: input.db, dialect, tenantId: input.tenantId });
  const verdict = await evaluateDelegation(gate, {
    content: input.task,
    requestId: randomUUID(),
    runId: input.parentRunId,
    conversationId: input.conversationId,
  });
  if (verdict.decision === "DENY") {
    const rejectReason: SpawnRejectReason = "SAFETY_DENIED";
    const detail = safetyDenyDetail(verdict);
    await spawner.rejectDelegation(
      {
        parentRunId: input.parentRunId,
        targetAgentId: input.targetAgentId,
        task: input.task,
        depth,
        maxDepth,
      },
      { stage: DELEGATION_STAGE, reason: rejectReason }
    );
    return {
      accepted: false,
      reason: `SAFETY_DENIED:${detail}`,
      stage: DELEGATION_STAGE,
    };
  }
  const effectiveTask = verdict.decision === "REDACT" ? (verdict.redactedContent ?? input.task) : input.task;

  // ---- 2. 深度闸（D1；拒绝事件同样带 delegation 挂点标记 —— S3-3）--------------
  const depthCheck = isDepthAllowed({ depth, maxDepth });
  if (!depthCheck.allowed) {
    await spawner.rejectDelegation(
      {
        parentRunId: input.parentRunId,
        targetAgentId: input.targetAgentId,
        task: effectiveTask,
        depth,
        maxDepth,
      },
      { stage: DELEGATION_STAGE, reason: DEPTH_EXCEEDED_REASON }
    );
    return { accepted: false, reason: DEPTH_EXCEEDED_REASON, stage: DELEGATION_STAGE };
  }

  // ---- 3. 并发闸 + 建 run + 双源写行（origin = SUBAGENT 豁免并发计数）-----------
  const outcome = await spawner.delegate({
    parentRunId: input.parentRunId,
    targetAgentId: input.targetAgentId,
    targetVersionId: input.targetVersionId,
    conversationId: input.conversationId,
    task: effectiveTask,
    depth,
    maxDepth,
    budget: toBudgetRecord(input.budget),
    policyVersion: input.parentPolicyVersion,
    rejectionStage: DELEGATION_STAGE,
  });
  if (!outcome.accepted) {
    return {
      accepted: false,
      reason: outcome.reason,
      ...(outcome.stage === undefined ? {} : { stage: outcome.stage }),
    };
  }
  registerDelegatedChild(input.parentRunId, outcome.childRunId);
  return {
    accepted: true,
    childRunId: outcome.childRunId,
    policyVersion: outcome.policyVersion,
  };
}

/** 进程内辅助索引登记（裁定 5：加速缓存，非正确性依赖 —— 双源查询独立成立）。 */
function registerDelegatedChild(parentRunId: string, childRunId: string): void {
  let children = DELEGATED_CHILDREN.get(parentRunId);
  if (children === undefined) {
    children = new Set();
    DELEGATED_CHILDREN.set(parentRunId, children);
  }
  children.add(childRunId);
}

/** 供测试/运维清理进程内辅助索引（不承载正确性）。 */
export function forgetDelegatedChildren(parentRunId: string): void {
  DELEGATED_CHILDREN.delete(parentRunId);
}
