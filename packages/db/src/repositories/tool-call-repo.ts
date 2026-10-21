/**
 * T3-03 · `tool_call` 仓储（一次工具调用的**四段事务边界**落点）。
 *
 * 表**没有 `tenant_id`**（父 = `agent_run`）⇒ `extends ChildScopedRepo`（R3-22）。
 *
 * 四段边界（`00-安全拦截链` / Harness §1-6）：
 *   ① intent  —— `createPending()`：`PENDING` + `attempt=1`
 *   ② authorize——（审批在 T3-12 / SafetyGate；拒绝 ⇒ `markTerminal(status="DENIED")`，
 *                 这是**唯一**允许从 `PENDING` 直达终态的路径）
 *   ③ execute —— `markRunning()`：`PENDING → RUNNING`
 *   ④ result  —— `markTerminal()`：写 `output` / `error` / `duration_ms`
 *
 * 幂等口径（任务卡验收 ②）：
 *   * `markRunning()` 对已 `RUNNING` 的行 ⇒ **原样返回**（不报错、不重置）；
 *   * `markTerminal()` 对**已终态**的行 ⇒ **返回现有行，`output` 不被覆盖**
 *     （重复 result 覆盖 = 把"第一次执行的结果"偷换成后到的那个，回放就不可信了）；
 *   * `attempt` 只经 {@link ToolCallRepo.incrementAttempt} **单调递增**。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { tool_call as pgToolCall } from "../schema/pg/index.js";
import { tool_call as sqliteToolCall } from "../schema/sqlite/index.js";
import {
  ChildScopedRepo,
  type ChildRepoOptions,
  type ChildScopedInsert,
  type ChildScopedPatch,
} from "./child-scoped-repo.js";
import { AgentRunRepo } from "./agent-run-repo.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import type { DrizzleDatabase, ListOptions, Scope, ScopedRef } from "./scoped-repo.js";

/** `tool_call` 行。 */
export type ToolCallRow = InferSelectModel<typeof pgToolCall>;

/**
 * 工具调用状态（**7 值**，R3-03：保留 py 的 5 值 + 登记 2 值）。
 *
 * 与 `packages/domain/src/runtime/tool-call-state.ts::TOOL_CALL_STATUSES` **逐字同源**；
 * 此处复述而非 import（同 `agent-run-repo.ts` 的说明：零新增依赖）。
 */
export const TOOL_CALL_STATUSES = [
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "UNKNOWN",
] as const;

/** 终态（恰有一条终态 —— Harness §1-2）。 */
export const TERMINAL_TOOL_CALL_STATUSES = [
  "SUCCESS",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "UNKNOWN",
] as const;

export function isTerminalToolCallStatus(status: string): boolean {
  return (TERMINAL_TOOL_CALL_STATUSES as readonly string[]).includes(status);
}

/** ③ 执行段的入参。 */
export interface MarkRunningOptions {
  /** 是否允许从**终态**回到 RUNNING。默认 `false`（终态不可复活 —— Harness §1-5）。 */
  readonly allowRevive?: boolean;
}

/** ④ 结果段的入参。 */
export interface MarkTerminalOptions {
  readonly status: string;
  readonly output?: unknown;
  readonly error?: string | null;
  readonly durationMs?: number | null;
}

export class ToolCallRepo extends ChildScopedRepo<ToolCallRow, "run_id"> {
  constructor(db: DrizzleDatabase, scope: Scope, runRef: ScopedRef, dialect: SqlDialect = "pg") {
    const runs = new AgentRunRepo(db, scope, dialect);
    const options: ChildRepoOptions = {
      parentColumn: "run_id",
      parentLabel: "run",
      parentExists: (ref) =>
        runs.findById(ref).then((row) => row !== null),
    };
    super(db, resolveTable(dialect, pgToolCall, sqliteToolCall), scope, runRef, options);
  }

