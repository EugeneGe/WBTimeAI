import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { useAuthStore } from "@/stores/authStore";

import { permissionService } from "@/services/permission";

/**
 * 能力检查 hook（W3 / T2-18；设计 §2.10.2）。
 *
 * 🔴 数据源是**后端**（`GET /permissions/check?cap=...`）——前端**不做**本地 capability
 *    推断（W3 裁定 §4.2）。`cap` 为空时不请求。
 *
 * 说明：本文件是对 §8.2 hooks 清单的**加性**补充（`SkillBuilder` / `McpManager` 的
 * 动作级守卫需实时 capability 判定）；既有 `lib/permission.ts::can()` 仍复用。
 */
export function usePermissionCheck(cap: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.permissionCheck(cap ?? ""),
    queryFn: () => permissionService.check(cap as string),
    enabled: isAuthenticated && Boolean(cap),
  });
}
