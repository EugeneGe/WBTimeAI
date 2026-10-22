/**
 * V0.3.1 · G031-SPK · 深度守卫（**纯判定**，零 IO）。
 *
 * 为什么单独成文件：深度是四道闸（深度 / 预算 / 权限 / 取消）里唯一**不碰数据库
 * 就能判**的一道 —— 判定与落库分离，测试才能只喂 `{depth, maxDepth}` 两个数
 * （判据 S-3-2 就是这么调的），而不必先造一条 run 链。
 *
 * 双向口径（判据 S-3-2 逐字）：
 *   - `depth=0 / maxDepth=1` ⇒ **放行**（父 run 必须仍能派生 —— 只测"拒绝"会被
 *     "一律拒绝"的假实现蒙混过关）；
 *   - `depth=1 / maxDepth=1` ⇒ **必拒**（单层委派，D1 ④：子 run 行数 == 0）。
 *
 * 返回形状（防假绿）：判据 `normalizeGuardOutcome` 只认 `{allowed: boolean}` /
 * `{conflict / blocked / rejected / exceeded: boolean}` 等已声明形态 —— 本函数恒返回
 * `{allowed, reason, depth, maxDepth}`，`undefined` 会被判 unrecognized ⇒ 红。
 */

import { MAX_SUBAGENT_DEPTH } from "@wbtime/domain";

/** 深度判定的入参（两个键都可缺省：缺省 depth = 0（根），缺省 maxDepth = 域常量）。 */
export interface DepthCheckArgs {
  /** 当前 run 的深度（父 run = 0）。 */
  readonly depth?: number;
  /** 允许的最大深度（缺省 {@link MAX_SUBAGENT_DEPTH} = 1）。 */
  readonly maxDepth?: number;
}

/** 深度判定的结果。 */
export interface DepthCheckResult {
  /** `true` = 允许本次派生。 */
  readonly allowed: boolean;
  /** 拒绝原因；`OK` = 放行。 */
  readonly reason: "OK" | "DEPTH_EXCEEDED" | "INVALID_DEPTH" | "INVALID_MAX_DEPTH";
  /** 归一后的 depth（入参缺省 ⇒ 0）。 */
  readonly depth: number;
  /** 归一后的 maxDepth（入参缺省 ⇒ 域常量）。 */
  readonly maxDepth: number;
}

/**
 * 判"在 `depth` 这一层还能不能再派生"。
 *
 * 守卫**不得对垃圾输入 fail-open**：`depth` / `maxDepth` 非整数或越界 ⇒ 一律拒绝
 * （`INVALID_*`），绝不静默夹取 —— 静默夹取会把调用方的编程错误变成
 * "看起来正常、实际多放了一层"，正是本项目要消灭的哑失败。
 */
export function isDepthAllowed(args: DepthCheckArgs): DepthCheckResult {
  const maxDepth = args.maxDepth === undefined ? MAX_SUBAGENT_DEPTH : args.maxDepth;
  const depth = args.depth === undefined ? 0 : args.depth;

  const maxOk = Number.isInteger(maxDepth) && maxDepth >= 1;
  const depthOk = Number.isInteger(depth) && depth >= 0;
  if (!maxOk) {
    return { allowed: false, reason: "INVALID_MAX_DEPTH", depth, maxDepth };
  }
  if (!depthOk) {
    return { allowed: false, reason: "INVALID_DEPTH", depth, maxDepth };
  }

  const allowed = depth < maxDepth;
  return {
    allowed,
    reason: allowed ? "OK" : "DEPTH_EXCEEDED",
    depth,
    maxDepth,
  };
}
