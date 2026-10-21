/**
 * T2-05 · RBAC 的**主体**与**判决形状**（纯类型 + 纯构造函数，零 IO）。
 *
 * `Principal` 是本项目对「已认证主体」的唯一表达（计划 §4.1 术语表）。它刻意**不是**
 * 一个「能自己去查库」的对象：判权需要的三跳取数（`membership.role_id` →
 * `role_permission` → `permission.code`）在 `permission-resolver.ts` 里，由认证层
 * （T2-04）在建立请求上下文时**一次性**跑完并把码集合塞进 `Principal`。
 *
 * 这样切分的两个好处：
 *  1. 判定层（{@link hasPermission} / `checkCapability`）是纯函数 —— 可以直接单测
 *     「有码/无码/通配」，不必为每条断言起一次真库；
 *  2. 守卫（`requirePermission`）里**没有** IO —— 一个 403 的代价永远是一次内存查表，
 *     不会因为「判权时又查了三次库」把 p99 拖长，也不会在流式响应中途才失败。
 */

import type { PermissionEffect } from "@wbtime/db";

/** 已认证主体（计划 §4.1）。 */
export interface Principal {
  /** 用户 id（`user.id`）。 */
  readonly userId: string;
  /** 租户 id —— 一切数据访问的 scope 起点。 */
  readonly tenantId: string;
  /** 工作区 id（多工作区表用；`null` = 该租户下全部工作区）。 */
  readonly workspaceId: string | null;
  /** 已生效成员关系覆盖的组织 id 集合（三级过滤的中间层）。 */
  readonly organizationIds: readonly string[];
  /**
   * 已合流的权限码（可能含通配 `*`）。
   *
   * **只允许**由 `resolvePermissionCodes()` 产出：它只吃 `membership.status = ACTIVE`
   * 的成员关系（`MembershipRepo.listActiveRoleIdsByUser`），因此「非 ACTIVE 不授权」
   * 是取数层的性质，不是判定层再判一次的规则 —— 判定层拿到的码**已经**是授权过的。
   */
  readonly permissionCodes: readonly string[];
}

/** 主体构造入参（与 {@link Principal} 同形，单独命名以便调用方按需组装）。 */
export type PrincipalInit = Principal;

/**
 * 构造一个 `Principal`，并挡住「空 id」这类会让 scope 形同虚设的入参。
 *
 * @param init 主体字段。
 * @returns 冻结后的主体（防止下游在判定途中被改写 —— 判权依赖的值不该可变）。
 * @throws {TypeError} `userId` / `tenantId` 为空。
 */
export function createPrincipal(init: PrincipalInit): Principal {
  assertNonEmpty(init.userId, "userId");
  assertNonEmpty(init.tenantId, "tenantId");
  return Object.freeze({
    userId: init.userId,
    tenantId: init.tenantId,
    workspaceId: init.workspaceId ?? null,
    organizationIds: Object.freeze([...init.organizationIds]),
    permissionCodes: Object.freeze([...init.permissionCodes]),
  });
}

/** 判定原因（稳定字面量，供日志归因）。 */
export type CapabilityReason =
  /** 命中通配 `*` ⇒ 视为拥有全部权限码。 */
  | "wildcard_admin"
  /** 命中具体码。 */
  | "permission_granted"
  /** 码合法但主体没有它。 */
  | "permission_not_granted"
  /** 请求的能力码本身不合法（空串 / 非字符串）—— 不是「没权限」，是「问错了」。 */
  | "capability_malformed";

/**
 * 判定**来源**（机器枚举，与 `reason` 分工：`source` 给程序分支，`reason` 给人看）。
 *
 * ⚠️ 这一项是 **J-11 oracle 实测倒逼出来的**：py 线 `GET /permissions/check` 的 `data`
 * 实测是 **5 个键**（`allowed / capability / effect / reason / source`），比计划 J-6a 写的
 * 「四字段」多一个 `source`。J-11 比的是「`data` 键集合」，故 TS 侧必须也返回 5 键
 * （依据：`02-施工/施工记录/T2-11-oracle.md` §3-1 的原始响应）。
 *
 * py 实测到的 `source` 值只有 `default_deny`（本轮没造出「有码用户」）；
 * `explicit_grant` / `wildcard_admin` 是本侧按同一命名风格给出的值域，
 * **未与 py 逐值对过**（J-11 不比 value，已登记为遗留 L-1/L-2）。
 */
export type CapabilitySource = "wildcard_admin" | "explicit_grant" | "default_deny";

/**
 * 一次能力判定的结论（**J-6a 的四字段恒在 + 第 5 键 `source`**）。
 *
 * `effect` 与 `allowed` 必须同步（`allowed === true ⇔ effect === "ALLOW"`）：
 * 这两个字段不是冗余 —— `effect` 是契约口径（`ALLOW`/`DENY`），`allowed` 是布尔便捷位；
 * 但若二者可以各说一套，前端就能拿到「allowed=false 且 effect=ALLOW」这种自相矛盾的响应。
 * 因此本类型只由 {@link decideCapability} 构造，且该函数**没有**产生不一致的分支。
 */
export interface CapabilityDecision {
  /** 被询问的能力码（原样回显，便于调用方对账）。 */
  readonly capability: string;
  /** 布尔便捷位。 */
  readonly allowed: boolean;
  /** 契约效果值。 */
  readonly effect: PermissionEffect;
  /** 原因（人类可读的归类，见 {@link CapabilityReason}）。 */
  readonly reason: CapabilityReason;
  /** 判定来源（机器枚举，见 {@link CapabilitySource}；py 同名字段实测存在）。 */
  readonly source: CapabilitySource;
}

/** 非空字符串断言（空 id 会让 scope 形同虚设，属编程错误）。 */
function assertNonEmpty(value: string, field: string): void {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(`Principal 的 ${field} 必须是非空字符串`);
  }
}
