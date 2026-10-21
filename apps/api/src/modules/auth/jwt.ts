/**
 * T2-04 · JWT 签发 / 校验（`jose` 6.2.13，HS256）。
 *
 * 契约口径（计划 §3.2，逐条对齐 py 线 `wbtime_ai_security/jwt.py`）
 * ---------------------------------------------------------------
 * * 算法 `HS256`；`iss = "wbtime-ai"`；
 * * claims = `sub` / `tenant_id` / `type`(`access`|`refresh`) / `exp` / `iat` / `jti` / `sid`；
 * * `access_ttl = 900s`、`refresh_ttl = 1 209 600s`；
 * * 校验**必须显式** `algorithms: ["HS256"]`（禁 alg 混淆 / `alg=none`）+ 校验 `iss`
 *   + 校验 `type` 匹配（access 端点拒 refresh，反之亦然）；
 * * 失败映射：过期 → `AUTH_TOKEN_EXPIRED`；其余（含算法不在白名单、签名不符、
 *   缺必需声明）→ `AUTH_TOKEN_INVALID`。两者都是 **401**，码不同是因为契约分了两码。
 *
 * 两条容易"顺手改坏"的继承语义
 * --------------------------
 * 1. **access 无状态**（计划 §3.2 / R-7 / U-1）：本模块只解码 + 校验声明，
 *    **不查** `session.revoked_at`。⇒ 登出后旧 access 在 `exp` 前仍可用（≤900s），
 *    这是 py 线的既有行为，**不是缺陷**。收紧 = 可观测行为变更 = 破 J-11 等价性。
 * 2. **`tenant_id` / `sid` 为空时不出现在 payload 里**（不是写 `null`）：py 侧是
 *    `if tenant_id is not None: payload[...]`。写 `null` 会让令牌多一个键，
 *    J-11 的"data 键集合"比对会红。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import { SignJWT, errors as joseErrors, jwtVerify } from "jose";

import { authError, tokenExpired, tokenInvalid } from "./errors.js";

/** 签发者（`iss`）。 */
export const TOKEN_ISSUER = "wbtime-ai";

/** 唯一允许的签名算法。 */
export const JWT_ALGORITHM = "HS256";

/** access token 有效期（秒）。契约 `TokenResponse.expires_in` 的默认值同源。 */
export const ACCESS_TTL_SECONDS = 900;

/** refresh token 有效期（秒）= 14 天。 */
export const REFRESH_TTL_SECONDS = 1_209_600;

/** 令牌类型取值域（封闭，不扩）。 */
export const TOKEN_TYPES = Object.freeze(["access", "refresh"] as const);

/** 令牌类型。 */
export type TokenType = (typeof TOKEN_TYPES)[number];

/** 令牌类型守卫。 */
export function isTokenType(value: unknown): value is TokenType {
  return value === "access" || value === "refresh";
}

/** 解码后的令牌声明（对外形状；`raw` 保留原始 payload 供审计）。 */
export interface TokenClaims {
  /** 主体（用户 id）。 */
  readonly sub: string;
  /** 租户 id；令牌里没有则为 `null`。 */
  readonly tenantId: string | null;
  /** 令牌类型。 */
  readonly type: TokenType;
  /** 令牌唯一标识。 */
  readonly jti: string | null;
  /** 会话 id（`logout` 靠它定位要撤销的会话）。 */
  readonly sid: string | null;
  /** 过期时刻。 */
  readonly exp: Date | null;
  /** 原始 payload（只读快照）。 */
  readonly raw: Readonly<Record<string, unknown>>;
}

/** `TokenService` 的可选项。 */
export interface TokenServiceOptions {
  /** access 有效期（秒），缺省 {@link ACCESS_TTL_SECONDS}。 */
  readonly accessTtlSeconds?: number;
  /** refresh 有效期（秒），缺省 {@link REFRESH_TTL_SECONDS}。 */
  readonly refreshTtlSeconds?: number;
  /** 签发者，缺省 {@link TOKEN_ISSUER}。 */
  readonly issuer?: string;
  /** 时钟（测试可注入固定时刻；缺省 `() => new Date()`）。 */
  readonly now?: () => Date;
}

/** 签发一对令牌时的可选上下文。 */
export interface TokenContext {
  /** 租户 id；`null` / 省略 ⇒ payload 里不出现 `tenant_id`（对齐 py）。 */
  readonly tenantId?: string | null;
  /** 会话 id；`null` / 省略 ⇒ payload 里不出现 `sid`。 */
  readonly sessionId?: string | null;
}

/**
 * JWT 服务。
 *
 * 密钥必须是 UTF-8 后的**字节**串（HS256 的 HMAC key）；长度校验在
 * `@wbtime/config` 的 `requireSecretKey()`，这里只做**防御性**复查 ——
 * 因为本类可以被直接构造（测试 / 其他装配路径），不能假设调用方都过了那道闸。
 */
export class TokenService {
  readonly #key: Uint8Array;
  readonly #accessTtl: number;
  readonly #refreshTtl: number;
  readonly #issuer: string;
  readonly #now: () => Date;

