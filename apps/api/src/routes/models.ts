/**
 * T2-07 · 模型/凭证族 **5 op**（§1 表 15–19）+ T3-12 · 模型目录 **6 op** = **11 op**。
 *
 * | # | Method · Path | 成功码 | 归属 |
 * |---|---|---|---|
 * | 15 | GET `/api/v1/models/credentials` | 200 | T2-07 |
 * | 16 | POST `/api/v1/models/credentials` | 201 | T2-07 |
 * | 17 | DELETE `/api/v1/models/credentials/{credential_id}` | **204** | T2-07 |
 * | 18 | POST `/api/v1/models/providers/{provider_id}/credential` | 200 | T2-07 |
 * | 19 | DELETE `/api/v1/models/providers/{provider_id}/credential` | 200 | T2-07 |
 * | 20 | GET `/api/v1/models/providers` | 200 | T3-12 |
 * | 21 | POST `/api/v1/models/providers` | **201** | T3-12 |
 * | 22 | GET `/api/v1/models/providers/{provider_id}` | 200 | T3-12 |
 * | 23 | DELETE `/api/v1/models/providers/{provider_id}` | 200 | T3-12（**软删**） |
 * | 24 | GET `/api/v1/models/providers/{provider_id}/models` | 200 | T3-12 |
 * | 25 | POST `/api/v1/models/providers/{provider_id}/models` | **201** | T3-12 |
 *
 * 安全要点：明文凭据**只在** `POST /models/credentials` 的请求体里出现一次，随后由
 * `CredentialService.save()` 加密落库，响应只回 `masked_value`（`****ab12`）。
 * 列表接口**不解密**（掩码存在 `metadata` 里）。
 *
 * 404 语义（J-7 第 2/3 族）：凭据 / 供应商 / 模型目录的父不可见（不存在或跨租户）
 * ⇒ 404 `CREDENTIAL_NOT_FOUND` / `NOT_FOUND`，**不是** 403。
 *
 * ⚠️ 两个 DELETE 的成功码**不同形**，这不是笔误
 * ------------------------------------------
 *   - `DELETE /credentials/{id}` = **204 零字节**（真删凭据行）；
 *   - `DELETE /providers/{id}` = **200 + 整行**（**软删**：`status = DISABLED`）。
 *   契约原文如此，py 亦如此（`disable_provider` 只改状态并 `update`）。
 *   把前者写宽成 200、或把后者写窄成 204，`openapi-alignment` 与 J-10 都会红。
 */

import type { FastifyInstance } from "fastify";

import {
  BindCredentialRequestSchema,
  RegisterModelRequestSchema,
  RegisterProviderRequestSchema,
  SaveCredentialRequestSchema,
  type BindCredentialRequestBody,
  type RegisterModelRequestBody,
  type RegisterProviderRequestBody,
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

  // ---------------------------------------------------------------------------
  // T3-12 · 模型目录 6 op（补 §5 盘点缺口；与凭证族共用同一 `deps`，服务分开）
  // ---------------------------------------------------------------------------

  // ⑳ GET /models/providers —— 200（本租户全部供应商；契约无分页参数）
  app.get(
    "/api/v1/models/providers",
    { preValidation: authenticate(deps) },
    async (request) => deps.providers.listProviders(contextOf(request).scope.tenantId)
  );

  // ㉑ POST /models/providers —— 201
  //     两条服务层 422（契约不约束）：`name` trim 后空 / `provider_type` 不在白名单。
  app.post(
    "/api/v1/models/providers",
    { preValidation: authenticate(deps), schema: { body: RegisterProviderRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as RegisterProviderRequestBody;
      const created = await deps.providers.registerProvider(context.scope.tenantId, {
        name: body.name,
        providerType: body.provider_type,
        endpoint: body.endpoint ?? null,
        credentialId: body.credential_id ?? null,
        config: body.config ?? {},
        workspaceId: body.workspace_id ?? null,
      });
      reply.code(201);
      return created;
    }
  );

  // ㉒ GET /models/providers/{provider_id} —— 200（不可见 ⇒ 404）
  app.get(
    "/api/v1/models/providers/:provider_id",
    { preValidation: authenticate(deps) },
    async (request) =>
      deps.providers.getProvider(
        contextOf(request).scope.tenantId,
        requiredParam(request.params, "provider_id")
      )
  );

  // ㉓ DELETE /models/providers/{provider_id} —— **200 + 整行**（软删：status=DISABLED）
  app.delete(
    "/api/v1/models/providers/:provider_id",
    { preValidation: authenticate(deps) },
    async (request) =>
      deps.providers.disableProvider(
        contextOf(request).scope.tenantId,
        requiredParam(request.params, "provider_id")
      )
  );

  // ㉔ GET /models/providers/{provider_id}/models —— 200（供应商不可见 ⇒ 404）
  app.get(
    "/api/v1/models/providers/:provider_id/models",
    { preValidation: authenticate(deps) },
    async (request) =>
      deps.providers.listModels(
        contextOf(request).scope.tenantId,
        requiredParam(request.params, "provider_id")
      )
  );

  // ㉕ POST /models/providers/{provider_id}/models —— 201（供应商不可见 ⇒ 404）
  app.post(
    "/api/v1/models/providers/:provider_id/models",
    { preValidation: authenticate(deps), schema: { body: RegisterModelRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const providerId = requiredParam(request.params, "provider_id");
      const body = request.body as RegisterModelRequestBody;
      const created = await deps.providers.registerModel(context.scope.tenantId, providerId, {
        name: body.name,
        ...(body.model_type === undefined ? {} : { modelType: body.model_type }),
        ...(body.context_window === undefined ? {} : { contextWindow: body.context_window }),
        ...(body.capabilities === undefined ? {} : { capabilities: body.capabilities }),
      });
      reply.code(201);
      return created;
    }
  );
}
