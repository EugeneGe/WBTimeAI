/**
 * T2-03 · `session` 仓储（一次登录 = 一条会话，设备维度）。
 *
 * 关键列语义（计划 §2 / §7）：`expires_at` / `revoked_at`；`device` / `ip_address` /
 * `user_agent`。会话**不物理删除** —— `GET /users/me/devices` 要能看到已撤销的行，
 * 因此撤销 = 打 `revoked_at` 时间戳。
 *
 * 撤销的幂等性（计划 §3.3）：`WHERE revoked_at IS NULL`，重复撤销只覆盖一次、
 * **不抛错**。所以 {@link SessionRepo.revoke} 走条件更新而不是 `update()`（后者会把
 * 已撤销行的 `revoked_at` 一路改写，审计时间线就废了）。
 */

import { and, eq, gt, isNull, type InferSelectModel } from "drizzle-orm";

import { session as pgSession } from "../schema/pg/index.js";
import { session as sqliteSession } from "../schema/sqlite/index.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `session` 行。 */
export type SessionRow = InferSelectModel<typeof pgSession>;

export class SessionRepo extends ScopedRepo<SessionRow> {
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgSession, sqliteSession), scope);
    this.#dialect = dialect;
  }

  /** 建档（登录 / 注册 / refresh 轮换各一条）。`tenant_id` 由 scope 注入。 */
  create(row: TenantScopedInsert<SessionRow>): Promise<SessionRow> {
    return this.insertRow(row);
  }

  /** 某用户的全部会话（含已撤销 —— `devices` 列表口径）。 */
  listByUser(userRef: ScopedRef, options: ListOptions = {}): Promise<SessionRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(eq(this.columns.user_id, userRef.id), options);
  }

  /**
   * 某用户**仍然有效**的会话：`revoked_at IS NULL` 且 `expires_at > at`。
   *
   * `at` 默认 `new Date()`；测试里传固定时刻可去掉时间抖动。
   */
  listActiveByUser(
    userRef: ScopedRef,
    at: Date | string = new Date(),
    options: ListOptions = {}
  ): Promise<SessionRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(
      and(
        eq(this.columns.user_id, userRef.id),
        isNull(this.columns.revoked_at),
        gt(this.columns.expires_at, instantLiteral(this.#dialect, at) as Date)
      ),
      options
    );
  }

  /** 某会话此刻是否有效（`revoked_at IS NULL` 且未过期）。 */
  async isActive(ref: ScopedRef, at: Date | string = new Date()): Promise<boolean> {
    this.assertOwnRef(ref, "sessionRef");
    const row = await this.findOneWhere(
      and(
        eq(this.columns.id, ref.id),
        isNull(this.columns.revoked_at),
        gt(this.columns.expires_at, instantLiteral(this.#dialect, at) as Date)
      )
    );
    return row !== null;
  }

  /**
   * 撤销单个会话（幂等）：只有 `revoked_at IS NULL` 的行会被改写。
   *
   * @returns 是否真的改写了行；已撤销/不存在都返回 `false`（**不抛错** —— 登出必须幂等）。
   */
  async revoke(ref: ScopedRef, at: Date | string = new Date()): Promise<boolean> {
    this.assertOwnRef(ref, "sessionRef");
    const rows = await this.updateManyWhere(
      and(eq(this.columns.id, ref.id), isNull(this.columns.revoked_at)),
      { revoked_at: instantLiteral(this.#dialect, at) as Date }
    );
    return rows.length > 0;
  }

  /**
   * 撤销某用户全部有效会话（`POST /users/me/logout-all`）。
   *
   * @returns 实际被改写（由有效变已撤销）的会话数 —— 注意**契约不返回这个数**
   *   （`MessageResponse` 只有 `{message}`），它仅供内部日志/测试断言。
   */
  async revokeAllByUser(userRef: ScopedRef, at: Date | string = new Date()): Promise<number> {
    this.assertOwnRef(userRef, "userRef");
    const rows = await this.updateManyWhere(
      and(eq(this.columns.user_id, userRef.id), isNull(this.columns.revoked_at)),
      { revoked_at: instantLiteral(this.#dialect, at) as Date }
    );
    return rows.length;
  }
}
