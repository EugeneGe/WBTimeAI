/**
 * T3-07 · Conversation / Message **5 op**（§2 W4 任务卡；契约 path / 成功码逐字）。
 *
 * | # | Method · Path | 成功码 | 说明 |
 * |---|---|---|---|
 * | 1 | GET `/api/v1/conversations` | 200 | 数组；契约 `parameters=[]`（**无分页参数**） |
 * | 2 | POST `/api/v1/conversations` | 201 | 创建（`status=ACTIVE`；`workspace_id` 缺失 ⇒ 422） |
 * | 3 | GET `/api/v1/conversations/{conversation_id}` | 200 | 详情（跨租户 / 不存在 ⇒ 404） |
 * | 4 | PUT `/api/v1/conversations/{conversation_id}` | 200 | **只改 title**（契约 `UpdateConversationRequest` 仅 1 键） |
 * | 5 | GET `/api/v1/conversations/{conversation_id}/messages` | 200 | 消息数组（`created_at` 升序 + `id` 并列键） |
 *
 * 404 语义（I-1 口径延续）：会话不可见（不存在或跨租户）⇒ 404 `NOT_FOUND`，**不是** 403；
 * 且所有 404 都来自**scope 内查询**，不来自 `Scope#owns()`（后者只是 mint provenance，
 * 见 `packages/db/src/repositories/scoped-repo.ts` 的心智模型注）。
 *
 * 认证必须早于入参校验（`preValidation`，与既有 33 op 惯例一致）：否则未认证请求带
 * 非法 body 会先被 schema 挡成 422，"有没有令牌"这件事就被绕开了。
 *
 * **不注册**的路径（刻意）：`DELETE /conversations/{id}` 与 `POST /conversations/{id}/messages`
 * 在契约里都不存在（实测 5 条 path 无 delete、无消息写 op）⇒ 本文件不注册，
 * `routes-invariants.test.mjs` 的守恒断言会把"顺手加一条"打红。
 */

import type { FastifyInstance } from "fastify";

import {
  CreateConversationRequestSchema,
  UpdateConversationRequestSchema,
  type CreateConversationRequestBody,
  type UpdateConversationRequestBody,
} from "./schemas.js";
import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 注册 Conversation 族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `conversations: ConversationService`，见 `app.ts` 装配）。
 */
export function conversationRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.conversations;

  // 1. GET /conversations —— 200（契约 parameters=[] ⇒ 不解析任何 query）
  app.get(
    "/api/v1/conversations",
    { preValidation: authenticate(deps) },
    async (request) => service.list(contextOf(request).scope.tenantId),
  );

  // 2. POST /conversations —— 201
  app.post(
    "/api/v1/conversations",
    { preValidation: authenticate(deps), schema: { body: CreateConversationRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as CreateConversationRequestBody;
      const created = await service.create(context.scope.tenantId, context.user.id, {
        agent_id: body.agent_id,
        // schema 给了 `default: ""`，这里再兜一层：取值来源不是 schema 时（如直接调
        // service 的测试）也不会把 `undefined` 送进 SQL。
        title: body.title ?? "",
        workspace_id: body.workspace_id ?? "",
      });
      reply.code(201);
      return created;
    },
  );

  // 3. GET /conversations/{conversation_id} —— 200 / 404
  app.get(
    "/api/v1/conversations/:conversation_id",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const conversationId = requiredParam(request.params, "conversation_id");
      return service.get(context.scope.tenantId, conversationId);
    },
  );

  // 4. PUT /conversations/{conversation_id} —— 200（只改 title）
  app.put(
    "/api/v1/conversations/:conversation_id",
    { preValidation: authenticate(deps), schema: { body: UpdateConversationRequestSchema } },
    async (request) => {
      const context = contextOf(request);
      const conversationId = requiredParam(request.params, "conversation_id");
      const body = request.body as UpdateConversationRequestBody;
      return service.rename(context.scope.tenantId, conversationId, body.title);
    },
  );

  // 5. GET /conversations/{conversation_id}/messages —— 200
  app.get(
    "/api/v1/conversations/:conversation_id/messages",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const conversationId = requiredParam(request.params, "conversation_id");
      return service.listMessages(context.scope.tenantId, conversationId);
    },
  );
}
