/**
 * T3-03 · `agent_event` 仓储（运行时事件流 / 回放的数据源）。
 *
 * 表**没有 `tenant_id`**（父 = `agent_run`）⇒ `extends ChildScopedRepo`（R3-22）。
 *
 * `seq` 的两条硬口径（**R3-05**）：
 *   1. `seq` **没有唯一约束**（冻结面不可加索引，176 不变）⇒ 唯一性由**应用层**兜：
 *      {@link AgentEventRepo.appendAt} 在写之前查一次 `(run_id, seq)`，已存在 ⇒ 抛
 *      {@link ChildConflictError}（fail loud，**不**静默覆盖 —— 覆盖会让回放凭空少一帧）；
 *   2. 分配 = `max(seq) + 1`（单 run 单写者，配合 `agent_run` 的 CAS lease）。
 *
 * 写入**返回分配到的 `seq`**（任务卡验收 ③）—— 调用方（T3-08 的 RunEventWriter）
 * 要把它放进 SSE 的 `id:` 字段，所以"写了但不知道几号"等于没写。
 */

import { randomUUID } from "node:crypto";

import { eq, gt, type InferSelectModel } from "drizzle-orm";

import { agent_event as pgAgentEvent } from "../schema/pg/index.js";
import { agent_event as sqliteAgentEvent } from "../schema/sqlite/index.js";
import { AgentRunRepo } from "./agent-run-repo.js";
import {
  ChildConflictError,
  ChildScopedRepo,
  type ChildListOptions,
  type ChildRepoOptions,
  type ChildScopedInsert,
} from "./child-scoped-repo.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import type { DrizzleDatabase, ListOptions, Scope, ScopedRef } from "./scoped-repo.js";

/** `agent_event` 行。 */
export type AgentEventRow = InferSelectModel<typeof pgAgentEvent>;

/** 追加事件的入参（`seq` 由仓储分配，调用方传不进来）。 */
export interface AppendEventInput {
  readonly type: string;
  readonly payload?: unknown;
  readonly traceId?: string | null;
  readonly spanId?: string | null;
}

/** 追加结果：行 + **分配到的 seq**（SSE `id:` 要用）。 */
export interface AppendedEvent {
  readonly row: AgentEventRow;
  readonly seq: number;
}

export class AgentEventRepo extends ChildScopedRepo<AgentEventRow, "run_id"> {
  constructor(db: DrizzleDatabase, scope: Scope, runRef: ScopedRef, dialect: SqlDialect = "pg") {
    const runs = new AgentRunRepo(db, scope, dialect);
    const options: ChildRepoOptions = {
      parentColumn: "run_id",
      parentLabel: "run",
      parentExists: (ref) =>
        runs.findById(ref).then((row) => row !== null),
    };
    super(db, resolveTable(dialect, pgAgentEvent, sqliteAgentEvent), scope, runRef, options);
  }

  /** 本 run 的事件（**按 seq 升序** —— 回放次序即写入次序）。 */
  list(options: ChildListOptions = {}): Promise<AgentEventRow[]> {
    return this.findManyWhere(undefined, { orderBy: "seq", descending: false, ...options });
  }

  /** 当前最大 seq（无事件 ⇒ 0）。 */
  async maxSeq(): Promise<number> {
    const rows = await this.findManyWhere(undefined, {
      orderBy: "seq",
      descending: true,
      limit: 1,
    });
    const last = rows[0];
    return last === undefined ? 0 : last.seq;
  }

  /** 按 seq 精确取（重复检测 / 回放定位用）。 */
  findBySeq(seq: number): Promise<AgentEventRow | null> {
    return this.findOneWhere(eq(this.columns.seq, seq));
  }

  /**
   * 追加事件：`seq = max(seq) + 1`，返回分配到的号。
   *
   * @throws {ChildConflictError} 计算出的 seq 已被占用（R3-05 的应用层护栏）。
   */
  async append(input: AppendEventInput): Promise<AppendedEvent> {
    const seq = (await this.maxSeq()) + 1;
    return this.appendAt(seq, input);
  }

  /**
   * 按**指定** seq 追加（回放 / 续传 / 测试注入用）。
   *
   * @throws {ChildConflictError} `(run_id, seq)` 已存在 —— **零 DDL** 前提下这是
   *         唯一能挡住重复的手段；静默覆盖会让「事件丢帧」变成不可见故障。
   */
  async appendAt(seq: number, input: AppendEventInput): Promise<AppendedEvent> {
    if (!Number.isInteger(seq) || seq < 1) {
      throw new ChildConflictError(`agent_event.seq 必须是 ≥1 的整数：${String(seq)}`);
    }
    const existing = await this.findBySeq(seq);
    if (existing !== null) {
      throw new ChildConflictError(
        `agent_event 重复：(run_id=${this.parentRef.id}, seq=${seq}) 已存在（R3-05：无唯一索引 ⇒ 应用层抛错，不覆盖）`
      );
    }
    // `id` 无默认值（双档 DDL 均无 default）⇒ 由仓储生成：把"每个事件都有 id"变成
    // 结构性保证，而不是靠每个调用方记得传。
    const row = await this.insertRow({
      id: randomUUID(),
      type: input.type,
      payload: input.payload ?? null,
      trace_id: input.traceId ?? null,
      span_id: input.spanId ?? null,
      seq,
    } as unknown as ChildScopedInsert<AgentEventRow, "run_id">);
    return { row, seq: row.seq };
  }

  /**
   * 查询级不变量：`(run_id, seq)` 不得重复（R3-05 的影响判据 ④）。
   *
   * 注意：这里的 `run_id` 谓词恒为本父 —— 所以它证明的是**本 run 内**无重复；
   * 「跨 run seq 复用」是**允许**的（seq 是 run 内序号）。
   */
  async findDuplicateSeq(): Promise<AgentEventRow[]> {
    const rows = await this.list({ limit: 500 });
    const seen = new Set<number>();
    const duplicates: AgentEventRow[] = [];
    for (const row of rows) {
      if (seen.has(row.seq)) duplicates.push(row);
      else seen.add(row.seq);
    }
    return duplicates;
  }

  /**
   * 区间读取（T3-08 做 gap-aware 续读的原语；**不含** gap 语义本身 ——
   * "遇到洞就停"是续读策略，不是仓储的事）。
   */
  listAfter(afterSeq: number, options: ChildListOptions = {}): Promise<AgentEventRow[]> {
    return this.findManyWhere(gt(this.columns.seq, afterSeq), {
      orderBy: "seq",
      descending: false,
      ...options,
    });
  }
}
