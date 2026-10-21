/**
 * T2-04 · 认证服务（注册 / 登录 / 刷新 / 登出 / 鉴权）。
 *
 * 分层：**只做服务层**。HTTP 路由（`/api/v1/auth/*`、`/users/me/*`）归 T2-07，
 * 它调用本类；本文件不 import fastify、不碰 request/reply。
 *
 * 与 py 线的对应关系（`application/services/auth_service.py`）
 * ---------------------------------------------------------
 * | 方法 | py | 差异 |
 * |---|---|---|
 * | `register` | `register()` | **未**自动授 `admin` 角色 / 建默认组织成员关系 —— 那依赖 T2-05 的 RBAC 种子，本版无种子就不该伪造（登记为遗留 L-1） |
 * | `login` | `login()` | 增加「租户 `is_active=false` ⇒ 401」前置（计划 §2 明确要求），其余顺序逐条一致 |
 * | `refresh` | `refresh()` | 同（撤销旧会话 → 建新会话 + 新令牌对） |
 * | `logout` | `logout()` | 同（解码不查 session ⇒ 同一 access 连打 2 次均 200） |
 * | `logoutAll` | `logout_all()` | 同（契约回 `{message}`，不回数量） |
 * | `authenticate` | `authenticate()` | 同（**不查** `session.revoked_at`，access 无状态） |
 *
 * 租户从哪来
 * ----------
 * py 用 `tenants.ensure_default()`（单租户部署假设），那是一次**无作用域**的表扫描。
 * TS 侧不复制它：租户 id 由装配方（配置 / bootstrap）给出，`TenantRepo` 只按 scope
 * 校验它存在且启用 —— 这样 `tenant` 不会被悄悄扩成第 4 张 unscoped 表（T2-03 D-1）。
 */

import { randomUUID } from "node:crypto";

import {
  LoginAttemptSink,
  Scope,
  TenantRepo,
  UserRepo,
  type DrizzleDatabase,
  type SessionRow,
  type SqlDialect,
  type UserRow,
} from "@wbtime/db";
import { assertAcceptablePassword, invariant } from "@wbtime/domain";

import { invalidCredentials, tokenRevoked, unauthorized, userAlreadyExists } from "./errors.js";
import { ACCESS_TTL_SECONDS, TokenService, type TokenClaims } from "./jwt.js";
import { LoginGuard, type LoginGuardOptions } from "./login-guard.js";
import { PasswordHasher } from "./password.js";
import { SessionTokenService, auditStamps } from "./refresh.js";

/** 认证上下文里的用户视图（**不含** `password_hash` —— 它不该离开仓储之外的任何地方）。 */
export interface AuthUser {
  readonly id: string;
  readonly tenantId: string | null;
  readonly username: string;
  readonly email: string;
  readonly displayName: string | null;
}

/**
 * 令牌响应（契约 `TokenResponse`）：**恒出四键**。
 *
 * `expires_in` 取 access TTL（900），`token_type` 恒 `"bearer"`。
 * 字段名是 snake_case —— 它直接进响应壳的 `data`，改驼峰会破 J-11 的键集合比对。
 */
export interface TokenResponse {
  readonly access_token: string;
  readonly refresh_token: string;
  readonly token_type: "bearer";
  readonly expires_in: number;
}

/** 一次认证成功的结果。 */
export interface AuthResult {
  readonly user: AuthUser;
  readonly tokens: TokenResponse;
}

/** 注册入参。 */
export interface RegisterInput {
  readonly username: string;
  readonly email: string;
  readonly password: string;
  readonly displayName?: string | null;
  readonly device?: string | null;
  readonly ipAddress?: string | null;
  readonly userAgent?: string | null;
}

/** 登录入参。 */
export interface LoginInput {
  readonly username: string;
  readonly password: string;
  readonly device?: string | null;
  readonly ipAddress?: string | null;
  readonly userAgent?: string | null;
}

/** 刷新 / 登录时的设备上下文。 */
export interface DeviceContext {
  readonly device?: string | null;
  readonly ipAddress?: string | null;
  readonly userAgent?: string | null;
}

/** 设备会话视图（`GET /users/me/devices` 的数据面）。 */
export interface DeviceView {
  readonly id: string;
  readonly device: string | null;
  readonly ipAddress: string | null;
  readonly userAgent: string | null;
  readonly expiresAt: Date | string;
  readonly revokedAt: Date | string | null;
}

