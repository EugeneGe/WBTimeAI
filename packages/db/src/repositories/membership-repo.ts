/**
 * T2-03 · `membership` 仓储（**唯一**的 user × org × role 连接）。
 *
 * 关键列语义（计划 §2）：`organization_id` / `role_id` 可空；`status` 非 `ACTIVE`
 * **不授予权限**。契约里没有 `user_role` 表，所以「用户的角色」只能从这里取 ——
 * RBAC 三层合流（`permission.code` → `role_permission` → `membership.role_id`）的
 * **起点**就是本仓储的 {@link MembershipRepo.listActiveRoleIdsByUser}。
 */

import { and, eq, isNotNull, type InferSelectModel } from "drizzle-orm";

import { membership as pgMembership } from "../schema/pg/index.js";
import { membership as sqliteMembership } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `membership` 行。 */
export type MembershipRow = InferSelectModel<typeof pgMembership>;

/** 唯一的「已生效」状态值（其余取值 = 不授权）。 */
export const MEMBERSHIP_STATUS_ACTIVE = "ACTIVE";

export class MembershipRepo extends ScopedRepo<MembershipRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgMembership, sqliteMembership), scope);
  }

  /**
   * 取某用户的全部成员关系（含非 ACTIVE；「设备/资料」这类展示面用）。
   *
   * 返回值里带 `role_id` / `organization_id` —— 调用方**必须**用
   * {@link listActiveByUser} 的语义自行筛 `status === "ACTIVE"` 后才可当授权依据。
   */
  listByUser(userRef: ScopedRef, options: ListOptions = {}): Promise<MembershipRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(eq(this.columns.user_id, userRef.id), options);
  }

  /** 取某用户**已生效**的成员关系（`status = ACTIVE`）。 */
  listActiveByUser(userRef: ScopedRef, options: ListOptions = {}): Promise<MembershipRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(
      and(
        eq(this.columns.user_id, userRef.id),
        eq(this.columns.status, MEMBERSHIP_STATUS_ACTIVE)
      ),
      options
    );
  }

  /**
   * 取某用户**已生效**成员关系里的 role id 集合（去重，保持发现顺序）。
   *
   * 这是 RBAC 判定的第一跳：`user → role_id[] → role_permission → permission.code`。
   * `role_id` 可空（组织级成员可能暂无角色）—— 空值不进结果集，否则下游
   * `inArray(role_id, ids)` 会带进 `null` 而放大查询面。
   */
  async listActiveRoleIdsByUser(userRef: ScopedRef): Promise<string[]> {
    const rows = await this.findManyWhere(
      and(
        eq(this.columns.user_id, userRef.id),
        eq(this.columns.status, MEMBERSHIP_STATUS_ACTIVE),
        isNotNull(this.columns.role_id)
      ),
      { limit: 500 }
    );
    const seen = new Set<string>();
    for (const row of rows) {
      if (typeof row.role_id === "string" && row.role_id !== "") seen.add(row.role_id);
    }
    return [...seen];
  }

  /** 取某组织下的成员关系（组织详情/成员面用）。 */
  listByOrganization(
    organizationRef: ScopedRef,
    options: ListOptions = {}
  ): Promise<MembershipRow[]> {
    this.assertOwnRef(organizationRef, "organizationRef");
    return this.findManyWhere(eq(this.columns.organization_id, organizationRef.id), options);
  }

  create(row: TenantScopedInsert<MembershipRow>): Promise<MembershipRow> {
    return this.insertRow(row);
  }
}
