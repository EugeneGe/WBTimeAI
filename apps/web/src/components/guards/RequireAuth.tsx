import type { ReactNode } from "react";

/**
 * 登录态守卫（V0.4.5 B4 · F-19.1 **放宽**）。
 *
 * 变更（F-19.1）：由「未登录 → 重定向 `/login`」改为 **匿名亦放行**——整个应用外壳
 * （Rail / Sidebar / Topbar / Outlet）匿名可达，未登录照常渲染外壳；受限操作改由
 * {@link useAuthGateStore} 的 `requireAuth(cb)` 在调用点按需拦截至**登录弹窗**。
 *
 * - **组件与 `to`/`replace` 语义保留**：作为路由守护位继续包裹 `<App />`（`router.tsx` 引用不变）；
 * - **会话判定语义保留**：内存 access 或 localStorage refresh 任一存在 = 有会话，该语义仍由
 *   `lib/token.ts` 的 `hasStoredSession()` 提供，并被 `stores/authGateStore.ts` 复用为门控判据；
 * - **已登录路径零变更**：非授权逻辑（`useMe` / `navigate("/chat")` / 401 刷新 / `redirectToLogin`）
 *   完全不受影响。
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
