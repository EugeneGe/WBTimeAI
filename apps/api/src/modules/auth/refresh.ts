/**
 * T2-04 · 会话与 refresh 轮换（计划 §3.3 / §7）。
 *
 * 语义（逐条对齐 py 线 `wbtime_ai_security/session.py`）
 * ---------------------------------------------------
 * * 一次登录 = 一条 `session`（设备维度）；**不物理删除**（`devices` 列表要看到已撤销行）；
 * * `refresh_token` 只存 `sha256(明文)` 的 **hex**，明文只在签发那一次出现在响应里；
 * * 轮换：命中「未撤销且未过期」→ **认领（撤销旧 refresh 行 + 旧会话）** → 建新 session +
 *   新令牌对；认领以 **affected rows** 为准（FIX-24）：只有真正把 `revoked_at` 由 NULL
 *   改成非 NULL 的那一次才签发，并发两次同一 refresh 必有一次 401，不会换出两对令牌；
 * * 二次使用旧 refresh ⇒ `AUTH_TOKEN_REVOKED`(401)；会话已撤销 ⇒ 同样 `AUTH_TOKEN_REVOKED`；
 *   记录不存在 ⇒ `AUTH_TOKEN_INVALID`(401)（与 py 一致，见施工记录 D-3 的口径张力说明）；
 * * 撤销**幂等**：`WHERE revoked_at IS NULL`（`SessionRepo.revoke` / `RefreshTokenRepo.revokeBySession`
 *   在 T2-03 里就是这么实现的），重复撤销只覆盖一次、**不抛错**。
 *
 * 时间列的双档形状（T2-03 D-6 的已知代价）
 * --------------------------------------
 * 仓储的行类型按 PG 档声明（`Date`），但 SQLite 档的时间列是 `text`
 * （`YYYY-MM-DD HH:MM:SS`，UTC、秒精度）。故写入时按方言转换、读取时按两种形状解析 ——
 * 直接拿 ISO 串去和 `CURRENT_TIMESTAMP` 形状比，会把"未过期"判成"过期"（不报错，只让人莫名被登出）。
 */

import { createHash, randomUUID } from "node:crypto";

import {
  RefreshTokenRepo,
  Scope,
  SessionRepo,
  toSqliteTimestamp,
  type DrizzleDatabase,
  type RefreshTokenRow,
  type SessionRow,
  type SqlDialect,
} from "@wbtime/db";

import { tokenExpired, tokenInvalid, tokenRevoked } from "./errors.js";
import { REFRESH_TTL_SECONDS, TokenService, type TokenClaims } from "./jwt.js";

/**
 * 会话有效期（秒）：与 refresh TTL 对齐。
 *
 * py 线 `DEFAULT_SESSION_TTL_SECONDS = 1_209_600` 且注释写明"与 refresh token TTL 对齐"。
 * 两者**同值不同源**的危险在于：哪天只改一处，就会出现"refresh 还有效但 session 已过期"
 * 的悬空态。这里直接引用同一个常量，从根上消除分叉。
 */
export const SESSION_TTL_SECONDS = REFRESH_TTL_SECONDS;

/** 一次签发产生的令牌组。`refreshToken` 是明文 —— 只在这一刻存在。 */
export interface SessionTokens {
  readonly sessionId: string;
  readonly accessToken: string;
  readonly refreshToken: string;
}

/** 签发令牌的入参。 */
export interface IssueTokensInput {
  readonly tenantId: string;
  readonly userId: string;
  readonly device?: string | null;
  readonly ipAddress?: string | null;
  readonly userAgent?: string | null;
}

/** {@link SessionTokenService.authenticateRefresh} 的结果。 */
export interface RefreshAuthentication {
  readonly claims: TokenClaims;
  readonly record: RefreshTokenRow;
}

/** {@link SessionTokenService} 的可选项。 */
export interface SessionTokenServiceOptions {
  /** 方言（缺省 `pg`；测试传 `sqlite`）。 */
  readonly dialect?: SqlDialect;
  /** 会话有效期（秒），缺省 {@link SESSION_TTL_SECONDS}。 */
  readonly sessionTtlSeconds?: number;
  /** 时钟（测试可注入）。 */
  readonly now?: () => Date;
}

/**
 * refresh 令牌的存储哈希：`sha256(明文)` 的 hex（64 字符）。
 *
 * `RefreshTokenRepo` 内置了同样的形状校验（非 64 hex 直接抛），因此这里漏改就会
 * **当场炸**而不是把明文写进库。
 */
export function hashRefreshToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

