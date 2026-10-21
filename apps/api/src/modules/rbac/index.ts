/**
 * T2-05 · RBAC 模块出口。
 *
 * 分层（**不要串层**，计划 §4.3）：
 *
 * | 层 | 文件 | 职责 | 不做什么 |
 * |---|---|---|---|
 * | 取数（IO） | `permission-resolver.ts` | `membership(ACTIVE)` → `role_permission` → `permission.code` | 不判权、不抛 403 |
 * | 判定（纯） | `authorization.ts` | `code ∈ codes ∪ {"*"}`；`check` 的四字段结论 | 不做 IO、不表达 HTTP 状态 |
 * | Router（守卫） | `guard.ts` | `requirePermission(code)`，失败抛 403 / 未认证抛 401 | **不挂任何路由**（谁挂谁负责） |
 * | repositories | `@wbtime/db`（T2-03 成品） | 只做 scope 过滤 | **不判权限**（判权下推会把跨租户 404 变成 403，破 I-1） |
 *
 * V0.2.0 的 4 路由族（登录 / 组织 / 权限 / 凭证，归 T2-07）**一个守卫都不挂** ——
 * py 线实测那 4 族 router 只有 `CurrentUser`、没有 `require_permission`，等价实现也不加
 * （计划 §8 J-6b 注解）。本模块只提供能力，不替 dispatch 方做决定。
 */

export {
  createPrincipal,
  type CapabilityDecision,
  type CapabilityReason,
  type CapabilitySource,
  type Principal,
  type PrincipalInit,
} from "./principal.js";
export { checkCapability, decideCapability, hasPermission } from "./authorization.js";
export {
  buildPrincipal,
  loadPrincipal,
  resolvePermissionCodes,
  type BuildPrincipalInput,
  type PermissionResolverDeps,
} from "./permission-resolver.js";
export {
  PERMISSION_DENIED_STATUS,
  UNAUTHORIZED_STATUS,
  forbiddenFrom,
  requirePermission,
} from "./guard.js";
