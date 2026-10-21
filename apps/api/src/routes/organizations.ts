/**
 * T2-07 · 组织族 2 个 op（§1 表 9–10）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 9 | GET `/api/v1/organizations` | 200 |
 * | 10 | GET `/api/v1/organizations/{organization_id}` | 200 |
 *
 * 第 10 条是 J-7 的四个 I-1 判据之一：**跨租户 ⇒ 404 而不是 403**。
 * 实现上不需要任何 `if`：`OrganizationRepo.findById` 收 `Scope#ref(id)`，
 * `scopedWhere()` 恒 and `tenant_id`，所以"别人的组织"根本查不到 ⇒ 折成
 * `ORGANIZATION_NOT_FOUND`(404)。这条边界**不能**改成"先查再判租户、不一致 403"。
 */

import type { FastifyInstance } from "fastify";

import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 注册组织族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖。
 */
export function organizationRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // ⑨ GET /organizations —— 200（数组，元素为 OrganizationResponse）
  app.get("/api/v1/organizations", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    return deps.organizations.list(context.scope.tenantId);
  });

  // ⑩ GET /organizations/{organization_id} —— 200 / 跨租户 404
  app.get("/api/v1/organizations/:organization_id", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    const organizationId = requiredParam(request.params, "organization_id");
    return deps.organizations.get(context.scope.tenantId, organizationId);
  });
}