/**
 * 把库里的时间值解析成毫秒时间戳。
 *
 * 支持三种形状：`Date`（PG 档）、`YYYY-MM-DD HH:MM:SS[.sss]`（SQLite 文本，UTC）、
 * 以及任何 `Date.parse` 认得的串（兜底）。
 *
 * @param value 库值。
 * @returns 毫秒时间戳；无法解析返回 `null`（调用方据此**不做**时间判定，
 *   而不是把"解析失败"当成"已过期"——后者会把所有会话瞬间作废）。
 */
export function parseDbInstant(value: unknown): number | null {
  if (value instanceof Date) {
    const time = value.getTime();
    return Number.isNaN(time) ? null : time;
  }
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim() === "") return null;
  const text = value.trim();
  const sqliteShape = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(text);
  if (sqliteShape) {
    const [, year, month, day, hour, minute, second, millis] = sqliteShape;
    return Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
      millis === undefined ? 0 : Number(millis.padEnd(3, "0"))
    );
  }
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? null : parsed;
}

/** 时间列写入字面量：PG 档 `Date`、SQLite 档 `YYYY-MM-DD HH:MM:SS`（见文件头注）。 */
function instantLiteral(dialect: SqlDialect, at: Date): Date {
  return (dialect === "sqlite" ? toSqliteTimestamp(at) : at) as unknown as Date;
}

/**
 * `created_at` / `updated_at` 的显式值。
 *
 * 为什么不让库默认值生效：T2-03 的 `TenantScopedInsert<TRow>` 是
 * `Omit<TRow, "tenant_id">`，而 drizzle 的 select 模型把**有默认值的列**也算作必需
 * 属性 ⇒ 不传就编译不过。既然非传不可，就传**注入时钟**的值而不是库的 `now()`：
 * 测试可以钉住时刻（J-4 要断言"旧 session 撤销时间非空"，固定时钟让断言可精确）。
 */
export function auditStamps(dialect: SqlDialect, at: Date): { created_at: Date; updated_at: Date } {
  const stamp = instantLiteral(dialect, at);
  return { created_at: stamp, updated_at: stamp };
}

/** 会话与 refresh 令牌的生命周期服务。 */
export class SessionTokenService {
  readonly #db: DrizzleDatabase;
  readonly #tokens: TokenService;
  readonly #dialect: SqlDialect;
  readonly #sessionTtl: number;
  readonly #now: () => Date;

  constructor(
    deps: {
      readonly db: DrizzleDatabase;
      readonly tokens: TokenService;
    } & SessionTokenServiceOptions
  ) {
    this.#db = deps.db;
    this.#tokens = deps.tokens;
    this.#dialect = deps.dialect ?? "pg";
    this.#sessionTtl = deps.sessionTtlSeconds ?? SESSION_TTL_SECONDS;
    this.#now = deps.now ?? (() => new Date());
  }

