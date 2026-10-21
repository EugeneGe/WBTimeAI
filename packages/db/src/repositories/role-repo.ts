/**
 * T2-03 · `role` 仓储（角色）。
 *
 * 关键列语义（计划 §2）：`(tenant_id, name)` 唯一；`is_system=true` **不许删**。
 *
 * `is_system` 的删除保护刻意**不**做成本仓储里的 `if` 分支：仓储不应表达业务拒绝
 * （计划 §4.3「repositories 层不判权限/规则，只做 scope 过滤」）。本类提供
 * {@link RoleRepo.findById}（继承）让 Service 读到 `is_system` 后自己决定 403/409 ——
 * 仓储这一侧只保证「看不见别的租户」。
 */

import { eq, inArray, type InferSelectModel } from "drizzle-orm";

import { role as pgRole } from "../schema/pg/index.js";
import { role as sqliteRole } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `role` 行。 */
export type RoleRow = InferSelectModel<typeof pgRole>;

export class RoleRepo extends ScopedRepo<RoleRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgRole, sqliteRole), scope);
  }

  /** 按角色名取（`(tenant_id, name)` 唯一，故 scope 内最多 1 行）。 */
  findByName(name: string): Promise<RoleRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /** 列举本租户角色（`GET` 类管理面用）。 */
  list(options: ListOptions = {}): Promise<RoleRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /**
   * 按 id 集合取角色 —— **只在 scope 内命中**。
   *
   * 存在的理由：`RolePermissionCatalog`（白名单 #2，无 scope）只接受「已由 scoped
   * 查询筛过的 role id 集合」。本方法就是那个筛子：即使调用方塞进别的租户的 role id，
   * 结果里也不会出现跨租户行，下游 code 合流因此不会扩散。
   *
   * 空集合直接返回 `[]`（不让 `inArray(col, [])` 生成 SQL 再到运行时才发现）。
   */
  listByIds(ids: readonly string[], options: ListOptions = {}): Promise<RoleRow[]> {
    const unique = [...new Set(ids.filter((id) => typeof id === "string" && id !== ""))];
    if (unique.length === 0) return Promise.resolve([]);
    return this.findManyWhere(inArray(this.columns.id, unique), options);
  }

  create(row: TenantScopedInsert<RoleRow>): Promise<RoleRow> {
    return this.insertRow(row);
  }
}
