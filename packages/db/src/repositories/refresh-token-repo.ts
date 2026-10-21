/**
 * T2-03 · `refresh_token` 仓储（refresh 的**哈希**存根）。
 *
 * 🔴 红线：`token_hash` 只存 `sha256(明文)` 的 **hex**，**不存明文**（计划 §2 / §7.1-2）。
 * 为了让「手滑存明文」在运行时也过不去，本仓储对入参做了形状校验
 * （{@link assertSha256Hex}）：长度不是 64 位 hex 的串**当场拒绝**。
 * 校验放在仓储（而不是只靠 code review）的理由很直接 —— 这个字段一旦写进明文，
 * 库文件就永久带着一个可用凭据，删库前无解。
 *
 * 轮换语义（计划 §3.3）：`sha256` 命中「未撤销且未过期」的 refresh → 撤销旧 session
 * （连带其全部 refresh）→ 建新 session + 新令牌对。二次使用旧 refresh ⇒ 401
 * `AUTH_TOKEN_REVOKED`，响应体**不区分**「已撤销」与「不存在」（防探测）——
 * 故本仓储只提供「按 hash 取」，不提供「是否存在」的布尔便利方法。
 */

import { and, eq, gt, isNull, type InferSelectModel } from "drizzle-orm";

import { refresh_token as pgRefreshToken } from "../schema/pg/index.js";
import { refresh_token as sqliteRefreshToken } from "../schema/sqlite/index.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `refresh_token` 行。 */
export type RefreshTokenRow = InferSelectModel<typeof pgRefreshToken>;

const SHA256_HEX = /^[0-9a-f]{64}$/i;

/**
 * 断言入参是 sha256 的 hex 串（64 位）。
 *
 * @throws {ScopeError} 形状不符 —— 传明文（或截断的 hash）视为**编程错误**，
 *   与业务错误区分开：它不该被 try/catch 吞掉，必须炸在开发机上。
 */
export function assertSha256Hex(tokenHash: string, label = "tokenHash"): void {
  if (typeof tokenHash !== "string" || !SHA256_HEX.test(tokenHash)) {
    throw new ScopeError(
      `${label} 必须是 sha256 明文的 64 位 hex 串 —— 传明文/截断值一律拒绝：` +
        "本表只存哈希，存明文等于把可用凭据写进库"
    );
  }
}

export class RefreshTokenRepo extends ScopedRepo<RefreshTokenRow> {
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgRefreshToken, sqliteRefreshToken), scope);
    this.#dialect = dialect;
  }

  /** 按 hash 取存根（**不**校验是否有效；有效性判定见 {@link findActiveByTokenHash}）。 */
  async findByTokenHash(tokenHash: string): Promise<RefreshTokenRow | null> {
    assertSha256Hex(tokenHash);
    return this.findOneWhere(eq(this.columns.token_hash, tokenHash));
  }

  /** 按 hash 取「未撤销且未过期」的存根；`null` 一律折算 401（不区分原因，防探测）。 */
  async findActiveByTokenHash(
    tokenHash: string,
    at: Date | string = new Date()
  ): Promise<RefreshTokenRow | null> {
    assertSha256Hex(tokenHash);
    return this.findOneWhere(
      and(
        eq(this.columns.token_hash, tokenHash),
        isNull(this.columns.revoked_at),
        gt(this.columns.expires_at, instantLiteral(this.#dialect, at) as Date)
      )
    );
  }

  /** 建档（`session_id` 可空；哈希形状由 {@link assertSha256Hex} 把关）。 */
  create(row: TenantScopedInsert<RefreshTokenRow>): Promise<RefreshTokenRow> {
    assertSha256Hex(row.token_hash);
    return this.insertRow(row);
  }

  /** 按 session 列出其 refresh 存根（轮换/审计用）。 */
  listBySession(sessionRef: ScopedRef, options: ListOptions = {}): Promise<RefreshTokenRow[]> {
    this.assertOwnRef(sessionRef, "sessionRef");
    return this.findManyWhere(eq(this.columns.session_id, sessionRef.id), options);
  }

  /** 撤销单条 refresh（幂等：只改写 `revoked_at IS NULL` 的行）。 */
  async revoke(ref: ScopedRef, at: Date | string = new Date()): Promise<boolean> {
    this.assertOwnRef(ref, "refreshTokenRef");
    const rows = await this.updateManyWhere(
      and(eq(this.columns.id, ref.id), isNull(this.columns.revoked_at)),
      { revoked_at: instantLiteral(this.#dialect, at) as Date }
    );
    return rows.length > 0;
  }

  /**
   * 撤销某 session 名下的全部 refresh（刷新轮换时连带撤销旧会话的全部 refresh）。
   *
   * @returns 实际被改写的条数。
   */
  async revokeBySession(sessionRef: ScopedRef, at: Date | string = new Date()): Promise<number> {
    this.assertOwnRef(sessionRef, "sessionRef");
    const rows = await this.updateManyWhere(
      and(eq(this.columns.session_id, sessionRef.id), isNull(this.columns.revoked_at)),
      { revoked_at: instantLiteral(this.#dialect, at) as Date }
    );
    return rows.length;
  }

  /**
   * 撤销某用户**全部** refresh（`POST /users/me/logout-all` 的 refresh 侧）。
   *
   * 为什么按 `user_id` 而不是"先取会话再按会话撤"（FIX-06 / FIX-06b）
   * ------------------------------------------------------------
   * 旧实现是「取该用户的会话列表 → 逐条 `revokeBySession`」：
   * * N 个会话 ⇒ N 条 UPDATE（N+1 反模式）；
   * * 会话集合一旦有上限（旧实现 `listByUser(limit:500)`）就会漏撤第 500 条之后的
   *   refresh，而会话侧 `SessionRepo.revokeAllByUser` 是单条 UPDATE 撤**全部** ⇒
   *   「session 已撤销、refresh 仍可轮换」的口径裂缝；
   * * **`session_id IS NULL` 的 refresh 行永远不会被按会话撤销命中**，而
   *   `SessionTokenService.authenticateRefresh` 在 `session_id === null` 时跳过会话校验
   *   ⇒ 这类行（脏数据/历史数据）在 logout-all 之后**仍然可轮换**。这是比"漏 500 条"
   *   更本质的缺口：它跟会话数量无关，是"以会话为撤销索引"这个设计本身的盲区。
   *
   * 按 `user_id` 直接撤，一次命中全部行，且与会话数量、会话是否存在、`session_id`
   * 是否为空**都**无关 —— 语义上「全端退出 = 这个人的所有 refresh 都作废」。
   * 租户隔离由 `ScopedRepo` 的 scope 谓词兜底（`WHERE tenant_id = ? AND ...`），
   * 因此另一个租户里同 `user_id` 的行不会被连带撤销。
   *
   * 幂等：`WHERE revoked_at IS NULL`，重复调用只覆盖一次、不改写时间戳。
   *
   * @param userRef 本 scope 内的用户引用（**不接受裸 id**）。
   * @param at 撤销时刻（按方言转字面量）。
   * @returns 实际被改写的行数；该用户没有 refresh 时为 `0`（不抛错）。
   * @throws {ScopeError} 引用不属于本 scope。
   */
  async revokeByUser(userRef: ScopedRef, at: Date | string = new Date()): Promise<number> {
    this.assertOwnRef(userRef, "userRef");
    const rows = await this.updateManyWhere(
      and(eq(this.columns.user_id, userRef.id), isNull(this.columns.revoked_at)),
      { revoked_at: instantLiteral(this.#dialect, at) as Date }
    );
    return rows.length;
  }
}