  constructor(secret: string, options: TokenServiceOptions = {}) {
    if (typeof secret !== "string" || secret === "") {
      throw authError(ERROR_CODES.CONFIGURATION_ERROR, "JWT 密钥缺失", {
        capability: "auth.jwt",
      });
    }
    this.#key = new TextEncoder().encode(secret);
    this.#accessTtl = options.accessTtlSeconds ?? ACCESS_TTL_SECONDS;
    this.#refreshTtl = options.refreshTtlSeconds ?? REFRESH_TTL_SECONDS;
    this.#issuer = options.issuer ?? TOKEN_ISSUER;
    this.#now = options.now ?? (() => new Date());
  }

  /** access 有效期（秒）——`TokenResponse.expires_in` 取它。 */
  get accessTtlSeconds(): number {
    return this.#accessTtl;
  }

  /** refresh 有效期（秒）。 */
  get refreshTtlSeconds(): number {
    return this.#refreshTtl;
  }

  /** 签发 access token。 */
  createAccessToken(subject: string, context: TokenContext = {}): Promise<string> {
    return this.#encode(subject, "access", this.#accessTtl, context);
  }

  /** 签发 refresh token。 */
  createRefreshToken(subject: string, context: TokenContext = {}): Promise<string> {
    return this.#encode(subject, "refresh", this.#refreshTtl, context);
  }

  /**
   * 解码并校验令牌。
   *
   * @param token 紧凑序列化 JWT。
   * @param expectedType 期望类型；不给则不校验类型（`logout` 用 access 时会校验）。
   * @returns 校验通过的声明。
   * @throws {HttpException} 过期 → `AUTH_TOKEN_EXPIRED`(401)；
   *   算法不在白名单 / 签名不符 / `iss` 不符 / 缺 `sub`·`exp` / 类型不符
   *   → `AUTH_TOKEN_INVALID`(401)。**均 401**，不区分"伪造"与"过期"以外的细节。
   */
  async decode(token: string, expectedType?: TokenType): Promise<TokenClaims> {
    if (typeof token !== "string" || token.trim() === "") {
      throw tokenInvalid("令牌为空");
    }

    let payload: Record<string, unknown>;
    try {
      // `algorithms` 白名单是**显式**的：不传它，jose 会按令牌自带的 alg 选实现，
      // `alg=none` / `RS256` 伪造就能借道（J-3 的假绿形态）。
      const verified = await jwtVerify(token, this.#key, {
        algorithms: [JWT_ALGORITHM],
        issuer: this.#issuer,
      });
      payload = verified.payload as Record<string, unknown>;
    } catch (error) {
      if (error instanceof joseErrors.JWTExpired) throw tokenExpired();
      throw tokenInvalid();
    }

    if (typeof payload.sub !== "string" || payload.sub === "") {
      throw tokenInvalid("令牌缺少 sub");
    }
    if (typeof payload.exp !== "number" || !Number.isFinite(payload.exp)) {
      // py 侧 `options={"require": ["exp","sub"]}`：缺 exp 的令牌一律非法。
      throw tokenInvalid("令牌缺少 exp");
    }

    const type = payload.type;
    if (!isTokenType(type)) {
      throw tokenInvalid("令牌缺少合法 type 声明");
    }
    if (expectedType !== undefined && type !== expectedType) {
      throw tokenInvalid(`令牌类型不符：期望 ${expectedType}，实际 ${type}`);
    }

    return {
      sub: payload.sub,
      tenantId: typeof payload.tenant_id === "string" ? payload.tenant_id : null,
      type,
      jti: typeof payload.jti === "string" ? payload.jti : null,
      sid: typeof payload.sid === "string" ? payload.sid : null,
      exp: new Date(payload.exp * 1000),
      raw: Object.freeze({ ...payload }),
    };
  }

  /**
   * 编码。
   *
   * `iat` / `exp` 用**秒**（JWT 规范），`jti` 每次新生成（撤销/审计的抓手）。
   * 与 py 一样把 `iss` 放进 payload，而不是只靠库的隐式行为。
   */
  async #encode(
    subject: string,
    type: TokenType,
    ttlSeconds: number,
    context: TokenContext
  ): Promise<string> {
    if (typeof subject !== "string" || subject === "") {
      throw tokenInvalid("签发令牌需要非空 sub");
    }
    const issuedAt = Math.floor(this.#now().getTime() / 1000);
    const payload: Record<string, unknown> = {
      sub: subject,
      type,
      iat: issuedAt,
      exp: issuedAt + ttlSeconds,
      jti: randomUUID(),
      iss: this.#issuer,
    };
    if (typeof context.tenantId === "string" && context.tenantId !== "") {
      payload.tenant_id = context.tenantId;
    }
    if (typeof context.sessionId === "string" && context.sessionId !== "") {
      payload.sid = context.sessionId;
    }
    return new SignJWT(payload).setProtectedHeader({ alg: JWT_ALGORITHM, typ: "JWT" }).sign(this.#key);
  }
}