  /** 本 run 的工具调用（新的在前）。 */
  list(options: ListOptions = {}): Promise<ToolCallRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /** 按工具名列举（同一 run 内可能多次调同一工具）。 */
  listByToolName(toolName: string, options: ListOptions = {}): Promise<ToolCallRow[]> {
    return this.findManyWhere(eq(this.columns.tool_name, toolName), options);
  }

  /**
   * ① intent：`PENDING` + `attempt=1`（未显式给时）。
   *
   * @throws {ScopeError} 入参自带 `run_id`（父只能由构造时的 ScopedRef 注入）。
   */
  createPending(row: ChildScopedInsert<ToolCallRow, "run_id">): Promise<ToolCallRow> {
    const values: Record<string, unknown> = { ...row };
    values.status = row.status ?? "PENDING";
    values.attempt = row.attempt ?? 1;
    return this.insertRow(values as ChildScopedInsert<ToolCallRow, "run_id">);
  }

  /**
   * ③ execute：`PENDING → RUNNING`。
   *
   * 幂等：已是 `RUNNING` ⇒ 原样返回；已是**终态** ⇒ 默认 `null`（终态不可复活）。
   *
   * @returns 更新后的行；不可见 / 拒绝迁移 ⇒ `null`。
   */
  async markRunning(id: string, options: MarkRunningOptions = {}): Promise<ToolCallRow | null> {
    const current = await this.findById(id);
    if (current === null) return null;
    if (current.status === "RUNNING") return current;
    if (isTerminalToolCallStatus(current.status) && options.allowRevive !== true) {
      return null;
    }
    return this.update(id, { status: "RUNNING" } as ChildScopedPatch<ToolCallRow, "run_id">);
  }

  /**
   * ④ result：写终态。
   *
   * 幂等：**已终态 ⇒ 返回现有行且不覆盖任何字段**（重复 result 不覆盖）。
   * 允许从 `PENDING` 直达 `DENIED`（审批/安全拒绝发生在执行之前，那条路径没有
   * `RUNNING` 段）—— 这是四段边界里唯一合法的"跳段"。
   *
   * @throws {Error} `status` 不是 7 值之一（写脏状态比不写更糟）。
   */
  async markTerminal(id: string, options: MarkTerminalOptions): Promise<ToolCallRow | null> {
    if (!(TOOL_CALL_STATUSES as readonly string[]).includes(options.status)) {
      throw new Error(
        `非法的 tool_call.status：${JSON.stringify(options.status)}（合法值：${TOOL_CALL_STATUSES.join(" | ")}）`
      );
    }
    const current = await this.findById(id);
    if (current === null) return null;
    if (isTerminalToolCallStatus(current.status)) {
      // 幂等：第二次 result 到达时**什么都不改**（回放与去重都依赖这一点）。
      return current;
    }
    const patch: Record<string, unknown> = { status: options.status };
    if (options.output !== undefined) patch.output = options.output;
    if (options.error !== undefined) patch.error = options.error;
    if (options.durationMs !== undefined) patch.duration_ms = options.durationMs;
    return this.update(id, patch as ChildScopedPatch<ToolCallRow, "run_id">);
  }

  /**
   * 重试：`attempt` **单调递增**（不回退、不重置）。
   *
   * 为什么单独一个方法而不是让调用方自己算：`attempt+1` 写在调用方就变成
   * 「读出来 + 写回去」的 TOCTOU（两个 worker 同时重试 ⇒ 都写成 2）。这里由 SQL 侧
   * 用读到的当前值 +1 落库，至少保证**单调**（并发下可能出现跳号，但绝不回退）。
   */
  async incrementAttempt(id: string): Promise<ToolCallRow | null> {
    const current = await this.findById(id);
    if (current === null) return null;
    return this.update(id, { attempt: current.attempt + 1 } as ChildScopedPatch<ToolCallRow, "run_id">);
  }
}
