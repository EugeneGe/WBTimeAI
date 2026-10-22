/**
 * T2-07 · 路由层的公共支撑：**依赖容器 + Bearer 解析 + 主体装配**。
 *
 * 为什么单独一个文件：19 个 op 里有 15 个要求认证，若每个 handler 各写一遍
 * "取 header → 解令牌 → 查用户 → 装 Principal"，那 15 份就必须靠 code review 保证一致
 * —— 而"某一份忘了校验 type"这种偏差只能靠攻击者发现。这里只写一次。
 *
 * 分层：本文件是 **Router 层**（计划 §4.3）。它做认证与主体装配，**不判权限码**：
 * V0.2.0 的 4 族 19 op **一条都没有** `requirePermission`（J-6b 反例红线，依据 py 线
 * 4 族 router 实测只有 `CurrentUser`）。`Principal` 照样装配，是因为
 * `GET /permissions/check` **需要它来回答**"我有没有 X 权限" —— 那是查询，不是守卫。
 */

import { ERROR_CODES } from "@wbtime/core";
import {
  MembershipRepo,
  RolePermissionCatalog,
  Scope,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";
import type { FastifyRequest } from "fastify";

import { AuthService, type AuthUser } from "../modules/auth/service.js";
import { authError, unauthorized } from "../modules/auth/errors.js";
import { AgentService } from "../modules/agent/service.js";
import { ApprovalService } from "../modules/approval/service.js";
import { ConversationService } from "../modules/conversation/service.js";
import { CredentialService } from "../modules/credential/service.js";
import { ModelProviderService } from "../modules/model/provider-service.js";
import { OrganizationService } from "../modules/organization/service.js";
import { RunService } from "../modules/run/run-service.js";
import { SkillService } from "../modules/skill/service.js";
import { ToolService } from "../modules/tool/service.js";
import {
  loadPrincipal,
  type Principal,
  type PermissionResolverDeps,
} from "../modules/rbac/index.js";
import type { RegisterLimiter } from "../modules/auth/register-limiter.js";

/** 身份族路由需要的全部依赖（`app.ts` 装配一次，注入给 5 个路由文件）。 */
export interface IdentityDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  /** 默认租户（由装配方给出：配置 / bootstrap；服务层不"猜"）。 */
  readonly tenantId: string;
  readonly auth: AuthService;
  readonly organizations: OrganizationService;
  readonly credentials: CredentialService;
  /**
   * Agent 族服务（T3-05 · 7 op）。
   *
   * 为什么挂在 IdentityDeps 而不是另立容器：它的依赖（db / dialect / tenantId）
   * 与身份族完全同源，而 `buildApp` 的装配入口只有一个 —— 多一个容器就会多一条
   * "两次装配各拿一份依赖"的漂移路径。名字沿用 `deps.agents`（复数，与路由文件
   * `agentRoutes(app, deps)` 的读取面一致）。
   */
  readonly agents: AgentService;
  /**
   * Skill 族服务（T3-06 · 7 op + `resolveSkill` 纯查询）。
   *
   * 挂载理由与 `agents` 同源：依赖（db / dialect / tenantId）与身份族完全同源，
   * `buildApp` 的装配入口只有一个。名字沿用 `deps.skills`（复数，与
   * `skillRoutes(app, deps)` 的读取面一致）。
   */
  readonly skills: SkillService;
  /**
   * Conversation 族服务（T3-07 · 5 op + 消息写入的服务层入口）。
   *
   * 挂载理由与 `agents` / `skills` 同源：依赖（db / dialect / tenantId）与身份族完全同源，
   * `buildApp` 的装配入口只有一个。名字沿用 `deps.conversations`（复数，与
   * `conversationRoutes(app, deps)` 的读取面一致）。
   */
  readonly conversations: ConversationService;
  /**
   * 审批族服务（T3-12 · 4 op）。
   *
   * 挂载理由与 `agents` / `skills` / `conversations` 同源：依赖（db / dialect）与身份族
   * 完全同源，`buildApp` 的装配入口只有一个。**决议不触发执行** —— 执行在 T3-08 的
   * 恢复路径，本服务只落状态与时间戳。
   */
  readonly approvals: ApprovalService;
  /**
   * 模型目录服务（T3-12 · 6 op：供应商目录 4 + 模型目录 2）。
   *
   * 与 `credentials`（凭证族 5 op，T2-07）**分开两个服务**：凭证关心密文与掩码，
   * 目录关心标签与层级；混成一个类会让"解密只在保存时发生"这条不变量难以审计。
   */
  readonly providers: ModelProviderService;
  /**
   * 工具目录服务（T3-12 · 1 op）。
   *
   * `list` 内含**幂等物化**（R3-23）：`tool_permission.tool_id` 是 FK，权限要引用工具
   * 就必须先有行与稳定 id ⇒ 不能只返回内存注册表。
   */
  readonly tools: ToolService;
  /**
   * runs 服务（T3-08 · 3 op：详情 / 取消 / SSE 事件流）。
   *
   * 与其他族同源装配；`cancel` 与终态判定都经 `RunCoordinator`（CAS 只有一处）。
   * **本服务不执行 run** —— run 的创建由 `POST /agents/{id}/run` 的入口回执负责。
   */
  readonly runs: RunService;
  /**
   * 未认证 register 的限速器（FIX-04）。
   *
   * **必须是每个 app 实例一份**（由 `buildIdentityStack` 在装配期构造）：
   * 模块级单例会让并发跑的两组测试夹具互相消耗配额，产生间歇性失败。
   * 它是依赖而不是模块常量，正是为了这一点。
   */
  readonly registerLimiter: RegisterLimiter;
}

