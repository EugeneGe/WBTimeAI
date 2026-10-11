import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { hasStoredSession } from "@/lib/token";
import { useAuthStore } from "@/stores/authStore";

/** 登录态守卫：未登录 → 重定向 `/login`（保留来源路径）。 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const location = useLocation();

  // 内存 access 可能为空（刷新页面），此时以 localStorage 中的 refresh 判定会话。
  if (!isAuthenticated && !hasStoredSession()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
