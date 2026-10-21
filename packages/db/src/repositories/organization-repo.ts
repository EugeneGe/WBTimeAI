/**
 * T2-03 · `organization` 仓储（租户下的二级范围）。
 *
 * 组织是**三级过滤**里的第二级（`tenant` ⊃ `organization` ⊃ `workspace`）；
 * 本版不建 workspace 表与路由（归 V0.6.0），故这一级只做「按 slug 取」与「列举」。
 * `(tenant_id, slug)` 唯一 ⇒ 查询必须带租户条件，否则 A 租户的 slug 会命中 B 租户
 * 的行（I-1 的典型破口）。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { organization as pgOrganization } from "../schema/pg/index.js";
import { organization as sqliteOrganization } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `organization` 行。 */
export type OrganizationRow = InferSelectModel<typeof pgOrganization>;

export class OrganizationRepo extends ScopedRepo<OrganizationRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgOrganization, sqliteOrganization), scope);
  }

  /** 按 slug 取组织（scope 内；`GET /organizations/{id}` 的 404 判定由此行缺失产生）。 */
  findBySlug(slug: string): Promise<OrganizationRow | null> {
    return this.findOneWhere(eq(this.columns.slug, slug));
  }

  /** 列举本租户组织（`GET /organizations`）。 */
  list(options: ListOptions = {}): Promise<OrganizationRow[]> {
    return this.findManyWhere(undefined, options);
  }

  create(row: TenantScopedInsert<OrganizationRow>): Promise<OrganizationRow> {
    return this.insertRow(row);
  }
}
