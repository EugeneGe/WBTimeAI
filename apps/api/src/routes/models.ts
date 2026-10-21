/**
 * T2-07 · 模型/凭证族 5 个 op（§1 表 15–19）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 15 | GET `/api/v1/models/credentials` | 200 |
 * | 16 | POST `/api/v1/models/credentials` | 201 |
 * | 17 | DELETE `/api/v1/models/credentials/{credential_id}` | **204** |
 * | 18 | POST `/api/v1/models/providers/{provider_id}/credential` | 200 |
 * | 19 | DELETE `/api/v1/models/providers/{provider_id}/credential` | 200 |
 *
 * 安全要点：明文凭据**只在** `POST /models/credentials` 的请求体里出现一次，随后由
 * `CredentialService.save()` 加密落库，响应只回 `masked_value`（`****ab12`）。
 * 列表接口**不解密**（掩码存在 `metadata` 里）。
 *
 * 404 语义（J-7 第 2/3 族）：凭据 / 供应商不可见（不存在或跨租户）⇒ 404
 * `CREDENTIAL_NOT_FOUND` / `NOT_FOUND`，**不是** 403。
 */

import type { FastifyInstance } from "fastify";

import {
  BindCredentialRequestSchema,
  SaveCredentialRequestSchema,
  type BindCredentialRequestBody,
  type SaveCredentialRequestBody,
} from "./schemas.js";
import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 注册模型/凭证族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖。
 */
export function modelRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // ⑮ GET /models/credentials —— 200（掩码列表，永不含明文）
  app.get("/api/v1/models/credentials", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    return deps.credentials.list(context.scope.tenantId);
  });

  // ⑯ POST /models/credentials —— 201（加密后落库，回掩码）
  app.post(
    "/api/v1/models/credentials",
    { preValidation: authenticate(deps), schema: { body: SaveCredentialRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as SaveCredentialRequestBody;
      const created = await deps.credentials.save(context.scope.tenantId, {
        provider: body.provider,
        value: body.value,
        ...(body.key_type === undefined ? {} : { key_type: body.key_type }),
        workspace_id: body.workspace_id ?? null,
      });
      reply.code(201);
      return created;
    }
  );

  // ⑰ DELETE /models/credentials/{credential_id} —— **204 零字节体**（J-10）
  app.delete(
    "/api/v1/models/credentials/:credential_id",
    { preValidation: authenticate(deps) },
    async (request, reply) => {
    const context = contextOf(request);
    const credentialId = requiredParam(request.params, "credential_id");
    await deps.credentials.remove(context.scope.tenantId, credentialId);
    reply.code(204).send();
  });

  // ⑱ POST /models/providers/{provider_id}/credential —— 200（绑定）
  app.post(
    "/api/v1/models/providers/:provider_id/credential",
    { preValidation: authenticate(deps), schema: { body: BindCredentialRequestSchema } },
    async (request) => {
      const context = contextOf(request);
      const providerId = requiredParam(request.params, "provider_id");
      const body = request.body as BindCredentialRequestBody;
      return deps.credentials.bind(context.scope.tenantId, providerId, body.credential_id);
    }
  );

  // ⑲ DELETE /models/providers/{provider_id}/credential —— 200（解绑：credential_id 置 null）
  app.delete(
    "/api/v1/models/providers/:provider_id/credential",
    { preValidation: authenticate(deps) },
    async (request) => {
    const context = contextOf(request);
    const providerId = requiredParam(request.params, "provider_id");
    return deps.credentials.unbind(context.scope.tenantId, providerId);
  });
}
