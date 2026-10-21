/**
 * T2-07 · 权限族 4 个 op（§1 表 11–14）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 11 | GET `/api/v1/permissions/check` | 200 |
 * | 12 | GET `/api/v1/tools/permissions` | 200 |
 * | 13 | POST `/api/v1/tools/permissions` | 201 |
 * | 14 | DELETE `/api/v1/tools/permissions/{permission_id}` | **204** |
 *
 * 三处容易做错的地方（都已在测试里钉住）
 * ------------------------------------
 * 1. **`check` 无码也是 200**（J-6a）：`checkCapability` 返回的是**判定结果**，不是异常。
 *    "我没有 X 权限"是一个正常答案；把它做成 4xx 就等于"用 check 探自己权限的人先被自己的
 *    查询 403 掉"，本项目明确拒绝这种链路。
 * 2. **`/tools/permissions` 落的是 `resource_permission` 行**（计划 §2 / §5.2 第 4 族），
 *    不是 `tool_permission` 表：契约 `ToolPermissionResponse.tool_id` 对应
 *    `resource_permission.resource_id`，`agent_id` 对应 `subject_id`（`subject_type='agent'`）。
 * 3. **第 14 条的 204 是零字节体**（J-10）：`reply.code(204).send()`，不带任何 JSON。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  ResourcePermissionRepo,
  instantLiteral,
  type ResourcePermissionRow,
} from "@wbtime/db";
import type { FastifyInstance } from "fastify";

import { authError } from "../modules/auth/errors.js";
import { checkCapability } from "../modules/rbac/index.js";
import {
  CheckQuerySchema,
  ListToolPermissionsQuerySchema,
  ToolPermissionRequestSchema,
  type PermissionCheckResponseBody,
  type ToolPermissionRequestBody,
  type ToolPermissionResponseBody,
} from "./schemas.js";
import { authenticate, contextOf, requiredParam, requiredQuery, type IdentityDeps } from "./support.js";

/** `resource_permission.resource_type` 的固定取值（契约把这一族叫 tools/permissions）。 */
const RESOURCE_TYPE_TOOL = "TOOL";

/** 行 → 契约 `ToolPermissionResponse`。 */
function toToolPermissionResponse(row: ResourcePermissionRow): ToolPermissionResponseBody {
  return {
    id: row.id,
    // `resource_id` 为 NULL 的行是「类型级」授权（对全部工具生效），而契约的 `tool_id`
    // 是必填字符串 —— 无法表达「全部」。故 list 只返回实例级行（见文件头注与施工记录 L-2）。
    tool_id: row.resource_id ?? "",
    action: row.action,
    effect: row.effect,
    agent_id: row.subject_type === "agent" ? row.subject_id : null,
    // `resource_permission` **没有** agent_version_id 列（契约有该字段）⇒ 恒 null，
    // 不为此改 DDL（J-1 红线）。登记为遗留。
    agent_version_id: null,
    scope: (row.scope ?? {}) as Record<string, unknown>,
    tenant_id: row.tenant_id ?? null,
    created_at: toIsoOrNull(row.created_at),
  };
}

/** 时间 → `string | null`（SQLite 文本 / PG Date 双形，统一 ISO）。 */
function toIsoOrNull(value: unknown): string | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString();
  if (typeof value !== "string" || value.trim() === "") return null;
  const text = value.trim();
  const shape = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(text);
  if (shape) {
    const [, y, mo, d, h, mi, s, ms] = shape;
    return new Date(
      Date.UTC(
        Number(y),
        Number(mo) - 1,
        Number(d),
        Number(h),
        Number(mi),
        Number(s),
        ms === undefined ? 0 : Number(ms.padEnd(3, "0"))
      )
    ).toISOString();
  }
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? null : new Date(parsed).toISOString();
}

/**
 * 注册权限族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖。
 */
