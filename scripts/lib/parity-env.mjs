/**
 * `test:parity:pg` 的 **RESET 决策**（纯函数，零 IO —— 这样守卫单测能直接钉它）。
 *
 * 背景（dev 服务器实测）：`j11-19ops.test.mjs` 有 **3 个 test，各自 `makeParityApp()`**。
 * SQLite 档每条都是新的 `:memory:`，互不影响；PG 档连的是**同一个库** ⇒
 * 第 2、3 个 test 必然撞 harness 的闸 2（`已存在 public.tenant（非空库）`）。
 *
 * 因此官方 runner **必须**默认带上 `WBTIME_PG_RESET=1`，否则"按文档执行"会得到
 * `# pass 1 / # fail 2` —— 那是「文档命令跑不通」，不是安全闸的正确用法。
 *
 * 决策表（**只有这三行**，不猜布尔字面量）：
 *
 * | 用户给的值 | 子进程收到的值 | 语义 |
 * |---|---|---|
 * | 未设置 / 空 | `"1"` | 默认开（3 个 test 共用一库，必须清） |
 * | `"0"` | **不注入**（沿用用户的 `"0"`） | 显式关：库非空时按闸 2 报错，这是尊重用户 |
 * | 其它（`"1"` / `"true"` / …） | 归一成 `"1"` | 只认 harness 认识的唯一直 |
 *
 * ⚠️ 归一成 `"1"` 不是"宽容"，而是**必要性**：harness 的判定是 `=== "1"`
 * （见 `j11-harness.mjs` 的 `PG_RESET_ENV` 用法），若把 `"true"` 原样传下去，
 * 用户以为开了、实际没开 —— 那种"看起来生效"的开关比没有更危险。
 */

/** RESET 开关的环境变量名（与 harness 的 `PG_RESET_ENV` 同名）。 */
export const PG_RESET_ENV = "WBTIME_PG_RESET";

/** harness 唯一认可的开值。 */
export const PG_RESET_ON = "1";

/** 显式关的取值。 */
export const PG_RESET_OFF = "0";

/**
 * 计算要注入给子进程的 RESET 环境变量。
 *
 * @param {Record<string, string|undefined>} [env] 调用方环境（默认 `process.env`）。
 * @returns {{env: Record<string, string>, mode: "on"|"off", reason: "default"|"user-on"|"user-off"}}
 *   `env` 是要**合并**进子进程环境的增量；`mode` 供日志使用。
 */
export function parityResetEnv(env = process.env) {
  const raw = String(env[PG_RESET_ENV] ?? "").trim();

  if (raw === PG_RESET_OFF) {
    // 显式关：**不注入**任何值（子进程会从 process.env 继承用户的 "0"），
    // 于是 harness 的闸 2 会在库非空时报错 —— 这正是"尊重用户"的含义。
    return { env: {}, mode: "off", reason: "user-off" };
  }
  if (raw === "" || raw === PG_RESET_ON) {
    return { env: { [PG_RESET_ENV]: PG_RESET_ON }, mode: "on", reason: raw === "" ? "default" : "user-on" };
  }
  // 其它写法一律归一成 harness 认识的 "1"（理由见文件头注）。
  return { env: { [PG_RESET_ENV]: PG_RESET_ON }, mode: "on", reason: "user-on" };
}

/**
 * 一行的 RESET 说明（启动时打印，让"开了没开"在日志里可核）。
 *
 * @param {ReturnType<typeof parityResetEnv>} decision {@link parityResetEnv} 的返回值。
 * @returns {string} 形如 `[run-parity-pg] RESET=on（…）`。
 */
export function describeReset(decision) {
  const label = decision.mode === "on" ? "on" : "off";
  if (decision.mode === "on") {
    return (
      `[run-parity-pg] RESET=${label}` +
      `（3 个 test 共用同一 parity 库；仅对库名含 parity 且非共享库生效）`
    );
  }
  return (
    `[run-parity-pg] RESET=${label}` +
    `（尊重 ${PG_RESET_ENV}=${PG_RESET_OFF}：库非空时会按闸 2 报错，不会自动清库）`
  );
}
