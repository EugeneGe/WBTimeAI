/**
 * T3-03 · `agent_run` 仓储（一次 Agent 执行的**主链行**）。
 *
 * 这张表**有 `tenant_id`** ⇒ 直接 `extends ScopedRepo`（不进 `ChildScopedRepo`）。
 * 它是 `agent_event` / `tool_call` 两张子表的**父**，所以本文件也是那两个子仓储
 * 校验「父是否在本 scope 下可见」时要用的查询源（见各自构造函数的 `parentExists`）。
 *
 * 本文件交的是 **lease / CAS 的数据面原语**（R3-05 ③）：
 * 竞态仲裁（谁拿到 lease、何时放弃）归 T3-08 的 RunCoordinator，这里只保证
 * 「CAS 是真的 CAS」—— `UPDATE ... WHERE id=? AND tenant_id=? AND status IN (...)`，
 * 影响行数 0 ⇒ 返回 `null`（调用方据此放弃），**不用**「先查后写」（那有 TOCTOU 窗口）。
 *
 * v0019：`stop_reason` 列双档同型可写（`packages/db/src/schema/{pg,sqlite}/agent.ts`），
 * 落点就是 {@link AgentRunRepo.finalize}。
 */

import { and, eq, inArray, type InferSelectModel } from "drizzle-orm";

import { agent_run as pgAgentRun } from "../schema/pg/index.js";
import { agent_run as sqliteAgentRun } from "../schema/sqlite/index.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `agent_run` 行。 */
export type AgentRunRow = InferSelectModel<typeof pgAgentRun>;

/**
 * Run 状态（v0019 契约 **7 值**）。
 *
 * 与 `packages/domain/src/runtime/run-status.ts::RUN_STATUSES` **逐字同源**；
 * 此处复述而非 import —— `packages/db` 不依赖 `@wbtime/domain`（本版零新增依赖），
 * 且两份常量由各自单测锁定，漂移会在两边同时红。
 */
export const AGENT_RUN_STATUSES = [
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "WAITING_INPUT",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;

/** 终态（终态后零事件 —— Harness §1-5）。 */
export const TERMINAL_AGENT_RUN_STATUSES = ["SUCCEEDED", "FAILED", "CANCELLED"] as const;

export function isTerminalAgentRunStatus(status: string): boolean {
  return (TERMINAL_AGENT_RUN_STATUSES as readonly string[]).includes(status);
}

/** CAS 抢 lease 的入参。 */
export interface AcquireLeaseOptions {
  /** 允许迁移的**源状态**集合（例：`["QUEUED"]`）。空数组 ⇒ 恒失败（拒绝无源迁移）。 */
  readonly from: readonly string[];
  /** 目标状态。 */
  readonly to: string;
  /** 同时刷新 `last_heartbeat_at` 的时刻；不给则不刷新。 */
  readonly at?: Date | string;
}

/** 终态落库入参（`stop_reason` 是 v0019 的关键列）。 */
export interface FinalizeRunPatch {
  readonly status: string;
  /** 停止原因（终态应有值；矩阵校验在 `packages/domain`，本层只负责写）。 */
  readonly stopReason?: string | null;
  readonly success?: boolean | null;
  readonly error?: string | null;
  readonly errorType?: string | null;
  readonly completedAt?: Date | string;
  readonly durationMs?: number | null;
}

export class AgentRunRepo extends ScopedRepo<AgentRunRow> {
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgAgentRun, sqliteAgentRun), scope);
    this.#dialect = dialect;
  }

  /** 本租户的 run 列表。 */
  list(options: ListOptions = {}): Promise<AgentRunRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /**
   * 按幂等键取 run（`(tenant_id, idempotency_key)` 有唯一索引 —— **零 DDL 复用既有约束**）。
   *
   * 用途：`POST /agents/{id}/run` 重放时认出"这个请求已经起过一次"，避免重复扣预算。
   */
  findByIdempotencyKey(key: string): Promise<AgentRunRow | null> {
    return this.findOneWhere(eq(this.columns.idempotency_key, key));
  }

  /** 按 agent 列举（运维面 / 审计用）。 */
  listByAgent(agentId: string, options: ListOptions = {}): Promise<AgentRunRow[]> {
    return this.findManyWhere(eq(this.columns.agent_id, agentId), options);
  }

  /**
   * **CAS 抢 lease**：`status ∈ from` ⇒ `to`。
   *
   * @returns 抢到 ⇒ 更新后的行；**没抢到 ⇒ `null`**（状态已不是 `from` 里的任何一个
   *          —— 通常是别的 worker 先抢到了）。调用方据此退出，不得重试覆盖。
   */
  async tryAcquireLease(
    runRef: ScopedRef,
    options: AcquireLeaseOptions,
  ): Promise<AgentRunRow | null> {
    this.assertOwnRef(runRef, "runRef");
    if (options.from.length === 0) {
      throw new Error("tryAcquireLease 必须给出至少一个源状态（空 from 等于永不抢到，多半是漏填）");
    }
    const patch: Record<string, unknown> = { status: options.to };
    if (options.at !== undefined) {
      patch.last_heartbeat_at = this.#instant(options.at);
    }
    const rows = await this.updateManyWhere(
      and(eq(this.columns.id, runRef.id), inArray(this.columns.status, [...options.from])),
      patch as never,
    );
    return rows[0] ?? null;
  }

  /** 心跳：只刷新 `last_heartbeat_at`（T3-08 用它判"worker 还活着"）。 */
  async heartbeat(runRef: ScopedRef, at: Date | string): Promise<AgentRunRow | null> {
    this.assertOwnRef(runRef, "runRef");
    return this.update(runRef, { last_heartbeat_at: this.#instant(at) } as never);
  }

  /**
   * 终态落库（含 **v0019 的 `stop_reason`**）。
   *
   * 不做状态矩阵校验（那是 `packages/domain` 的 `run-stop-reason.ts`）；本层只保证
   * 「写得到、写得进、双档同型」。
   */
  async finalize(runRef: ScopedRef, patch: FinalizeRunPatch): Promise<AgentRunRow | null> {
    this.assertOwnRef(runRef, "runRef");
    const values: Record<string, unknown> = { status: patch.status };
    if (patch.stopReason !== undefined) values.stop_reason = patch.stopReason;
    if (patch.success !== undefined) values.success = patch.success;
    if (patch.error !== undefined) values.error = patch.error;
    if (patch.errorType !== undefined) values.error_type = patch.errorType;
    if (patch.durationMs !== undefined) values.duration_ms = patch.durationMs;
    if (patch.completedAt !== undefined) values.completed_at = this.#instant(patch.completedAt);
    return this.update(runRef, values as never);
  }

  create(row: TenantScopedInsert<AgentRunRow>): Promise<AgentRunRow> {
    return this.insertRow(row);
  }

  /**
   * 时间列写值：PG 档要 `Date`，SQLite 档要规整文本（`instantLiteral` 的既有口径）。
   *
   * 行类型按 PG 档声明（dialect.ts D-6），故此处返回值的**静态**类型是 `Date`；
   * SQLite 档运行时拿到的是文本 —— 与 `session-repo` 等既有仓储同一取舍。
   */
  #instant(at: Date | string): Date {
    return instantLiteral(this.#dialect, at) as Date;
  }
}
