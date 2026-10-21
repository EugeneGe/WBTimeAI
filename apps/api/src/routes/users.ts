/**
 * T2-07 · 用户族 4 个 op（§1 表 5–8）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 5 | GET `/api/v1/users/me` | 200 |
 * | 6 | PUT `/api/v1/users/me` | 200 |
 * | 7 | GET `/api/v1/users/me/devices` | 200 |
 * | 8 | POST `/api/v1/users/me/logout-all` | 200 |
 *
 * `UserResponse` 比认证上下文（`AuthUser`）多三列（`is_active` / `is_superuser` /
 * `created_at`），`DeviceResponse` 又比 `AuthService.listDevices()` 的视图多 `created_at`
 * —— 所以这两个 op **直接读仓储行**，而不是拿中间对象凑字段。多一次按主键的 scope 内
 * 查询，换的是"响应字段真来自库"。**不**为了少写几行去改 T2-04 的对外视图（那是别人的
 * 已完成面，且视图变宽会把 `password_hash` 之类的东西带出去的风险抬高）。
 */

import type { FastifyInstance } from "fastify";

import { SessionRepo, UserRepo, type SessionRow, type UserRow } from "@wbtime/db";

import { unauthorized } from "../modules/auth/errors.js";
import {
  UpdateUserRequestSchema,
  type DeviceResponseBody,
  type UpdateUserRequestBody,
  type UserResponseBody,
} from "./schemas.js";
import { authenticate, bearerToken, contextOf, type IdentityDeps } from "./support.js";

/** 行 → 契约 `UserResponse`（键集合逐字对齐；**不含** `password_hash`）。 */
function toUserResponse(row: UserRow): UserResponseBody {
  return {
    id: row.id,
    username: row.username,
    email: row.email,
    display_name: row.display_name ?? null,
    tenant_id: row.tenant_id ?? null,
    is_active: row.is_active === true,
    is_superuser: row.is_superuser === true,
    created_at: toIsoOrNull(row.created_at),
  };
}

/** 行 → 契约 `DeviceResponse`（7 键；含已撤销行）。 */
function toDeviceResponse(row: SessionRow): DeviceResponseBody {
  return {
    id: row.id,
    device: row.device ?? null,
    ip_address: row.ip_address ?? null,
    user_agent: row.user_agent ?? null,
    created_at: toIsoOrNull(row.created_at),
    expires_at: toIsoOrNull(row.expires_at),
    revoked_at: toIsoOrNull(row.revoked_at),
  };
}

/**
 * 时间 → 契约要求的 `string | null`。
 *
 * 两种形状都要认：PG 档是 `Date`，SQLite 档是 `YYYY-MM-DD HH:MM:SS`（空格分隔、UTC）。
 * 统一输出 ISO-8601 —— 否则同一接口在两种部署档下时间形状不同，前端得写两套解析。
 */
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
 * 注册用户族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖。
 */
export function userRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // ⑤ GET /users/me —— 200
  app.get("/api/v1/users/me", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    const repo = new UserRepo(deps.db, context.scope, deps.dialect);
    const row = await repo.findById(context.scope.ref(context.user.id));
    if (row === null) {
      // 令牌有效但用户行不可见 ⇒ 认证主体已失效：401（不是 404 —— 404 会变成
      // "这个 id 存不存在"的探针，而这里的主语是调用者自己）。
      throw unauthorized("用户不存在");
    }
    return toUserResponse(row);
  });

  // ⑥ PUT /users/me —— 200（当前唯一可改字段 `display_name`，可显式置 null 清空）
  app.put(
    "/api/v1/users/me",
    { preValidation: authenticate(deps), schema: { body: UpdateUserRequestSchema } },
    async (request) => {
    const context = contextOf(request);
    const body = request.body as UpdateUserRequestBody;
    const repo = new UserRepo(deps.db, context.scope, deps.dialect);
    const ref = context.scope.ref(context.user.id);
    const updated =
      body.display_name === undefined
        ? await repo.findById(ref)
        : await repo.update(ref, { display_name: body.display_name });
    if (updated === null) throw unauthorized("用户不存在");
    return toUserResponse(updated);
  });

  // ⑦ GET /users/me/devices —— 200（含已撤销行：`DeviceResponse.revoked_at` 必须可见）
  app.get("/api/v1/users/me/devices", { preValidation: authenticate(deps) }, async (request) => {
    const context = contextOf(request);
    const sessions = new SessionRepo(deps.db, context.scope, deps.dialect);
    const rows = await sessions.listByUser(context.scope.ref(context.user.id), { limit: 500 });
    return rows.map(toDeviceResponse);
  });

  // ⑧ POST /users/me/logout-all —— 200（撤销全部会话；契约不回撤销数量）
  app.post("/api/v1/users/me/logout-all", { preValidation: authenticate(deps) }, async (request) => {
    // 认证由 `preValidation` 钩子完成（401 先于校验）；这里直接交给 T2-04 撤销。
    await deps.auth.logoutAll(bearerToken(request));
    return { message: "已退出全部设备" };
  });
}
