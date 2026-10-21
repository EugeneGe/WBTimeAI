/**
 * T2-04 · 登录限速（计划 §3.4；`login_attempt` 是**唯一**数据源）。
 *
 * 规则（原样继承 py 线 `wbtime_ai_security/login_guard.py`）
 * ------------------------------------------------------
 * 同一 `username` 的**连续失败** ≥ `max_attempts`(5) 且最近一次失败落在
 * `lock_seconds`(900s) 窗口内 ⇒ 锁定（`AUTH_ACCOUNT_LOCKED`，HTTP **423**）。
 * 成功尝试**打断**连续计数；每次判定只读最近 `max(4×5, 20) = 20` 条。
 *
 * 三条"看起来可以优化、其实不能"的地方
 * ----------------------------------
 * 1. **校验失败也必须落库**：`login_attempt` 是限速的唯一数据来源。只在"确定是攻击"
 *    时才记，等于永远数不到那 5 次。
 * 2. **落库内容不含口令、不含口令哈希**：`data` 只带 `{username, lock_seconds}`
 *    （计划 §3.4 原文），也不区分"用户不存在"与"口令错"—— 否则 423 会变成用户名探测器。
 * 3. **窗口按"最近一次失败"起算**，不是按窗口内失败总数：连续 10 次失败但最近一次在
 *    一小时前 ⇒ **不锁**（py 的 `is_locked` 实现就是读列表首条失败的时间）。
 */

import { LoginAttemptSink, countConsecutiveFailures } from "@wbtime/db";

import type { LoginAttemptRow } from "@wbtime/db";

import { authError } from "./errors.js";
import { ERROR_CODES } from "@wbtime/core";
import { parseDbInstant } from "./refresh.js";

/** 连续失败阈值（py `max_attempts=5`）。 */
export const LOGIN_MAX_ATTEMPTS = 5;

/** 锁定时长 / 失败窗口（秒，py `lock_seconds=900`）。 */
export const LOGIN_LOCK_SECONDS = 900;

/**
 * 判定窗口大小 = `max(4 × max_attempts, 20)`（py 原式）。
 *
 * 4 倍余量的意义：连续失败被一条成功打断后，还要能在后面的失败里重新数到 5；
 * 窗口太小会把"成功之后刚发生的失败"挤出窗口，让锁永远触发不了。
 */
export function loginAttemptWindow(maxAttempts: number = LOGIN_MAX_ATTEMPTS): number {
  return Math.max(maxAttempts * 4, 20);
}

/** {@link LoginGuard} 的可选项。 */
export interface LoginGuardOptions {
  /** 连续失败阈值，缺省 {@link LOGIN_MAX_ATTEMPTS}。 */
  readonly maxAttempts?: number;
  /** 锁定窗口（秒），缺省 {@link LOGIN_LOCK_SECONDS}。 */
  readonly lockSeconds?: number;
  /** 时钟（测试可注入）。 */
  readonly now?: () => Date;
}

/** 一次尝试的落库入参。 */
export interface LoginAttemptInput {
  readonly username: string;
  readonly tenantId?: string | null;
  readonly ipAddress?: string | null;
  readonly success: boolean;
}

/**
 * 登录尝试守卫。
 *
 * 只依赖 T2-03 的 `LoginAttemptSink`（白名单通道 #3）与它的纯函数
 * `countConsecutiveFailures` —— 计数规则本身不在本文件里复制一份。
 */
export class LoginGuard {
  readonly #sink: LoginAttemptSink;
  readonly #maxAttempts: number;
  readonly #lockSeconds: number;
  readonly #now: () => Date;

  constructor(deps: { readonly sink: LoginAttemptSink } & LoginGuardOptions) {
    this.#sink = deps.sink;
    this.#maxAttempts = deps.maxAttempts ?? LOGIN_MAX_ATTEMPTS;
    this.#lockSeconds = deps.lockSeconds ?? LOGIN_LOCK_SECONDS;
    this.#now = deps.now ?? (() => new Date());
  }

  /** 连续失败阈值（对外暴露，便于测试与文档对齐）。 */
  get maxAttempts(): number {
    return this.#maxAttempts;
  }

  /** 锁定时长（秒）。 */
  get lockSeconds(): number {
    return this.#lockSeconds;
  }

  /**
   * 读最近窗口并按"连续失败"计数。
   *
   * @param username 用户名。
   * @returns 新的在前的尝试序列（含成功行 —— 它是打断点，不能提前过滤掉）。
   */
  async recentAttempts(username: string): Promise<LoginAttemptRow[]> {
    return this.#sink.recentAttempts(username, loginAttemptWindow(this.#maxAttempts));
  }

  /** 当前连续失败次数（成功即打断）。 */
  async consecutiveFailures(username: string): Promise<number> {
    return countConsecutiveFailures(await this.recentAttempts(username));
  }

  /**
   * 是否处于锁定期。
   *
   * 三段判定：① 连续失败是否够数；② 最近一次失败是哪条；③ 它是否落在窗口内。
   * 解析不出时间的行按"在窗口内"处理（**保守**：宁可多锁 900 秒，也不要因为一条
   * 时间戳坏掉的记录让爆破无限重试）。
   */
  async isLocked(username: string): Promise<boolean> {
    const recent = await this.recentAttempts(username);
    const failures = countConsecutiveFailures(recent);
    if (failures < this.#maxAttempts) return false;

    const lastFailure = recent.find((row) => row.success !== true);
    if (lastFailure === undefined) return false;

    const createdAt = parseDbInstant(lastFailure.created_at);
    if (createdAt === null) return true;

    return this.#now().getTime() - createdAt <= this.#lockSeconds * 1000;
  }

  /**
   * 若处于锁定期则抛 `AUTH_ACCOUNT_LOCKED`（423）。
   *
   * `data` 只带 `{username, lock_seconds}` —— 不带"还剩多久"、不带"失败几次"，
   * 免得响应体成为攻击者的进度条。
   *
   * @param username 用户名。
   * @throws {HttpException} 锁定中（423）。
   */
  async assertNotLocked(username: string): Promise<void> {
    if (!(await this.isLocked(username))) return;
    throw authError(ERROR_CODES.AUTH_ACCOUNT_LOCKED, "账号因连续登录失败已被临时锁定", {
      username,
      lock_seconds: this.#lockSeconds,
    });
  }

  /**
   * 记一次失败。
   *
   * @param input 尝试信息（**不含口令 / 口令哈希**）。
   */
  async registerFailure(input: Omit<LoginAttemptInput, "success">): Promise<LoginAttemptRow> {
    return this.#sink.record({ ...input, success: false });
  }

  /**
   * 记一次成功（它的作用是**打断**连续失败计数）。
   *
   * @param input 尝试信息。
   */
  async registerSuccess(input: Omit<LoginAttemptInput, "success">): Promise<LoginAttemptRow> {
    return this.#sink.record({ ...input, success: true });
  }
}
