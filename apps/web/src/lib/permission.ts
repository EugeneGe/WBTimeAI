import { useAuthStore } from "@/stores/authStore";

/**
 * 权限 SDK（与后端最小 RBAC 语义对齐，§2T.0.1）。
 *
 * 后端 `admin = *` **通配放行**；前端 `can(code)` **必须**同样支持 `*` 通配：
 * `permission.includes(code) || permission.includes("*")`。
 */

/** 通配权限码（对齐后端 `admin = *`）。 */
export const WILDCARD_PERMISSION = "*";

/** 纯函数：判断权限集是否满足某权限码（含 `*` 通配）。 */
export function hasPermission(permissions: readonly string[], code: string): boolean {
  return permissions.includes(code) || permissions.includes(WILDCARD_PERMISSION);
}

/** 非 Hook 版本：基于当前 store 快照判定（供事件回调等使用）。 */
export function can(code: string): boolean {
  return hasPermission(useAuthStore.getState().permissions, code);
}

/** Hook 版本：返回当前权限集与 `can` 断言（随 store 变化自动重渲染）。 */
export function usePermission(): {
  permissions: string[];
  can: (code: string) => boolean;
} {
  const permissions = useAuthStore((state) => state.permissions);
  return {
    permissions,
    can: (code: string) => hasPermission(permissions, code),
  };
}
