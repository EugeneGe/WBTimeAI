/**
 * T3-06 · Skill **7 op**（§2 W3 任务卡；契约 path 逐字）。
 *
 * | # | Method · Path | 成功码 | 说明 |
 * |---|---|---|---|
 * | 1 | GET `/api/v1/skills` | 200 | 列表（契约无分页参数 —— py `list_by_tenant` 同） |
 * | 2 | POST `/api/v1/skills` | 201 | 创建（`status = DRAFT`，无当前版本） |
 * | 3 | GET `/api/v1/skills/{skill_id}` | 200 | 详情（跨租户 / 不存在 ⇒ 404） |
 * | 4 | PUT `/api/v1/skills/{skill_id}` | 200 | 更新 display_name / description / category / **status** |
 * | 5 | POST `/api/v1/skills/{skill_id}/publish` | 200 | 发布**最新** DRAFT 版本（发布即冻结） |
 * | 6 | GET `/api/v1/skills/{skill_id}/versions` | 200 | 版本列表（不可变快照） |
 * | 7 | POST `/api/v1/skills/{skill_id}/versions` | 201 | 创建 DRAFT 版本 |
 *
 * 404 语义（I-1 口径延续）：skill / 版本不可见（不存在或跨租户）⇒ 404 `NOT_FOUND`，
 * **不是** 403。认证必须早于入参校验（`preValidation`，同 19 op 惯例）。
 * 范围红线：**不做 Skill 执行**（Skill 是提示词/资源包，非工具）—— 本文件无任何执行入口。
 */

import type { FastifyInstance } from "fastify";

import {
  CreateSkillRequestSchema,
  CreateSkillVersionRequestSchema,
  UpdateSkillRequestSchema,
  type CreateSkillRequestBody,
  type CreateSkillVersionRequestBody,
  type UpdateSkillRequestBody,
} from "./schemas.js";
import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 注册 Skill 族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `skills: SkillService`，见 `app.ts` 装配）。
 */
export function skillRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.skills;
  // 本族校验全部由 body schema（Fastify/Ajv ⇒ 统一 422 出口）与服务层承担；
  // 服务层把 repo 的 ScopeError 统一翻 VALIDATION_ERROR / CONFLICT，路由层零手判。

  // 1. GET /skills —— 200（无分页：契约与 py list_by_tenant 均无分页参数）
  app.get("/api/v1/skills", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    return service.list(context.scope.tenantId);
  });

  // 2. POST /skills —— 201（DRAFT，无当前版本；重名 ⇒ 409 服务层给）
  app.post(
    "/api/v1/skills",
    { preValidation: authenticate(deps), schema: { body: CreateSkillRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as CreateSkillRequestBody;
      const created = await service.create(context.scope.tenantId, context.user.id, {
        name: body.name,
        display_name: body.display_name,
        description: body.description ?? null,
        category: body.category,
      });
      reply.code(201);
      return created;
    },
  );

  // 3. GET /skills/{skill_id} —— 200 / 404
  app.get(
    "/api/v1/skills/:skill_id",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const skillId = requiredParam(request.params, "skill_id");
      return service.get(context.scope.tenantId, skillId);
    },
  );

  // 4. PUT /skills/{skill_id} —— 200（缺省字段不变；显式 null = 不变，py is not None 同口径）
  app.put(
    "/api/v1/skills/:skill_id",
    { preValidation: authenticate(deps), schema: { body: UpdateSkillRequestSchema } },
    async (request) => {
      const context = contextOf(request);
      const skillId = requiredParam(request.params, "skill_id");
      const body = request.body as UpdateSkillRequestBody;
      return service.update(context.scope.tenantId, skillId, {
        display_name: body.display_name,
        description: body.description,
        category: body.category,
        status: body.status,
      });
    },
  );

  // 5. POST /skills/{skill_id}/publish —— 200（发布最新 DRAFT；无 DRAFT ⇒ 409 服务层给）
  app.post(
    "/api/v1/skills/:skill_id/publish",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const skillId = requiredParam(request.params, "skill_id");
      return service.publish(context.scope.tenantId, skillId);
    },
  );

  // 6. GET /skills/{skill_id}/versions —— 200（不可变快照）
  app.get(
    "/api/v1/skills/:skill_id/versions",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      const skillId = requiredParam(request.params, "skill_id");
      return service.listVersions(context.scope.tenantId, skillId);
    },
  );

  // 7. POST /skills/{skill_id}/versions —— 201（DRAFT 版本；版本号重复 ⇒ 409 服务层给）
  app.post(
    "/api/v1/skills/:skill_id/versions",
    { preValidation: authenticate(deps), schema: { body: CreateSkillVersionRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const skillId = requiredParam(request.params, "skill_id");
      const body = request.body as CreateSkillVersionRequestBody;
      const created = await service.createVersion(context.scope.tenantId, skillId, context.user.id, {
        version: body.version,
        instructions: body.instructions,
        manifest: body.manifest,
      });
      reply.code(201);
      return created;
    },
  );
}