/** 装配认证服务所需的依赖。 */
export interface AuthServiceDeps extends LoginGuardOptions {
  /** drizzle 句柄（`createSqliteDb` / `createPgDb` 的产物）。 */
  readonly db: DrizzleDatabase;
  /** 方言（缺省 `pg`；测试传 `sqlite`）。 */
  readonly dialect?: SqlDialect;
  /** 默认租户 id（由配置 / bootstrap 给出，不在服务里"猜"）。 */
  readonly tenantId: string;
  /** 主密钥（`requireSecretKey(config)` 的产物）。 */
  readonly secretKey: string;
  /** 令牌服务（可注入以便测试用固定时钟）。 */
  readonly tokens?: TokenService;
  /** 口令哈希器（可注入）。 */
  readonly hasher?: PasswordHasher;
  /** 会话 TTL（秒）。 */
  readonly sessionTtlSeconds?: number;
  /** 时钟（测试可注入）。 */
  readonly now?: () => Date;
}

/** 认证服务。 */
export class AuthService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;
  readonly #tokens: TokenService;
  readonly #hasher: PasswordHasher;
  readonly #sessions: SessionTokenService;
  readonly #guard: LoginGuard;
  readonly #now: () => Date;

  constructor(deps: AuthServiceDeps) {
    invariant(typeof deps.tenantId === "string" && deps.tenantId !== "", "AuthService 需要非空 tenantId");
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#tenantId = deps.tenantId;
    this.#now = deps.now ?? (() => new Date());
    this.#hasher = deps.hasher ?? new PasswordHasher();
    this.#tokens =
      deps.tokens ??
      new TokenService(deps.secretKey, {
        ...(deps.now ? { now: deps.now } : {}),
      });
    this.#sessions = new SessionTokenService({
      db: this.#db,
      tokens: this.#tokens,
      dialect: this.#dialect,
      ...(deps.sessionTtlSeconds === undefined ? {} : { sessionTtlSeconds: deps.sessionTtlSeconds }),
      ...(deps.now ? { now: deps.now } : {}),
    });
    this.#guard = new LoginGuard({
      sink: new LoginAttemptSink(this.#db, this.#dialect),
      ...(deps.maxAttempts === undefined ? {} : { maxAttempts: deps.maxAttempts }),
      ...(deps.lockSeconds === undefined ? {} : { lockSeconds: deps.lockSeconds }),
      ...(deps.now ? { now: deps.now } : {}),
    });
  }

  /** 默认租户 id（T2-07 的路由在需要时读它，避免各处重复取配置）。 */
  get tenantId(): string {
    return this.#tenantId;
  }

  /** 登录守卫（路由层若要单独查锁定状态可用）。 */
  get loginGuard(): LoginGuard {
    return this.#guard;
  }

  // -------------------------------------------------------------------------
  // 注册
  // -------------------------------------------------------------------------

  /**
   * 注册并自动登录。
   *
   * 顺序：口令策略 → 字段非空 → 租户启用 → 重名/重邮箱 → 建档 → 签发令牌。
   * 口令策略在**最前面**：一个不合格的口令不该先花 200ms 做 argon2 再被拒。
   *
   * @param input 注册入参。
   * @throws {DomainError} 口令不满足策略（`VALIDATION_ERROR` → 422）。
   * @throws {HttpException} 用户名/邮箱已存在（409）、租户已停用（401）。
   */
  async register(input: RegisterInput): Promise<AuthResult> {
    assertAcceptablePassword(input.password);
    invariant(typeof input.username === "string" && input.username.trim() !== "", "用户名不能为空", {
      field: "username",
    });
    invariant(typeof input.email === "string" && input.email.trim() !== "", "邮箱不能为空", {
      field: "email",
    });

    await this.#assertTenantActive();

    const scope = this.#scope();
    const users = new UserRepo(this.#db, scope, this.#dialect);
    if ((await users.findByUsername(input.username)) !== null) {
      throw userAlreadyExists("username", input.username);
    }
    if ((await users.findByEmail(input.email)) !== null) {
      throw userAlreadyExists("email", input.email);
    }

    const passwordHash = await this.#hasher.hash(input.password);
    const created = await users.create({
      id: randomUUID(),
      username: input.username,
      email: input.email,
      password_hash: passwordHash,
      display_name: input.displayName ?? null,
      is_active: true,
      is_superuser: false,
      ...auditStamps(this.#dialect, this.#now()),
    });

    const tokens = await this.#sessions.issueTokens({
      tenantId: this.#tenantId,
      userId: created.id,
      device: input.device ?? null,
      ipAddress: input.ipAddress ?? null,
      userAgent: input.userAgent ?? null,
    });

    return { user: toAuthUser(created), tokens: this.#tokenResponse(tokens) };
  }

  // -------------------------------------------------------------------------
  // 登录
  // -------------------------------------------------------------------------

  /**
   * 登录（含连续失败锁定）。
   *
   * 顺序**严格**照 py：① 租户启用；② 锁定检查（先于用户查询 —— 否则锁定状态会被
   * "这个用户名到底存不存在"的响应时间差泄露）；③ 查用户；④ 校验口令；
   * ⑤ 失败则落库并抛 401；⑥ `is_active` 检查；⑦ 成功落库（打断计数）→ 签发。
   *
   * @param input 登录入参。
   * @throws {HttpException} 锁定（423）、凭据无效 / 账号停用 / 租户停用（均 401）。
   */
  async login(input: LoginInput): Promise<AuthResult> {
    invariant(typeof input.username === "string" && input.username.trim() !== "", "用户名不能为空", {
      field: "username",
    });
    invariant(typeof input.password === "string" && input.password !== "", "口令不能为空", {
      field: "password",
    });

    await this.#assertTenantActive();
    await this.#guard.assertNotLocked(input.username);

    const scope = this.#scope();
    const users = new UserRepo(this.#db, scope, this.#dialect);
    const user = await users.findByUsername(input.username);

    const passwordOk =
      user === null ? false : await this.#hasher.verify(input.password, user.password_hash);

    if (user === null || !passwordOk) {
      // 失败也落库（限速的唯一数据来源）；文案与码不区分"用户不存在"与"口令错"。
      await this.#guard.registerFailure({
        username: input.username,
        tenantId: this.#tenantId,
        ipAddress: input.ipAddress ?? null,
      });
      throw invalidCredentials();
    }

    if (user.is_active !== true) {
      // py：停用账号同样回 INVALID_CREDENTIALS（不是 403），避免"这个号存在但被停用"泄露。
      await this.#guard.registerFailure({
        username: input.username,
        tenantId: this.#tenantId,
        ipAddress: input.ipAddress ?? null,
      });
      throw invalidCredentials();
    }

    await this.#guard.registerSuccess({
      username: input.username,
      tenantId: this.#tenantId,
      ipAddress: input.ipAddress ?? null,
    });

    const tokens = await this.#sessions.issueTokens({
      tenantId: this.#tenantId,
      userId: user.id,
      device: input.device ?? null,
      ipAddress: input.ipAddress ?? null,
      userAgent: input.userAgent ?? null,
    });

    return { user: toAuthUser(user), tokens: this.#tokenResponse(tokens) };
  }

  // -------------------------------------------------------------------------
  // 刷新 / 登出
  // -------------------------------------------------------------------------

  /**
   * 用 refresh token 换一对新令牌（**轮换**）。
   *
   * 轮换 = 认领旧 refresh（连带撤销旧会话及其全部 refresh）→ 建新会话 + 新令牌对。
   * ⇒ 旧 refresh 的二次使用必然 `AUTH_TOKEN_REVOKED`（J-4 的正面判据）。
   *
   * 为什么要"认领"而不是"校验后撤销"（FIX-24 / TOCTOU）
   * ----------------------------------------------
   * `authenticateRefresh` 与撤销之间隔着若干 `await`，两个并发请求可能**都**通过校验。
   * `claimForRotation` 以 `UPDATE ... WHERE revoked_at IS NULL` 的 affected rows 为准：
   * 抢不到行的那一次**不签发**，抛 `AUTH_TOKEN_REVOKED`。若不这样做，同一个 refresh
   * 并发两次会换出两对长期有效的令牌（审计 P2）。
   *
   * @param refreshToken refresh 明文。
   * @param context 设备上下文（新会话沿用本次请求的 UA/IP）。
   * @throws {HttpException} 令牌过期 / 非法 / 已撤销（均 401）；用户不可用（401）。
   */
  async refresh(refreshToken: string, context: DeviceContext = {}): Promise<AuthResult> {
    const { claims, record } = await this.#sessions.authenticateRefresh(refreshToken);

    const tenantId = claims.tenantId as string;
    const scope = new Scope(tenantId);
    const users = new UserRepo(this.#db, scope, this.#dialect);
    const user = await users.findById(scope.ref(record.user_id));
    if (user === null || user.is_active !== true) {
      // py：`user is None or not user.is_active` ⇒ UNAUTHORIZED。
      throw unauthorized("用户不存在或已停用");
    }

    const claimed = await this.#sessions.claimForRotation(tenantId, record);
    if (!claimed) {
      // 并发轮换 / 并发登出抢先撤销 ⇒ 与「二次使用」同一口径（防探测：不区分原因）。
      throw tokenRevoked("refresh 令牌已被并发的轮换或登出抢先撤销");
    }

    const tokens = await this.#sessions.issueTokens({
      tenantId,
      userId: user.id,
      device: context.device ?? null,
      ipAddress: context.ipAddress ?? null,
      userAgent: context.userAgent ?? null,
    });

    return { user: toAuthUser(user), tokens: this.#tokenResponse(tokens) };
  }

  /**
   * 登出：解 access → `claims.sid` → 撤销该会话及其全部 refresh。
   *
   * **幂等**：同一 access 连打 2 次都成功 —— 因为解码**不查** `session.revoked_at`
   * （计划 §3.2 / §7，继承语义）。无 `sid` ⇒ 空操作（也算成功）。
   *
   * @param accessToken access 明文。
   * @throws {HttpException} 令牌过期 / 非法（401）。
   */
  async logout(accessToken: string): Promise<void> {
    const claims = await this.#tokens.decode(accessToken, "access");
    if (claims.sid === null) return;
    const tenantId = claims.tenantId ?? this.#tenantId;
    await this.#sessions.revokeSession(tenantId, claims.sid);
  }

  /**
   * 全端退出：撤销该用户全部会话 + refresh。
   *
   * 响应由路由层给 `{message}`（`MessageResponse`），**不回撤销数量**（计划 §7）。
   *
   * @param accessToken access 明文（用它的 `sub` + `tenant_id` 定位用户）。
   * @throws {HttpException} 令牌过期 / 非法（401）。
   */
  async logoutAll(accessToken: string): Promise<void> {
    const claims = await this.#tokens.decode(accessToken, "access");
    const tenantId = claims.tenantId ?? this.#tenantId;
    await this.#sessions.revokeAllSessions(tenantId, claims.sub);
  }

  // -------------------------------------------------------------------------
  // 鉴权 / 设备
  // -------------------------------------------------------------------------

  /**
   * 以 access token 鉴权。
   *
   * **只做三件事**：解码（含 alg/iss/type 校验）→ 用户存在 → `is_active`。
   * **不查** `session.revoked_at`：access 是无状态的，登出后它仍可用至 `exp`（≤900s）。
   * 这是继承语义（R-7 / U-1），不是缺陷 —— 收紧会变成可观测行为变更。
   *
   * @param accessToken access 明文。
   * @returns 认证上下文中的用户视图。
   * @throws {HttpException} 令牌过期 / 非法（401）、用户不存在 / 停用（401）。
   */
  async authenticate(accessToken: string): Promise<AuthUser> {
    const claims: TokenClaims = await this.#tokens.decode(accessToken, "access");
    const tenantId = claims.tenantId ?? this.#tenantId;
    const scope = new Scope(tenantId);
    const users = new UserRepo(this.#db, scope, this.#dialect);
    const user = await users.findById(scope.ref(claims.sub));
    if (user === null) throw unauthorized("用户不存在");
    if (user.is_active !== true) throw unauthorized("账号已停用");
    return toAuthUser(user);
  }

  /**
   * 列出当前用户全部设备会话（含已撤销行 —— `DeviceResponse.revoked_at` 要在列表里可见）。
   *
   * @param accessToken access 明文。
   */
  async listDevices(accessToken: string): Promise<DeviceView[]> {
    const claims = await this.#tokens.decode(accessToken, "access");
    const tenantId = claims.tenantId ?? this.#tenantId;
    const rows = await this.#sessions.listDevices(tenantId, claims.sub);
    return rows.map(toDeviceView);
  }

  // -------------------------------------------------------------------------
  // 内部
  // -------------------------------------------------------------------------

  /** 本服务作用域（默认租户）。 */
  #scope(): Scope {
    return new Scope(this.#tenantId);
  }

  /**
   * 租户必须存在且启用（计划 §2：`is_active=false` ⇒ 该租户登录一律 **401**）。
   *
   * 用 `AUTH_INVALID_CREDENTIALS` 而不是专门的码：租户停用是运营决定，不该通过
   * 错误码向未认证的调用方暴露"这个部署被停用了"。
   */
  async #assertTenantActive(): Promise<void> {
    const scope = this.#scope();
    const tenants = new TenantRepo(this.#db, scope, this.#dialect);
    if (!(await tenants.isActive(scope.ref(this.#tenantId)))) {
      throw invalidCredentials();
    }
  }

  /** 令牌组 → 契约 `TokenResponse`（四键恒在）。 */
  #tokenResponse(tokens: {
    readonly accessToken: string;
    readonly refreshToken: string;
  }): TokenResponse {
    return {
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      token_type: "bearer",
      expires_in: ACCESS_TTL_SECONDS,
    };
  }
}

/** 行 → 对外用户视图（**丢弃** `password_hash`）。 */
function toAuthUser(row: UserRow): AuthUser {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    username: row.username,
    email: row.email,
    displayName: row.display_name,
  };
}

/** 行 → 设备视图。 */
function toDeviceView(row: SessionRow): DeviceView {
  return {
    id: row.id,
    device: row.device,
    ipAddress: row.ip_address,
    userAgent: row.user_agent,
    expiresAt: row.expires_at,
    revokedAt: row.revoked_at,
  };
}
