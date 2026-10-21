/**
 * T2-03 · `login_attempt` —— 登录尝试流水（白名单通道 #3 · **限速唯一数据源**）。
 *
 * 为什么可以没有 scope：登录**前**租户/用户可能都未知（用户名不存在、租户 slug 打错、
 * 甚至在多租户部署里还没确定是哪个租户），此时仍必须落库 —— 否则「连续失败 5 次
 * 锁定」永远数不到那几次失败（计划 §2 白名单 #3 理由）。
 *
 * 关键列语义（计划 §2 / §3.4）：`tenant_id` / `username` **均可空**；`success` 打断
 * 连续计数；表里**不含口令、不含口令哈希**。锁定判定 = 同一 `username` 的连续失败
 * ≥ 5 且最近一次失败落在 900s 窗口内，只读最近 `max(4×5,20)=20` 条。
 *
 * ⚠️ 列清单实测差异（与任务卡原文不同，见 T2-03 施工记录 D-5）
 * -----------------------------------------------------------
 * `login_attempt` 的列只有 `id` / `tenant_id` / `username` / `ip_address` / `success` /
 * `created_at` / `updated_at` —— **没有 `user_agent`**。任务卡写的
 * `record({…, user_agent})` 无法落地：加这一列 = 改 DDL = 破「零 DDL」红线。
 * 故本方法的入参只有 `ipAddress`；`user_agent` 归 `session` 表（它有这一列）。
 */

import { randomUUID } from "node:crypto";

import { and, eq, type InferSelectModel } from "drizzle-orm";

import { login_attempt as pgLoginAttempt } from "../schema/pg/index.js";
import { login_attempt as sqliteLoginAttempt } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import type { DrizzleDatabase } from "./scoped-repo.js";
import { UNSCOPED_WHITELIST, UnscopedTableRepo } from "./unscoped-repo.js";

/** `login_attempt` 行。 */
export type LoginAttemptRow = InferSelectModel<typeof pgLoginAttempt>;

/**
 * 一条尝试记录。除了必须的 `success`，其余都可空 —— 「租户未知 / 用户不存在」时
 * 也要能落一条失败记录。
 */
export interface LoginAttemptRecord {
  /** 已解析到的租户；登录前未知则给 `null` / 省略。 */
  readonly tenantId?: string | null;
  /** 用户名字面量（**不**校验它是否存在 —— 存在性校验会反过来变成探测面）。 */
  readonly username?: string | null;
  /** 客户端 IP（`varchar(64)`）。 */
  readonly ipAddress?: string | null;
  /** 本次尝试是否成功。成功记录用于**打断**连续失败计数。 */
  readonly success: boolean;
}

/** §3.4：判定只读最近 `max(4×5, 20) = 20` 条。 */
export const LOGIN_ATTEMPT_WINDOW_SIZE = 20;

/** §3.4：`max_attempts=5`（连续失败阈值）。 */
export const LOGIN_MAX_CONSECUTIVE_FAILURES = 5;

/** §3.4：`lock_seconds=900`（锁定时长 / 失败窗口）。 */
export const LOGIN_LOCK_SECONDS = 900;

