/**
 * T2-07 · 认证族 4 个 op（§1 表 1–4）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 1 | POST `/api/v1/auth/register` | 201 |
 * | 2 | POST `/api/v1/auth/login` | 200 |
 * | 3 | POST `/api/v1/auth/refresh` | 200 |
 * | 4 | POST `/api/v1/auth/logout` | 200 |
 *
 * 前三个**不需要** Bearer（契约里它们的 `security` 是 `undefined`，实测确认）；
 * `logout` 需要（`[{HTTPBearer: []}]`）。
 *
 * 路由只做三件事：**校验入参（schema）→ 调 service → 返回裸业务对象**。
 * 不拼壳（壳在 `http/envelope.ts`）、不加工错误（错误在 `http/error-handler.ts`）。
 *
 * 唯一的**前置判定**是 `register` 的未认证限速（FIX-04）：那是路由层职责（要 `request.ip`、
 * 要 `Retry-After` 头），且必须早于 service（service 第一件事就是 64MiB 的 argon2id）。
 */

import { ERROR_CODES } from "@wbtime/core";
import type { FastifyInstance, FastifyRequest } from "fastify";

import {
  LoginRequestSchema,
  RefreshRequestSchema,
  RegisterRequestSchema,
  type LoginRequestBody,
  type RefreshRequestBody,
  type RegisterRequestBody,
} from "./schemas.js";
import { authenticate, bearerToken, type IdentityDeps } from "./support.js";
import { authError } from "../modules/auth/errors.js";
import type { DeviceContext } from "../modules/auth/service.js";

/** 从请求里取设备上下文（契约 `DeviceResponse` 的字段来源）。 */
function deviceContext(request: FastifyRequest): DeviceContext {
  const userAgent = request.headers["user-agent"];
  return {
    device: typeof userAgent === "string" ? userAgent.slice(0, 255) : null,
    ipAddress: request.ip ?? null,
    userAgent: typeof userAgent === "string" ? userAgent.slice(0, 512) : null,
  };
}

/**
 * 注册认证族路由。
 *
 * @param app Fastify 实例（须在响应壳中间件之后装配）。
 * @param deps 身份族依赖。
 */
export function authRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // ① POST /auth/register —— 201
  app.post(
    "/api/v1/auth/register",
    { schema: { body: RegisterRequestSchema } },
    async (request, reply) => {
      // FIX-04 / R-34：未认证限速必须在 `deps.auth.register`（内部第一件事就是 argon2id）
      // **之前**。放在之后等于没省一次 CPU —— 防护的全部价值就在"拒绝时不跑哈希"。
      // 计数依据是 `request.ip`（socket 对端地址），**不读** `X-Forwarded-For`：
      // 本版未定代理形态（`trustProxy` 未开），信任该头等于让攻击者自造无限个 IP。
      const decision = deps.registerLimiter.check(request.ip);
      if (!decision.allowed) {
        // 头先设、错后抛：统一错误出口只负责状态码 + 四键壳，不会清掉已设的响应头。
        reply.header("Retry-After", String(decision.retryAfterSeconds));
        throw authError(
          ERROR_CODES.RESOURCE_LIMIT_EXCEEDED,
          `注册请求过于频繁，请 ${decision.retryAfterSeconds} 秒后重试`,
          {
            retry_after_seconds: decision.retryAfterSeconds,
            limit_per_minute: deps.registerLimiter.limitPerMinute,
          }
        );
      }

      const body = request.body as RegisterRequestBody;
      const context = deviceContext(request);
      const result = await deps.auth.register({
        username: body.username,
        email: body.email,
        password: body.password,
        displayName: body.display_name ?? null,
        ...context,
      });
      // 契约 `TokenResponse`；注册也直接登录（py 线同语义），故回令牌而不是用户对象。
      reply.code(201);
      return result.tokens;
    }
  );

  // ② POST /auth/login —— 200
  app.post(
    "/api/v1/auth/login",
    { schema: { body: LoginRequestSchema } },
    async (request) => {
      const body = request.body as LoginRequestBody;
      const result = await deps.auth.login({
        username: body.username,
        password: body.password,
        ...deviceContext(request),
      });
      return result.tokens;
    }
  );

  // ③ POST /auth/refresh —— 200（轮换：旧会话撤销 + 新会话）
  app.post(
    "/api/v1/auth/refresh",
    { schema: { body: RefreshRequestSchema } },
    async (request) => {
      const body = request.body as RefreshRequestBody;
      const result = await deps.auth.refresh(body.refresh_token, deviceContext(request));
      return result.tokens;
    }
  );

  // ④ POST /auth/logout —— 200（幂等；同一 access 连打两次都成功）
  app.post("/api/v1/auth/logout", { preValidation: authenticate(deps) }, async (request) => {
    // 令牌自己解（不查 session）—— T2-04 的 `logout` 就是这么实现的，
    // 这里传原串而不是 User，正是为了保留"解码不查 session"的语义。
    await deps.auth.logout(bearerToken(request));
    return { message: "已退出登录" };
  });
}
