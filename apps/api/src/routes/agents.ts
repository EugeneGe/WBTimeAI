/**
 * T3-05 · Agent / AgentVersion **7 op**（§2 W3 任务卡；契约 path 逐字）。
 *
 * | # | Method · Path | 成功码 | 说明 |
 * |---|---|---|---|
 * | 1 | GET `/api/v1/agents` | 200 | `?page=&page_size=` 分页（缺省 1 / 20，上限 100） |
 * | 2 | POST `/api/v1/agents` | 201 | 创建（`DRAFT`，无当前版本） |
 * | 3 | GET `/api/v1/agents/{agent_id}` | 200 | 详情（跨租户 / 不存在 ⇒ 404） |
 * | 4 | PUT `/api/v1/agents/{agent_id}` | 200 | 更新 name / description / **status（走状态机）** |
 * | 5 | POST `/api/v1/agents/{agent_id}/publish` | 201 | 发布新版本（一次发布 = 一个新行；不可变快照） |
 * | 6 | POST `/api/v1/agents/{agent_id}/run` | 200 | **只做入口与前置校验**（执行归 T3-08） |
 * | 7 | GET `/api/v1/agents/{agent_id}/versions` | 200 | 版本列表（不可变快照） |
 *
 * 404 语义（I-1 口径延续）：agent / 版本 / 会话不可见（不存在或跨租户）⇒ 404
 * `NOT_FOUND`，**不是** 403。认证必须早于入参校验（`preValidation`，同 19 op 惯例）。
 */

import type { FastifyInstance } from "fastify";

import { ERROR_CODES } from "@wbtime/core";

import { authError } from "../modules/auth/errors.js";
import {
  CreateAgentRequestSchema,
  PublishRequestSchema,
  UpdateAgentRequestSchema,
  type CreateAgentRequestBody,
  type PublishRequestBody,
  type UpdateAgentRequestBody,
} from "./schemas.js";
import { RunRequestSchema, type RunRequestBody } from "./schemas-run.js";
import { authenticate, contextOf, requiredParam, singleQueryValue, type IdentityDeps } from "./support.js";

/** 分页查询参数解析（契约：`page` ≥ 1 缺省 1；`page_size` ∈ 1..100 缺省 20；非法 ⇒ 422）。 */
function parsePagination(
  query: Record<string, unknown>,
  toError: (message: string) => Error,
): { page?: number; pageSize?: number } {
  const out: { page?: number; pageSize?: number } = {};
  const rawPage = singleQueryValue(query.page);
  if (rawPage !== undefined) {
    const page = Number(rawPage);
    if (!Number.isInteger(page) || page < 1) {
      throw toError(`page 非法（实测 ${JSON.stringify(rawPage)}），须为 ≥ 1 的整数`);
    }
    out.page = page;
  }
  const rawSize = singleQueryValue(query.page_size);
  if (rawSize !== undefined) {
    const size = Number(rawSize);
    if (!Number.isInteger(size) || size < 1 || size > 100) {
      throw toError(`page_size 非法（实测 ${JSON.stringify(rawSize)}），须为 1..100 的整数`);
    }
    out.pageSize = size;
  }
  return out;
}

/**
 * 注册 Agent 族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `agents: AgentService`，见 `app.ts` 装配）。
 */
export function agentRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.agents;
  // 与 19 op 的校验出口同形：校验错误恒 422 `VALIDATION_ERROR`（httpStatusOf 派生）。
  const validationError = (message: string) => authError(ERROR_CODES.VALIDATION_ERROR, message);

  // 1. GET /agents —— 200（page / page_size 分页）
  app.get("/api/v1/agents", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    const tenantId = context.scope.tenantId;
    const { page, pageSize } = parsePagination(
      (request.query ?? {}) as Record<string, unknown>,
      validationError,
    );
    return service.list(tenantId, page, pageSize);
  });

  // 2. POST /agents —— 201（DRAFT，无当前版本）
  app.post(
    "/api/v1/agents",
    { preValidation: authenticate(deps), schema: { body: CreateAgentRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as CreateAgentRequestBody;
      const created = await service.create(context.scope.tenantId, context.user.id, {
        name: body.name,
        description: body.description ?? null,
        type: body.type,
        workspace_id: body.workspace_id ?? null,
      });
      reply.code(201);
      return created;
    },
  );

  // 3. GET /agents/{agent_id} —— 200 / 404
  app.get(
    "/api/v1/agents/:agent_id",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const agentId = requiredParam(request.params, "agent_id");
      return service.get(context.scope.tenantId, agentId);
    },
  );

  // 4. PUT /agents/{agent_id} —— 200（name / description 直改；status 转接 transition）
  app.put(
    "/api/v1/agents/:agent_id",
    { preValidation: authenticate(deps), schema: { body: UpdateAgentRequestSchema } },
    async (request) => {
      const context = contextOf(request);
      const agentId = requiredParam(request.params, "agent_id");
      const body = request.body as UpdateAgentRequestBody;
      return service.update(context.scope.tenantId, agentId, {
        name: body.name,
        description: body.description,
        status: body.status,
      });
    },
  );

  // 5. POST /agents/{agent_id}/publish —— 201（一次发布 = 一个新行）
  app.post(
    "/api/v1/agents/:agent_id/publish",
    { preValidation: authenticate(deps), schema: { body: PublishRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const agentId = requiredParam(request.params, "agent_id");
      const body = request.body as PublishRequestBody;
      const published = await service.publish(
        context.scope.tenantId,
        agentId,
        context.user.id,
        {
          version: body.version ?? null,
          system_prompt: body.system_prompt,
          model_config: body.model_config,
          runtime_config: body.runtime_config,
          // `tools` 收下不落库（§13.8.7 挂账 #7：agent_tool 承接归后续接线），
          // 见 `versioning.ts` 文件头注 —— 不在服务层臆造绑定语义。
          tools: body.tools,
        },
      );
      reply.code(201);
      return published;
    },
  );

  // 6. POST /agents/{agent_id}/run —— 200（只做入口与前置校验；执行归 T3-08）
  app.post(
    "/api/v1/agents/:agent_id/run",
    { preValidation: authenticate(deps), schema: { body: RunRequestSchema } },
    async (request) => {
      const context = contextOf(request);
      const agentId = requiredParam(request.params, "agent_id");
      const body = (request.body ?? {}) as RunRequestBody;
      return service.runEntry(context.scope.tenantId, agentId, context.user.id, request.id, {
        message: body.message,
        conversation_id: body.conversation_id ?? null,
        workspace_id: body.workspace_id ?? null,
        run_mode: body.run_mode,
      });
    },
  );

  // 7. GET /agents/{agent_id}/versions —— 200（不可变快照）
  app.get(
    "/api/v1/agents/:agent_id/versions",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const agentId = requiredParam(request.params, "agent_id");
      return service.listVersions(context.scope.tenantId, agentId);
    },
  );
}