export class LoginAttemptSink extends UnscopedTableRepo<LoginAttemptRow> {
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, dialect: SqlDialect = "pg") {
    super(
      db,
      resolveTable(dialect, pgLoginAttempt, sqliteLoginAttempt),
      UNSCOPED_WHITELIST.login_attempt
    );
    this.#dialect = dialect;
  }

  /**
   * 落一条尝试。
   *
   * `id` 由本方法生成（DDL 里 `id` 无默认值，调用方也不该关心它）；`created_at`
   * **显式写入**而不是靠 `DEFAULT CURRENT_TIMESTAMP`：SQLite 档该默认值只有**秒**
   * 精度，同一秒内 5 次失败会拿到 5 个相同时间戳，`ORDER BY created_at DESC` 的
   * 顺序就不再确定，而"连续失败计数"正是靠顺序数出来的。这里给到毫秒精度，
   * 让顺序可判定（PG 档仍是 `now()` 的微秒精度）。
   */
  record(entry: LoginAttemptRecord): Promise<LoginAttemptRow> {
    if (typeof entry.success !== "boolean") {
      throw new TypeError("LoginAttemptRecord.success 必须是布尔值 —— 它决定计数是否被打断");
    }
    const now = nextIssuedInstant();
    const stamp: Date | string =
      this.#dialect === "sqlite" ? toSortableTimestamp(now) : now;
    return this.insertRow({
      id: randomUUID(),
      tenant_id: entry.tenantId ?? null,
      username: entry.username ?? null,
      ip_address: entry.ipAddress ?? null,
      success: entry.success,
      created_at: stamp,
      updated_at: stamp,
    });
  }

  /**
   * 某用户名的最近尝试（**新的在前**），最多 `limit` 条。
   *
   * 这是限速判定的原始数据；语义判定交给 {@link countConsecutiveFailures}（纯函数）。
   */
  recentAttempts(username: string, limit: number = LOGIN_ATTEMPT_WINDOW_SIZE): Promise<LoginAttemptRow[]> {
    if (typeof username !== "string" || username === "") {
      throw new TypeError("recentAttempts 需要非空 username —— 空串会把所有匿名尝试混成一条序列");
    }
    return this.findManyWhere(eq(this.columns.username, username), {
      limit,
      orderBy: "created_at",
      descending: true,
    });
  }

  /** 某用户名的最近**失败**尝试（新的在前）。 */
  recentFailures(username: string, limit: number = LOGIN_ATTEMPT_WINDOW_SIZE): Promise<LoginAttemptRow[]> {
    if (typeof username !== "string" || username === "") {
      throw new TypeError("recentFailures 需要非空 username");
    }
    return this.findManyWhere(
      and(eq(this.columns.username, username), eq(this.columns.success, false)),
      { limit, orderBy: "created_at", descending: true }
    );
  }

  /** 某用户名今天的成功尝试数（运维诊断用；不含任何凭据信息）。 */
  countSuccesses(username: string, limit: number = LOGIN_ATTEMPT_WINDOW_SIZE): Promise<number> {
    return this.findManyWhere(
      and(eq(this.columns.username, username), eq(this.columns.success, true)),
      { limit, orderBy: "created_at", descending: true }
    ).then((rows) => rows.length);
  }
}

/**
 * 纯函数：从「新的在前」的尝试序列里数**连续失败**条数（成功一次即打断）。
 *
 * 为什么独立成纯函数：判定逻辑与 SQL 解耦后可以拿 5 条手写序列直接证明
 * 「成功打断计数」「窗口内 5 次」「窗口外不算」三种情形，不需要造时钟。
 */
export function countConsecutiveFailures(rows: readonly LoginAttemptRow[]): number {
  let count = 0;
  for (const row of rows) {
    if (row.success !== true) count += 1;
    else break;
  }
  return count;
}

/**
 * 本进程内**严格递增**的授时点（毫秒）。
 *
 * 为什么不能直接 `new Date()`：同一毫秒内连打两次 `record()` 会拿到相同时间戳，
 * 而「连续失败计数」完全依赖 `ORDER BY created_at DESC` 的**确定性**顺序 ——
 * 时间戳相等时 SQL 不保证顺序，5 次快速失败就可能被数成 3 次（限速被绕过）。
 * 这里保证进程内严格递增；跨进程（多 API worker）仍可能同毫秒，那属于已知边界
 * （登记在 T2-03 施工记录的遗留项）。
 */
let lastIssuedMs = 0;

function nextIssuedInstant(): Date {
  const now = Date.now();
  const issued = now > lastIssuedMs ? now : lastIssuedMs + 1;
  lastIssuedMs = issued;
  return new Date(issued);
}

/**
 * 毫秒精度、可按字典序比较的时间文本（SQLite 档 `created_at` / `updated_at` 用）。
 *
 * 形状 `YYYY-MM-DD HH:MM:SS.sss`（UTC）—— 与 `DEFAULT CURRENT_TIMESTAMP` 的
 * `YYYY-MM-DD HH:MM:SS` **前缀一致**，因此同一列里混写两种形状时，秒级行的排序
 * 仍然正确（短串在同秒内排在长串之前）。
 */
function toSortableTimestamp(at: Date): string {
  return `${at.toISOString().slice(0, 19).replace("T", " ")}.${String(at.getUTCMilliseconds()).padStart(3, "0")}`;
}
