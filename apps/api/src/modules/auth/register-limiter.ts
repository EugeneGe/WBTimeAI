/**
 * FIX-04 · 未认证 `POST /auth/register` 的进程内限速器（20xx 审计 #5 / 裁定 R-34）。
 *
 * 为什么要限速（问题的真实形状）
 * --------------------------
 * 注册是本版**唯一**「不需要令牌 + 每次请求都烧 CPU」的入口：`AuthService.register`
 * 在查重通过后立刻跑一次 `argon2id`（m=64MiB, t=3, p=4，实测 50～100ms）。
 * 也就是说单个客户端串行发 20 个请求就能占满一个核若干秒，并发起来更糟 ——
 * 这是一条**未认证的算力放大面**，且没有成本。
 *
 * 三条不可让步的性质
 * ----------------
 * 1. **必须在 argon2 之前**判定。放在 `hasher.hash` 之后 = 没省一次 CPU = 等于没防
 *    （只是把响应码换成了 429）。落点见 `routes/auth.ts` 与配套测试的 hasher 计数断言。
 * 2. **每 app 实例一份**，禁止模块级单例。单例会让"同一进程里并发跑的两组测试夹具"
 *    互相消耗配额 —— 那类失败是间歇性的，最难归因（本仓 R-34 明确要求注入式构造）。
 * 3. **按客户端 IP 计数**，且**不信任** `X-Forwarded-For`：本版尚未确定代理形态
 *    （`trustProxy` 未开），信任该头等于让攻击者用一个自造头把自己伪装成无限多个 IP。
 *    取值点因此是 `request.ip`（Fastify 按 socket 对端地址给出）。
 *
 * 为什么是滑动窗口而不是固定窗口
 * ----------------------------
 * 固定窗口（每分钟清零）在窗口边界会放过 2×limit 个请求（59s 打满 + 61s 再打满）。
 * 滑动窗口用「最近 60s 的时间戳列表」判定，边界没有这种突刺；代价是每 IP 最多保留
 * `limitPerMinute` 个时间戳（内存上界 = 活跃 IP 数 × limit，可控）。
 *
 * 内存不无界
 * ---------
 * 两条 prune：
 * * **每次访问**都把该 IP 里超出窗口的时间戳丢掉（`Array#filter`）；
 * * 当记录的 IP 数超过 {@link PRUNE_KEY_THRESHOLD} 时，扫一遍把所有"窗口内无命中"的
 *   key 删掉。没有这一条，被扫描器打过的实例会永久留着几十万个空数组。
 */

/** 限速窗口（毫秒）。固定 60s —— 与"每分钟"这个对外口径严格一致。 */
export const REGISTER_RATE_WINDOW_MS = 60_000;

/** 触发 key 级清扫的阈值（超过它才扫；每请求都全表扫是 O(n)，没必要）。 */
export const PRUNE_KEY_THRESHOLD = 256;

/** 一次限速判定的结果。 */
export interface RegisterLimiterDecision {
  /** 是否放行（`true` 才继续走 argon2）。 */
  readonly allowed: boolean;
  /** 建议的 `Retry-After` 秒数；放行时为 `0`。 */
  readonly retryAfterSeconds: number;
}

/** {@link createRegisterLimiter} 的构造参数。 */
export interface RegisterLimiterOptions {
  /** 阈值：每客户端 IP / 每分钟允许的注册次数。`0` = 关闭限速（不记账）。 */
  readonly limitPerMinute: number;
  /** 时钟（测试注入固定/可推进时钟）。缺省真实时钟。 */
  readonly now?: () => Date;
}

/** 限速器（每个 app 实例一份；见文件头第 2 条）。 */
export interface RegisterLimiter {
  /** 阈值（原样回显，供错误 `data` 与日志使用）。 */
  readonly limitPerMinute: number;
  /**
   * 判定并**记账**一次注册尝试。
   *
   * @param clientKey 客户端标识（本版恒为请求的 socket 对端 IP）。
   * @returns `{ allowed, retryAfterSeconds }`。
   */
  check(clientKey: string): RegisterLimiterDecision;
  /** 当前记账的 key 数（诊断/测试用；证明 prune 生效）。 */
  size(): number;
}

/**
 * 造一个限速器。
 *
 * @param options 见 {@link RegisterLimiterOptions}。
 * @returns 限速器实例。
 * @throws {TypeError} `limitPerMinute` 不是非负整数（编程错误 —— 配置层已经拦过一遍，
 *   到这里还错说明有人在代码里写死了非法值，必须炸在开发机上）。
 */
export function createRegisterLimiter(options: RegisterLimiterOptions): RegisterLimiter {
  const { limitPerMinute } = options;
  const now = options.now ?? (() => new Date());

  if (!Number.isInteger(limitPerMinute) || limitPerMinute < 0) {
    throw new TypeError(
      `createRegisterLimiter：limitPerMinute 必须是非负整数（实测 ${String(limitPerMinute)}）；` +
        "0 表示关闭限速"
    );
  }

  /** 关闭态：恒放行且**不记账**（不记账是刻意的：开关关了就不该留下任何状态）。 */
  if (limitPerMinute === 0) {
    return {
      limitPerMinute,
      check: () => ({ allowed: true, retryAfterSeconds: 0 }),
      size: () => 0,
    };
  }

  /** IP → 窗口内的时间戳（升序，天然按到达顺序）。 */
  const hits = new Map<string, number[]>();

  /** key 级清扫：删掉所有"窗口内 0 次命中"的 IP。 */
  const pruneKeys = (cutoff: number): void => {
    if (hits.size <= PRUNE_KEY_THRESHOLD) return;
    for (const [key, stamps] of hits) {
      const last = stamps.length === 0 ? null : stamps[stamps.length - 1];
      if (last === null || last <= cutoff) hits.delete(key);
    }
  };

  return {
    limitPerMinute,
    check(clientKey: string): RegisterLimiterDecision {
      // 空 key 不能并成同一个桶 —— 那会让"取不到 IP"的请求互相消耗配额；
      // 但也不能放行（否则缺失 IP 就成了绕过路径）。统一记在 "(unknown)" 下并照常计数。
      const key = typeof clientKey === "string" && clientKey.trim() !== "" ? clientKey : "(unknown)";
      const at = now().getTime();
      const cutoff = at - REGISTER_RATE_WINDOW_MS;

      const previous = hits.get(key) ?? [];
      // prune：只留窗口内的（这一步同时保证内存上界 = limit）。
      const recent = previous.filter((stamp) => stamp > cutoff);

      if (recent.length >= limitPerMinute) {
        // 窗口内已满：下一次可放行的时刻 = 最早那次 + 60s。
        const oldest = recent[0];
        const retryAfterSeconds = Math.max(1, Math.ceil((oldest + REGISTER_RATE_WINDOW_MS - at) / 1000));
        hits.set(key, recent);
        pruneKeys(cutoff);
        return { allowed: false, retryAfterSeconds };
      }

      recent.push(at);
      hits.set(key, recent);
      pruneKeys(cutoff);
      return { allowed: true, retryAfterSeconds: 0 };
    },
    size: () => hits.size,
  };
}
