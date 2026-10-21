/**
 * T2-03 · `user` 仓储（账号主体，唯一持有口令哈希）。
 *
 * 关键列语义（计划 §2）：`password_hash` = argon2id PHC 串；`(tenant_id,username)` 与
 * `(tenant_id,email)` 唯一；`is_active` / `is_superuser`。
 *
 * 红线：本文件**不**读、不比对、不回显口令明文；只搬运 `password_hash`。
 * 校验一律在 Service 层用 `@node-rs/argon2` 的 `verify()` 完成（§3.1）。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { user as pgUser } from "../schema/pg/index.js";
import { user as sqliteUser } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `user` 行。 */
export type UserRow = InferSelectModel<typeof pgUser>;

export class UserRepo extends ScopedRepo<UserRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgUser, sqliteUser), scope);
  }

  /**
   * 按用户名取用户 —— **scope 内**。
   *
   * 唯一约束是 `(tenant_id, username)`，所以"同名不同租户"是合法数据；
   * 若这里不加租户条件，登录就会跨租户命中别人的账号。故必须经 `findOneWhere`
   * （它恒 and `tenant_id`），不得写裸 `WHERE username = ?`。
   */
  findByUsername(username: string): Promise<UserRow | null> {
    return this.findOneWhere(eq(this.columns.username, username));
  }

  /** 按邮箱取用户 —— 同样只在 scope 内（唯一约束 `(tenant_id, email)`）。 */
  findByEmail(email: string): Promise<UserRow | null> {
    return this.findOneWhere(eq(this.columns.email, email));
  }

  /** 列出启用账号（运维/管理面用）。 */
  listActive(options: ListOptions = {}): Promise<UserRow[]> {
    return this.findManyWhere(eq(this.columns.is_active, true), options);
  }

  /** 建档。`tenant_id` 由 scope 注入，调用方传不进来（类型层 `never`）。 */
  create(row: TenantScopedInsert<UserRow>): Promise<UserRow> {
    return this.insertRow(row);
  }

  /** 更新口令哈希（已是 PHC 串；本方法**不**做哈希，也不看明文）。 */
  updatePasswordHash(ref: ScopedRef, passwordHash: string): Promise<UserRow | null> {
    this.assertOwnRef(ref, "userRef");
    return this.update(ref, { password_hash: passwordHash });
  }

  /** 启停账号。停用后登录与令牌刷新都必须拒绝（判定在 Service 层）。 */
  setActive(ref: ScopedRef, isActive: boolean): Promise<UserRow | null> {
    this.assertOwnRef(ref, "userRef");
    return this.update(ref, { is_active: isActive });
  }
}
