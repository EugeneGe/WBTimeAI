/**
 * T2-07 · 组织服务（`GET /organizations` / `GET /organizations/{id}`）。
 *
 * 只做两件事：列本租户组织、按 id 取单个组织（拿不到 ⇒ 404 `ORGANIZATION_NOT_FOUND`）。
 *
 * 404 而不是 403 的理由（I-1，计划 §5.1）
 * ------------------------------------
 * `OrganizationRepo.findById` 收的是 `Scope#ref(id)`，`scopedWhere()` 恒 and `tenant_id`。
 * 所以"别的租户的组织"在这里根本**查不到** —— 查不到就只能是 404。若这里改成"先查
 * 再判租户、不一致返 403"，等于用 403 告诉调用方"这个 id 确实存在，只是不给你看"，
 * 那就是跨租户存在性泄漏，也正是 I-1 要消灭的东西。
 */

import { OrganizationRepo, Scope, type DrizzleDatabase, type OrganizationRow, type SqlDialect } from "@wbtime/db";

import { authError } from "../auth/errors.js";
import { ERROR_CODES } from "@wbtime/core";

/** 对外组织视图（契约 `OrganizationResponse`，键集合逐字对齐）。 */
export interface OrganizationView {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly tenant_id: string | null;
}

/** 组织服务。 */
export class OrganizationService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: { readonly db: DrizzleDatabase; readonly dialect?: SqlDialect }) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
  }

  /**
   * 列本租户组织。
   *
   * @param tenantId 租户（来自已认证主体，不来自请求参数）。
   */
  async list(tenantId: string): Promise<OrganizationView[]> {
    const scope = new Scope(tenantId);
    const repo = new OrganizationRepo(this.#db, scope, this.#dialect);
    const rows = await repo.list({ limit: 500 });
    return rows.map(toOrganizationView);
  }

  /**
   * 取单个组织；不可见（不存在 / 跨租户）一律 404。
   *
   * @param tenantId 租户。
   * @param organizationId 组织 id（裸 id 在仓储层进不去，这里由本方法包成 `ScopedRef`）。
   * @throws {HttpException} `ORGANIZATION_NOT_FOUND`（404）。
   */
  async get(tenantId: string, organizationId: string): Promise<OrganizationView> {
    const scope = new Scope(tenantId);
    const repo = new OrganizationRepo(this.#db, scope, this.#dialect);
    const row = await repo.findById(scope.ref(organizationId));
    if (row === null) {
      throw authError(ERROR_CODES.ORGANIZATION_NOT_FOUND, "组织不存在", {
        organization_id: organizationId,
      });
    }
    return toOrganizationView(row);
  }
}

/** 行 → 契约视图。 */
function toOrganizationView(row: OrganizationRow): OrganizationView {
  return {
    id: row.id,
    name: row.name,
    slug: row.slug,
    tenant_id: row.tenant_id ?? null,
  };
}
