/**
 * T2-03 · `role_permission` —— role × permission 连接（白名单通道 #2）。
 *
 * 为什么可以没有 scope：连接表自身没有 `tenant_id`，租户归属经 `role.tenant_id`
 * **回指**（计划 §2）。为了让"回指"真的成立，本通道的**所有**查询都必须带
 * `role_id` 集合，且该集合必须来自 scoped 侧（`RoleRepo.listByIds` /
 * `MembershipRepo.listActiveRoleIdsByUser`）—— 因此本类**不提供**"全表列举"入口。
 *
 * RBAC 三层合流的中间一跳就在这里：
 * `membership.role_id` →（本类）`permission_id` →（`PermissionCatalog`）`code`。
 */

import { inArray, type InferSelectModel } from "drizzle-orm";

import { role_permission as pgRolePermission } from "../schema/pg/index.js";
import { role_permission as sqliteRolePermission } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import { PermissionCatalog } from "./permission-catalog.js";
import type { DrizzleDatabase, ListOptions } from "./scoped-repo.js";
import { UNSCOPED_WHITELIST, UnscopedTableRepo } from "./unscoped-repo.js";

/** `role_permission` 行。 */
export type RolePermissionRow = InferSelectModel<typeof pgRolePermission>;

export class RolePermissionCatalog extends UnscopedTableRepo<RolePermissionRow> {
  readonly #permissions: PermissionCatalog;

  /**
   * @param db drizzle 实例
   * @param dialect 方言（缺省 pg）
   * @param permissions 字典侧句柄；缺省自建一个同方言的 {@link PermissionCatalog}
   *   （第三跳 `permission_id → code` 需要它；注入是为了测试可换、生产可复用同一实例）
   */
  constructor(
    db: DrizzleDatabase,
    dialect: SqlDialect = "pg",
    permissions: PermissionCatalog = new PermissionCatalog(db, dialect)
  ) {
    super(
      db,
      resolveTable(dialect, pgRolePermission, sqliteRolePermission),
      UNSCOPED_WHITELIST.role_permission
    );
    this.#permissions = permissions;
  }

  /**
   * 按 role id 集合取连接行。
   *
   * 空集合 ⇒ `[]`（不打库、不生成 `inArray(col, [])` 这种"永远假"的 SQL）。
   * role id 的去重与空值过滤在这里做一次：`null` 混进 `inArray` 会放宽匹配面。
   */
  async listByRoleIds(
    roleIds: readonly string[],
    options: ListOptions = {}
  ): Promise<RolePermissionRow[]> {
    const unique = normalizeIds(roleIds);
    if (unique.length === 0) return [];
    return this.findManyWhere(inArray(this.columns.role_id, unique), options);
  }

  /** 按 role id 集合取 `permission_id`（去重，保持首次出现顺序）。 */
  async listPermissionIdsByRoleIds(roleIds: readonly string[]): Promise<string[]> {
    const rows = await this.listByRoleIds(roleIds, { limit: 500 });
    const seen = new Set<string>();
    for (const row of rows) {
      if (typeof row.permission_id === "string" && row.permission_id !== "") {
        seen.add(row.permission_id);
      }
    }
    return [...seen];
  }

  /**
   * 按 role id 集合取**权限码**（三层合流的第 2 + 3 跳）。
   *
   * 返回值**未**并入通配符 `*`：`code ∈ codes ∪ {"*"}` 的并集判断在 Service 的
   * `can()` 里做（判定层在 Router/Service，不在这里，见计划 §4.3）。
   */
  async listCodesByRoleIds(roleIds: readonly string[]): Promise<string[]> {
    const permissionIds = await this.listPermissionIdsByRoleIds(roleIds);
    if (permissionIds.length === 0) return [];
    return this.#permissions.listCodesByIds(permissionIds);
  }
}

/** 去重 + 去掉空串/null（`inArray` 的入参必须干净）。 */
function normalizeIds(ids: readonly string[]): string[] {
  const unique = new Set<string>();
  for (const id of ids) {
    if (typeof id === "string" && id !== "") unique.add(id);
  }
  return [...unique];
}
