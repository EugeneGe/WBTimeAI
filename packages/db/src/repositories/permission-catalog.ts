/**
 * T2-03 · `permission` —— **平台级权限码字典**（白名单通道 #1）。
 *
 * 为什么可以没有 scope（强制理由，逐字登记在 `unscoped-repo.ts` 的
 * {@link UNSCOPED_WHITELIST}）：`code` 全平台唯一一份、不按租户复制，表里没有
 * `tenant_id` 列，也不含任何租户私有数据。计划 §2 把这张表的访问通道定为
 * `PermissionCatalog`（白名单 #1），**只此三处**。
 *
 * 本版落地的权限码（计划 §4.1）：`marketplace:import` · `marketplace:export` ·
 * `evaluation:read` · `evaluation:write` · `evaluation:run` · `*`。前 5 码的路由族在
 * 0.5/0.7，本版只落「字典行 + 守卫单测」；字典内容属 bootstrap 种子，**不产生 DDL**。
 */

import { eq, inArray, type InferSelectModel } from "drizzle-orm";

import { permission as pgPermission } from "../schema/pg/index.js";
import { permission as sqlitePermission } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import type { DrizzleDatabase, ListOptions } from "./scoped-repo.js";
import { UNSCOPED_WHITELIST, UnscopedTableRepo } from "./unscoped-repo.js";

/** `permission` 行。 */
export type PermissionRow = InferSelectModel<typeof pgPermission>;

/** 通配权限码（`ADMIN_PERMISSION`）：`code ∈ codes ∪ {"*"}` 里的那个 `*`。 */
export const ADMIN_PERMISSION = "*";

export class PermissionCatalog extends UnscopedTableRepo<PermissionRow> {
  constructor(db: DrizzleDatabase, dialect: SqlDialect = "pg") {
    super(
      db,
      resolveTable(dialect, pgPermission, sqlitePermission),
      UNSCOPED_WHITELIST.permission
    );
  }

  /**
   * 全平台权限码字典。
   *
   * 这是白名单通道里**唯一**允许"全表列举"的方法：字典行是平台公共数据（不含租户
   * 私有信息），列举它不会泄漏任何租户的行。`options.limit` 仍是 1..500 的严格规则。
   */
  listAll(options: ListOptions = {}): Promise<PermissionRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /** 按码取字典行（`code` 唯一索引 `ix_permission_code`）。 */
  findByCode(code: string): Promise<PermissionRow | null> {
    return this.findOneWhere(eq(this.columns.code, code));
  }

  /** 全部权限码字面量（`can()` 判定的字典侧输入）。 */
  async listCodes(options: ListOptions = {}): Promise<string[]> {
    const rows = await this.listAll(options);
    return rows.map((row) => row.code);
  }

  /** 按 id 集合取字典行（供 `RolePermissionCatalog.listCodesByRoleIds` 做第二跳）。 */
  async listByIds(ids: readonly string[], options: ListOptions = {}): Promise<PermissionRow[]> {
    const unique = [...new Set(ids.filter((id) => typeof id === "string" && id !== ""))];
    if (unique.length === 0) return [];
    return this.findManyWhere(inArray(this.columns.id, unique), options);
  }

  /** 按 id 集合取权限码（空集合 ⇒ `[]`，不打库）。 */
  async listCodesByIds(ids: readonly string[], options: ListOptions = {}): Promise<string[]> {
    const rows = await this.listByIds(ids, options);
    return rows.map((row) => row.code);
  }
}