export function permissionRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // ⑪ GET /permissions/check?cap=... —— 200（**无码也是 200**，J-6a）
  app.get(
    "/api/v1/permissions/check",
    { preValidation: authenticate(deps), schema: { querystring: CheckQuerySchema } },
    async (request) => {
    const context = contextOf(request);
    const capability = requiredQuery((request.query as Record<string, unknown>).cap, "cap");
    const decision = checkCapability(context.principal, capability);
    const body: PermissionCheckResponseBody = {
      capability: decision.capability,
      allowed: decision.allowed,
      effect: decision.effect,
      reason: decision.reason,
      // `source` 是判定结果的一部分（R-29）：`default_deny` / `explicit_grant` /
      // `wildcard_admin` 三态由 `decideCapability()` 产出，必须**原样透传**。
      // 这里曾经硬编码 `null`（理由是"本版没有外部权限源"）—— 那条注释把
      // "丢弃判定结果"写成了设计：`null` 既不表示"没有外部源"，也让调用方无法区分
      // "默认拒绝"与"通配管理员放行"，与 py oracle 实测值
      // （`"source":"default_deny"`，见 T2-11-oracle.md §3-1）当场不一致。
      // 契约 `PermissionCheckResponse.source` 是 `string | null`，透传三态在契约内。
      source: decision.source,
    };
    return body;
  });

  // ⑫ GET /tools/permissions?agent_id=... —— 200
  app.get(
    "/api/v1/tools/permissions",
    { preValidation: authenticate(deps), schema: { querystring: ListToolPermissionsQuerySchema } },
    async (request) => {
    const context = contextOf(request);
    const agentId = requiredQuery((request.query as Record<string, unknown>).agent_id, "agent_id");
    const repo = new ResourcePermissionRepo(deps.db, context.scope, deps.dialect);
    const rows = await repo.listBySubject("agent", agentId, RESOURCE_TYPE_TOOL, { limit: 500 });
    // 只返回实例级行（`resource_id` 非空）：契约的 `tool_id` 必填，类型级授权无法表达。
    return rows.filter((row) => row.resource_id !== null).map(toToolPermissionResponse);
  });

  // ⑬ POST /tools/permissions —— 201
  app.post(
    "/api/v1/tools/permissions",
    { preValidation: authenticate(deps), schema: { body: ToolPermissionRequestSchema } },
    async (request, reply) => {
      const context = contextOf(request);
      const body = request.body as ToolPermissionRequestBody;
      const repo = new ResourcePermissionRepo(deps.db, context.scope, deps.dialect);

      // 主体：给了 agent_id 就记在 agent 名下；否则记在当前用户名下
      // （契约里 agent_id 可空，而 `subject_id` 是 NOT NULL）。
      const subjectType = typeof body.agent_id === "string" && body.agent_id !== "" ? "agent" : "user";
      const subjectId = subjectType === "agent" ? (body.agent_id as string) : context.user.id;
      const action = body.action ?? "EXECUTE";
      const effect = body.effect ?? "ALLOW";

      // 唯一约束 `uq_resource_permission_subject_resource_action` 的存在性预检：
      // 直接插会在数据库层抛唯一冲突 → 统一错误出口只能给 500。这里先查，给 409。
      const existing = await repo.listBySubject(subjectType, subjectId, RESOURCE_TYPE_TOOL, {
        limit: 500,
      });
      const duplicated = existing.some(
        (row) => row.resource_id === body.tool_id && row.action === action
      );
      if (duplicated) {
        throw authError(ERROR_CODES.CONFLICT, "该主体对该工具的动作授权已存在", {
          subject_type: subjectType,
          subject_id: subjectId,
          tool_id: body.tool_id,
          action,
        });
      }

      const now = new Date();
      const stamp = instantLiteral(deps.dialect, now) as unknown as Date;
      const created = await repo.create({
        // `TenantScopedInsert` 是 `Omit<行, "tenant_id">`，而 drizzle 把有默认值的列也
        // 标成必需 ⇒ id / created_at / updated_at 必须显式给（同 T2-04 的处理）。
        id: randomUUID(),
        subject_type: subjectType,
        subject_id: subjectId,
        resource_type: RESOURCE_TYPE_TOOL,
        resource_id: body.tool_id,
        action,
        effect,
        scope: body.scope ?? {},
        created_at: stamp,
        updated_at: stamp,
      });
      reply.code(201);
      return toToolPermissionResponse(created);
    }
  );

  // ⑭ DELETE /tools/permissions/{permission_id} —— **204 零字节体**（J-10）
  app.delete(
    "/api/v1/tools/permissions/:permission_id",
    { preValidation: authenticate(deps) },
    async (request, reply) => {
    const context = contextOf(request);
    const permissionId = requiredParam(request.params, "permission_id");
    const repo = new ResourcePermissionRepo(deps.db, context.scope, deps.dialect);
    const removed = await repo.remove(context.scope.ref(permissionId));
    if (!removed) {
      // 不存在与跨租户同码（404 `NOT_FOUND`）：不区分，否则 404/403 的差异会泄露
      // "别的租户有这条记录"。这也是 J-7 第 4 族的判据。
      throw authError(ERROR_CODES.NOT_FOUND, "权限记录不存在", { permission_id: permissionId });
    }
    // 204：**不** `return` 任何对象（Fastify 会发 `null` 体）。见 J-10。
    reply.code(204).send();
  });
}
