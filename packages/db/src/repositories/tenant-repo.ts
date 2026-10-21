/**
 * T2-03 · `tenant` 仓储（隔离顶点 · **自作用域**表）。
 *
 * 这张表的特殊之处
 * ----------------
 * `tenant` 是隔离顶点**自身**：行 `id` 就是租户 id，表里没有也不该有 `tenant_id`
 * 列。因此它走 `ScopedRepo` 的 `selfScoped` 通道（scope 谓词由 `id` 列承载），
 * 而**不是** unscoped 白名单 —— 它依然必须带 `Scope` 构造，跨 scope 依然查不到行。
 *
 * 「slug → tenant」解析去哪了
 * -------------------------
 * py 线用 `identity.tenants.ensure_default()`（单租户部署假设）。TS 侧不复制这个
 * 无作用域的查询，而是：**tenant id 由配置给出 → 本仓储按 scope 校验其存在与
 * `is_active`**。这样 `tenant` 不会被悄悄扩成第 4 张 unscoped 表（计划 §2 白名单
 * 只此三处）。`is_active=false` ⇒ 该租户登录一律 401，判定所需的数据由
 * {@link TenantRepo.isActive} 提供。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { tenant as pgTenant } from "../schema/pg/index.js";
import { tenant as sqliteTenant } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
} from "./scoped-repo.js";

/** `tenant` 行（PG 档形状；SQLite 档的差异见 `dialect.ts` 的说明）。 */
export type TenantRow = InferSelectModel<typeof pgTenant>;

export class TenantRepo extends ScopedRepo<TenantRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgTenant, sqliteTenant), scope, { selfScoped: true });
  }

  /** 本租户是否启用（`is_active=false` ⇒ 登录一律 401）。 */
  async isActive(ref: ScopedRef): Promise<boolean> {
    this.assertOwnRef(ref, "tenantRef");
    const row = await this.findById(ref);
    return row !== null && row.is_active === true;
  }

  /** 列出启用的租户（本仓储下最多 1 行；供 bootstrap 自检与运维诊断）。 */
  listActive(options: ListOptions = {}): Promise<TenantRow[]> {
    return this.findManyWhere(eq(this.columns.is_active, true), options);
  }

  /** 本租户的 slug 是否与外部断言一致（用于校验配置/令牌里的 slug 声明）。 */
  async matchesSlug(slug: string): Promise<boolean> {
    const row = await this.findOneWhere(eq(this.columns.slug, slug));
    return row !== null;
  }
}
