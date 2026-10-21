/**
 * T2-05 · RBAC 三层合流的**取数层**（唯一有 IO 的地方）。
 *
 *     membership.role_id  →  role_permission.permission_id  →  permission.code
 *     （本文件第 ① 跳）        （`RolePermissionCatalog`）        （`PermissionCatalog`）
 *
 * 三跳分别落在谁身上（计划 §4.1 与 §2 表）：
 *  ① `MembershipRepo.listActiveRoleIdsByUser` —— scoped（带 `tenant_id` 谓词），
 *     且**只取 `status = ACTIVE`** 的成员关系；
 *  ② `RolePermissionCatalog.listCodesByRoleIds` —— 白名单通道，**只吃 scoped 侧筛过的 role id**；
 *  ③ 第 ③ 跳已封装在 ② 内部（`listCodesByRoleIds` 会再查 `permission.code`）。
 *
 * 「`membership.status` 非 `ACTIVE` 不授予权限」这条规则**只在这里实现一次** ——
 * 靠的是调用 `listActiveRoleIdsByUser` 而不是 `listByUser`。判定层（`hasPermission`）
 * 拿到的码已经是授权过的码，它不再重复判状态；两处都判会让人误以为「漏了其中一处还有救」，
 * 实际上只会让「哪一处才是真闸门」变得含糊。
 *
 * 入参刻意收 `ScopedRef` 而不是裸 `string`：裸 id 在类型层就过不去（T2-03 的品牌约束），
 * 这样「判权路径上偷偷跨租户」在编译期就不可能，而不是靠 code review。
 */

import {
  MembershipRepo,
  RolePermissionCatalog,
  ScopeError,
  type ScopedRef,
} from "@wbtime/db";

import { createPrincipal, type Principal } from "./principal.js";

/** 取数依赖（构造成本由调用方承担，便于复用同一实例 / 测试注入）。 */
export interface PermissionResolverDeps {
  /** `membership`（scoped）—— 第 ① 跳。 */
  readonly memberships: MembershipRepo;
  /** `role_permission` → `permission.code`（白名单第 ②③ 跳）。 */
  readonly rolePermissions: RolePermissionCatalog;
}

/**
 * 解析某用户在当前 scope 下的全部权限码。
 *
 * @param deps 取数依赖。
 * @param userRef 用户在**本 scope** 下的引用（`scope.ref(userId)` 产出）。
 * @returns 去重后的权限码；无 ACTIVE 成员关系时返回 `[]`。
 * @throws {ScopeError} `userRef` 不属于当前 scope（纵深防御：正常调用路径不会命中）。
 */
export async function resolvePermissionCodes(
  deps: PermissionResolverDeps,
  userRef: ScopedRef,
): Promise<readonly string[]> {
  const roleIds = await deps.memberships.listActiveRoleIdsByUser(userRef);
  if (roleIds.length === 0) return [];

  const codes = await deps.rolePermissions.listCodesByRoleIds(roleIds);
  // 去重但保持发现顺序：role_permission 可能给多个角色授同一个码，重复项会让
  // 下游「码数量」类断言（以及将来的审计计数）失真。
  const seen = new Set<string>();
  for (const code of codes) {
    if (typeof code === "string" && code !== "") seen.add(code);
  }
  return [...seen];
}

/** 建立 `Principal` 的入参（取数层输出的自然形态）。 */
export interface BuildPrincipalInput {
  readonly userId: string;
  readonly tenantId: string;
  readonly workspaceId?: string | null;
  readonly organizationIds?: readonly string[];
  readonly permissionCodes: readonly string[];
}

/**
 * 用「已解析的码」组装 `Principal`。
 *
 * 单独一个函数而不是让调用方手拼对象：`createPrincipal` 会做空 id 校验与冻结，
 * 而手拼对象会绕过这两件事 —— 然后某天在 `Scope` 构造处才炸，离根因很远。
 *
 * @param input 主体字段 + 已解析的权限码。
 * @returns 冻结的主体。
 */
export function buildPrincipal(input: BuildPrincipalInput): Principal {
  return createPrincipal({
    userId: input.userId,
    tenantId: input.tenantId,
    workspaceId: input.workspaceId ?? null,
    organizationIds: input.organizationIds ?? [],
    permissionCodes: input.permissionCodes,
  });
}

/**
 * 「取数 + 组装」一步到位（认证层建立请求上下文时用这一个入口）。
 *
 * @param deps 取数依赖。
 * @param args `scope`、用户引用与主体字段。
 * @returns 冻结的主体（`permissionCodes` 已按 ACTIVE 过滤）。
 */
export async function loadPrincipal(
  deps: PermissionResolverDeps,
  args: {
    readonly userRef: ScopedRef;
    readonly userId: string;
    readonly tenantId: string;
    readonly workspaceId?: string | null;
    readonly organizationIds?: readonly string[];
  },
): Promise<Principal> {
  if (args.userRef.tenantId !== args.tenantId) {
    // 拿 A 租户的引用去建 B 租户的主体，等同于把 scope 拆成两半。当场拒绝，
    // 不留「看起来能跑」的路径。
    throw new ScopeError("loadPrincipal：userRef 的 tenantId 与 Principal 的 tenantId 不一致");
  }
  const permissionCodes = await resolvePermissionCodes(deps, args.userRef);
  return buildPrincipal({
    userId: args.userId,
    tenantId: args.tenantId,
    workspaceId: args.workspaceId ?? null,
    organizationIds: args.organizationIds ?? [],
    permissionCodes,
  });
}