  /**
   * 建会话 + 签发 access / refresh。
   *
   * 顺序是刻意的：先落 `session`（拿到 id）→ 再用该 id 签 refresh（payload 里带 `sid`）
   * → 存 refresh 哈希 → 最后签 access。反过来做就得回填 `sid`，多一次写。
   */
  async issueTokens(input: IssueTokensInput): Promise<SessionTokens> {
    const scope = new Scope(input.tenantId);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    const tokenRepo = new RefreshTokenRepo(this.#db, scope, this.#dialect);

    const sessionId = randomUUID();
    const now = this.#now();
    const expiresAt = new Date(now.getTime() + this.#sessionTtl * 1000);

    await sessions.create({
      id: sessionId,
      user_id: input.userId,
      device: input.device ?? null,
      ip_address: input.ipAddress ?? null,
      user_agent: input.userAgent ?? null,
      expires_at: instantLiteral(this.#dialect, expiresAt),
      revoked_at: null,
      ...auditStamps(this.#dialect, now),
    });

    const refreshToken = await this.#tokens.createRefreshToken(input.userId, {
      tenantId: input.tenantId,
      sessionId,
    });

    await tokenRepo.create({
      id: randomUUID(),
      user_id: input.userId,
      session_id: sessionId,
      token_hash: hashRefreshToken(refreshToken),
      expires_at: instantLiteral(this.#dialect, expiresAt),
      revoked_at: null,
      ...auditStamps(this.#dialect, now),
    });

    const accessToken = await this.#tokens.createAccessToken(input.userId, {
      tenantId: input.tenantId,
      sessionId,
    });

    return { sessionId, accessToken, refreshToken };
  }

  /**
   * 校验 refresh 令牌，返回有效记录。
   *
   * 四道闸门（顺序与 py 一致）：① 解码（含 exp / iss / alg / type）；② 哈希命中；
   * ③ `revoked_at` 为空；④ 会话未撤销。过期在 ① 就被 `AUTH_TOKEN_EXPIRED` 拦下，
   * ③④ 都是 `AUTH_TOKEN_REVOKED`。
   *
   * @throws {HttpException} `AUTH_TOKEN_EXPIRED` / `AUTH_TOKEN_INVALID` / `AUTH_TOKEN_REVOKED`（均 401）。
   */
  async authenticateRefresh(refreshToken: string): Promise<RefreshAuthentication> {
    const claims = await this.#tokens.decode(refreshToken, "refresh");
    if (claims.tenantId === null) {
      // 没有租户声明的 refresh 无法定位 scope —— 一律当非法，不猜默认租户。
      throw tokenInvalid("refresh 令牌缺少 tenant_id 声明");
    }
    const scope = new Scope(claims.tenantId);
    const tokenRepo = new RefreshTokenRepo(this.#db, scope, this.#dialect);

    const record = await tokenRepo.findByTokenHash(hashRefreshToken(refreshToken));
    if (record === null) {
      // py：哈希命中不到 ⇒ AUTH_TOKEN_INVALID（不是 REVOKED）。见施工记录 D-3 的口径张力。
      throw tokenInvalid("refresh 令牌不存在");
    }
    if (record.revoked_at !== null) throw tokenRevoked("refresh 令牌已撤销");

    const expiresAt = parseDbInstant(record.expires_at);
    if (expiresAt !== null && expiresAt <= this.#now().getTime()) throw tokenExpired();

    if (record.session_id !== null) {
      const sessions = new SessionRepo(this.#db, scope, this.#dialect);
      const session = await sessions.findById(scope.ref(record.session_id));
      if (session !== null && session.revoked_at !== null) throw tokenRevoked("会话已撤销");
    }

    return { claims, record };
  }

  /**
   * 撤销一条会话及其名下全部 refresh（**登出**专用）。
   *
   * 轮换不再走这里：轮换要的是「以 affected rows 判定谁抢到这次轮换」，
   * 见 {@link claimForRotation}（FIX-24）。
   *
   * 幂等：两次调用不抛错，第二次不再改写时间戳（`WHERE revoked_at IS NULL`）。
   *
   * @param tenantId 会话所属租户（决定 scope）。
   * @param sessionId 会话 id。
   */
  async revokeSession(tenantId: string, sessionId: string): Promise<void> {
    const scope = new Scope(tenantId);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    const tokenRepo = new RefreshTokenRepo(this.#db, scope, this.#dialect);
    const at = this.#now();
    await sessions.revoke(scope.ref(sessionId), at);
    await tokenRepo.revokeBySession(scope.ref(sessionId), at);
  }

  /**
   * 轮换前的**原子认领**：把「旧 refresh 行」与「旧会话」由有效改成已撤销，
   * 并以**实际改写行数**（affected rows）判定本次是否抢到了这次轮换（FIX-24）。
   *
   * 为什么不能只做"先查后撤"
   * ----------------------
   * 旧路径是 `find → revoke → issue`：两个并发请求可能**都**通过「未撤销」校验，
   * 于是各自撤销并各自签发 —— 同一个 refresh 换出两对有效令牌（TOCTOU）。
   * 单线程的 Node 里，交错点就是 `await`；只要"校验"与"写入"之间有 await，
   * 这个窗口就真实存在（已用延迟探针在测试里确定性地撑开）。
   *
   * 判据以 `UPDATE ... WHERE revoked_at IS NULL` 的 **affected rows** 为准：
   * 该语句天然是原子的 —— 谁先把 NULL 改成非 NULL，谁就拿到这次轮换的资格。
   *
   * 三条 UPDATE 的顺序与理由：
   * 1. `revoke(refresh)`：认领的**唯一凭据**（返回 `boolean`）。0 行 ⇒ 已被别人抢先，
   *    立刻返回 `false`，调用方必须转 401 `AUTH_TOKEN_REVOKED` —— 不签发任何令牌。
   * 2. `revoke(session)`：会话维度的同一判据（并发 logout 抢先撤销会话时同样必须拒绝）。
   * 3. `revokeBySession`：连带撤掉该会话名下**其余** refresh 行（正常形态下只有 1 条，
   *    但 `session_id` 上并无唯一约束，不做这一步就会留下同会话的第二条活口）。
   *
   * 注意第 2 步失败时第 1 步已生效（旧 refresh 已被撤），这正是想要的收敛方向：
   * 宁可让用户重新登录，也不能发出一对"来源已被撤销"的新令牌。
   *
   * @param tenantId 令牌所属租户（决定 scope）。
   * @param record {@link authenticateRefresh} 返回的 refresh 行。
   * @returns `true` = 本次调用成功认领（可以签发新令牌）；`false` = 已被抢先撤销。
   */
  async claimForRotation(tenantId: string, record: RefreshTokenRow): Promise<boolean> {
    const scope = new Scope(tenantId);
    const tokenRepo = new RefreshTokenRepo(this.#db, scope, this.#dialect);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    const at = this.#now();

    const claimed = await tokenRepo.revoke(scope.ref(record.id), at);
    if (!claimed) return false;

    if (record.session_id === null) {
      // 无会话的 refresh（历史数据兜底）：没有会话可撤，refresh 行本身已认领即成立。
      return true;
    }

    const sessionRef = scope.ref(record.session_id);
    const sessionClaimed = await sessions.revoke(sessionRef, at);
    await tokenRepo.revokeBySession(sessionRef, at);
    return sessionClaimed;
  }

  /**
   * 撤销某用户**全部**会话与 refresh（全端退出）。
   *
   * 数据口径（FIX-06 → FIX-06b）
   * -------------------------
   * 目标语义：**"全端退出" = 这个人的所有 refresh 都作废**，与会话数量、会话是否存在、
   * `session_id` 是否为空都无关。
   *
   * 旧实现（审计 #8）用 `listByUser(limit: 500)` 取会话集合再逐条 `revokeBySession`，
   * 有三个问题叠在一起：
   * * 语句数 = 会话数 + 1（N+1）；
   * * 会话集合被 500 截断 ⇒ 第 501 条之后的 refresh 不会被撤，而会话侧
   *   `revokeAllByUser` 是**单条** UPDATE 撤全部 ⇒ 「session 已撤销、refresh 仍可轮换」；
   * * **`session_id IS NULL` 的行永远不在任何会话集合里** ⇒ 它根本不会被命中。而
   *   {@link authenticateRefresh} 在 `session_id === null` 时**跳过会话校验**，所以这类
   *   行在 logout-all 之后仍能换出新令牌 —— 这个缺口跟 500 无关，是"以会话为撤销索引"
   *   这个设计本身的盲区。
   *
   * 因此改为**两条按 user_id 的 UPDATE**（FIX-06b）：
   * 1. `RefreshTokenRepo.revokeByUser`：`WHERE tenant_id = ? AND user_id = ? AND revoked_at IS NULL`；
   * 2. `SessionRepo.revokeAllByUser`：同样单条。
   *
   * 语句数恒为 **2 条 UPDATE、0 条 SELECT**，且与会话数、refresh 数彻底无关；
   * 租户隔离由两个仓储的 scope 谓词兜底（另一租户里同 `user_id` 的行不受影响）。
   *
   * 顺序刻意是「先 refresh、后 session」：中途崩掉的残留态是「refresh 已撤、session 未撤」，
   * 那个方向是安全的（refresh 撤了就无法再换令牌）；反过来会留下"session 已撤但
   * refresh 仍能轮换"的活口。
   *
   * 幂等：两条 UPDATE 都带 `revoked_at IS NULL`，二次调用不改写任何时间戳。
   *
   * @param tenantId 租户（决定 scope）。
   * @param userId 用户 id。
   * @returns 实际被撤销（由未撤销变已撤销）的会话数；**契约不返回这个数**，仅供日志/断言。
   */
  async revokeAllSessions(tenantId: string, userId: string): Promise<number> {
    const scope = new Scope(tenantId);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    const tokenRepo = new RefreshTokenRepo(this.#db, scope, this.#dialect);
    const at = this.#now();
    const userRef = scope.ref(userId);

    await tokenRepo.revokeByUser(userRef, at);
    return sessions.revokeAllByUser(userRef, at);
  }

  /** 列出某用户全部会话（含已撤销 —— `devices` 口径，计划 §7）。 */
  listDevices(tenantId: string, userId: string): Promise<SessionRow[]> {
    const scope = new Scope(tenantId);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    return sessions.listByUser(scope.ref(userId), { limit: 500 });
  }

  /** 会话是否仍然有效（未撤销且未过期）；供 T2-07 的路由守卫按需使用。 */
  async isSessionActive(tenantId: string, sessionId: string): Promise<boolean> {
    const scope = new Scope(tenantId);
    const sessions = new SessionRepo(this.#db, scope, this.#dialect);
    return sessions.isActive(scope.ref(sessionId), this.#now());
  }
}