/** 一次已认证请求的上下文（用户 + 主体）。 */
export interface RequestContext {
  readonly user: AuthUser;
  readonly principal: Principal;
  /** 主体所在的 scope（`tenantId` 来自令牌声明，缺省回落默认租户）。 */
  readonly scope: Scope;
}

/**
 * 从 `Authorization: Bearer <token>` 取令牌。
 *
 * 只接受大小写不敏感的 `Bearer` 方案（RFC 6750 里方案名不区分大小写，但**必须**有
 * 一个空格分隔）；缺少 / 空值一律 401 `UNAUTHORIZED`（契约的 `HTTPBearer` 语义）。
 *
 * @param request Fastify 请求。
 * @returns 令牌串。
 * @throws {HttpException} 缺失或格式非法（401 `UNAUTHORIZED`）。
 */
export function bearerToken(request: FastifyRequest): string {
  const raw = request.headers.authorization;
  if (typeof raw !== "string" || raw.trim() === "") {
    throw unauthorized("缺少访问令牌");
  }
  const match = /^Bearer[ ]+(.+)$/i.exec(raw.trim());
  if (match === null || match[1].trim() === "") {
    throw unauthorized("Authorization 头必须是 `Bearer <token>`");
  }
  return match[1].trim();
}

/**
 * 认证**必须早于入参校验**（`preValidation`），否则会出现两种坏结果：
 *
 * 1. 未认证请求带非法 body ⇒ 先被 schema 挡成 **422**，于是"有没有令牌"这件事
 *    在 422 的 `data.errors` 里被绕开 —— 而 §5.1 的第一条边界是"未认证 ⇒ 401"；
 * 2. 每个 handler 各写一遍认证 ⇒ 15 份必须靠 review 保证一致。
 *
 * 所以认证做成 `preValidation` 钩子：401 先出，校验随后；handler 只从
 * {@link contextOf} 取已装好的上下文，不再自己认证。
 */
const CONTEXT = new WeakMap<FastifyRequest, RequestContext>();

/**
 * 造一个 `preValidation` 钩子：认证并把上下文挂到本次请求上。
 *
 * @param deps 依赖容器。
 * @returns Fastify `preValidation` 处理器。
 */
export function authenticate(
  deps: IdentityDeps
): (request: FastifyRequest) => Promise<void> {
  return async (request: FastifyRequest): Promise<void> => {
    CONTEXT.set(request, await buildRequestContext(deps, request));
  };
}

/**
 * 取本次请求的认证上下文（由 {@link authenticate} 钩子写入）。
 *
 * @param request Fastify 请求。
 * @returns 已认证的用户 + 主体 + scope。
 * @throws {Error} 路由忘了挂 `preValidation` 钩子（**编程错误**，不是用户错误）。
 */
export function contextOf(request: FastifyRequest): RequestContext {
  const context = CONTEXT.get(request);
  if (context === undefined) {
    throw new Error("路由未挂 `preValidation: authenticate(deps)` —— 拿不到认证上下文");
  }
  return context;
}

/**
 * 认证请求并装配主体（**唯一的认证实现**）。
 *
 * `AuthService.authenticate` 只做「解码 + 用户存在 + `is_active`」——
 * **不查** `session.revoked_at`（access 无状态，计划 §3.2 / R-7 / U-1）。
 *
 * @param deps 依赖容器。
 * @param request Fastify 请求。
 * @returns 用户 + 主体 + scope。
 * @throws {HttpException} 401（缺令牌 / 令牌非法 / 过期 / 用户不可用）。
 */
export async function buildRequestContext(
  deps: IdentityDeps,
  request: FastifyRequest
): Promise<RequestContext> {
  const token = bearerToken(request);
  const user = await deps.auth.authenticate(token);
  const tenantId = user.tenantId ?? deps.tenantId;
  const scope = new Scope(tenantId);
  const resolverDeps: PermissionResolverDeps = {
    memberships: new MembershipRepo(deps.db, scope, deps.dialect),
    rolePermissions: new RolePermissionCatalog(deps.db, deps.dialect),
  };
  const principal = await loadPrincipal(resolverDeps, {
    userRef: scope.ref(user.id),
    userId: user.id,
    tenantId,
  });
  return { user, principal, scope };
}

/**
 * 把查询参数里的单值取出来（Fastify 的 query 值可能是数组）。
 *
 * @param value 原始值。
 * @returns 字符串，或 `undefined`。
 */
export function singleQueryValue(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return undefined;
}

/**
 * 必填查询参数。
 *
 * @param value 原始值。
 * @param name 参数名（写进错误 `data`，便于前端定位）。
 * @returns 非空字符串。
 * @throws {HttpException} 缺失 / 空串（422 `VALIDATION_ERROR`）。
 */
export function requiredQuery(value: unknown, name: string): string {
  const single = singleQueryValue(value);
  if (single === undefined || single.trim() === "") {
    // 契约把 `/permissions/check?cap=` 与 `/tools/permissions?agent_id=` 标为 required；
    // 缺失走 422（校验失败）而不是 400 —— 与本项目"校验错误恒 422"的既有出口一致。
    throw authError(ERROR_CODES.VALIDATION_ERROR, `缺少必需查询参数：${name}`, { field: name });
  }
  return single;
}

/** 路径参数（Fastify 已按路由模板解析，这里只做非空断言）。 */
export function requiredParam(params: unknown, name: string): string {
  const bag = (params ?? {}) as Record<string, unknown>;
  const value = bag[name];
  if (typeof value !== "string" || value.trim() === "") {
    throw authError(ERROR_CODES.VALIDATION_ERROR, `缺少路径参数：${name}`, { field: name });
  }
  return value;
}
