/**
 * T2-05 · 权限判定（纯函数，**零 IO**）。
 *
 * 判定式逐字对齐计划 §4.1：
 *
 *     hasPermission = code ∈ codes ∪ {"*"}      （`*` = ADMIN_PERMISSION 通配）
 *
 * 三条边界（都有测试钉住，且都不是「顺手加的」）：
 *
 * 1. **空码不放行**。若不做这条，持有 `*` 的主体对**空字符串**也会返回「有权限」——
 *    而空码一旦进到业务里就是「没指定要什么权限」，那是最危险的一种「通过」。
 * 2. **`*` 不是「也能被当成一个普通码来查」**：主体有 `*` 时查 `*` 返回 true（它确实含
 *    `*`），查任何具体码也返回 true（通配语义）。
 * 3. **不做大小写/空白归一化**。权限码是契约字面量（`marketplace:import`），
 *    归一化会让 `Marketplace:Import` 这种拼写错误悄悄生效；宁可判 DENY 让人发现。
 */

import { ADMIN_PERMISSION } from "@wbtime/db";

import type {
  CapabilityDecision,
  CapabilityReason,
  CapabilitySource,
  Principal,
} from "./principal.js";

/**
 * 主体是否拥有某个权限码（计划 §4.1 原文判定式）。
 *
 * @param principal 已认证主体（`permissionCodes` 已由取数层按 `ACTIVE` 过滤）。
 * @param capability 权限码（契约字面量，如 `marketplace:import`）。
 * @returns 拥有为 `true`；空码 / 非字符串一律 `false`。
 */
export function hasPermission(principal: Principal, capability: string): boolean {
  if (!isWellFormedCapability(capability)) return false;
  const codes = principal.permissionCodes;
  // 通配优先：一次 `includes` 就够，不需要先扫全表。
  return codes.includes(ADMIN_PERMISSION) || codes.includes(capability);
}

/**
 * 判定并给出**四字段**结论（`GET /permissions/check` 的语义本体）。
 *
 * 注意这不是「判权 + 抛错」：本函数**永不抛**，也永不表达 HTTP 状态。
 * 「没有权限」在这里是一个**正常结果**（`allowed:false, effect:"DENY"`），
 * 不是异常 —— 这正是 J-6a 要求「`check` 无码时 HTTP 仍是 200」的同一条语义：
 * 查询判定结果 ≠ 执行被判定的动作。把两者混在一起，就会出现
 * 「用 check 探一下自己有没有权限，结果先被自己的守卫 403 掉了」的荒谬链路。
 *
 * @param principal 已认证主体。
 * @param capability 被询问的能力码。
 * @returns 四字段结论（`capability` / `allowed` / `effect` / `reason`）。
 */
export function decideCapability(principal: Principal, capability: string): CapabilityDecision {
  if (!isWellFormedCapability(capability)) {
    // 码本身不合法：仍是「拒绝」，`source` 归入 `default_deny`（py 侧无此场景，
    // 不发明新枚举值；差异体现在 `reason === "capability_malformed"`）。
    return decision(capability, false, "capability_malformed", "default_deny");
  }
  if (principal.permissionCodes.includes(ADMIN_PERMISSION)) {
    return decision(capability, true, "wildcard_admin", "wildcard_admin");
  }
  if (principal.permissionCodes.includes(capability)) {
    return decision(capability, true, "permission_granted", "explicit_grant");
  }
  return decision(capability, false, "permission_not_granted", "default_deny");
}

/**
 * `GET /permissions/check` 的 **service 层**（HTTP 适配归 T2-07）。
 *
 * 与 {@link decideCapability} 是同一个判定的两个名字：保留这层入口是为了让
 * 「HTTP 层调什么」有明确落点，而不是让路由去 import 一个叫 `decide*` 的内部函数。
 *
 * @param principal 已认证主体。
 * @param capability 查询参数 `cap`。
 * @returns 四字段结论；**恒为成功结果**（无码也是 `DENY` + 200，不是 4xx）。
 */
export function checkCapability(principal: Principal, capability: string): CapabilityDecision {
  return decideCapability(principal, capability);
}

/** 唯一构造点：保证 `allowed` 与 `effect` 不可能各说一套。 */
function decision(
  capability: string,
  allowed: boolean,
  reason: CapabilityReason,
  source: CapabilitySource,
): CapabilityDecision {
  return {
    capability,
    allowed,
    effect: allowed ? "ALLOW" : "DENY",
    reason,
    source,
  };
}

/** 能力码是否「形状合法」：非空字符串（不做归一化，理由见文件头第 3 条）。 */
function isWellFormedCapability(capability: unknown): capability is string {
  return typeof capability === "string" && capability.trim() !== "";
}
