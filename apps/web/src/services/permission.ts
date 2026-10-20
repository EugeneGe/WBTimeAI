import { api } from "@/lib/api";
import type { PermissionCheckResponse } from "@/types";

/**
 * 权限服务（`/permissions/*` API，W3 / T2-18；设计 §2.10.2）。
 *
 * 🔴 `can(cap)` 的**唯一数据源是后端**（`GET /permissions/check?cap=...`）——
 *    前端 SDK **不做**本地 capability 推断（W3 裁定 §4.2）。
 */
export const permissionService = {
  /** 判定当前用户是否具备某 capability（如 `tool:git.commit`）。 */
  check(cap: string): Promise<PermissionCheckResponse> {
    return api
      .get<PermissionCheckResponse>("/permissions/check", { params: { cap } })
      .then((r) => r.data);
  },
};
