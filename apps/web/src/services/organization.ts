import { api } from "@/lib/api";
import type { OrganizationResponse } from "@/types";

/** 组织服务（Phase 0 最小实现：列表 / 详情）。 */
export const organizationService = {
  /** 组织列表。 */
  list(): Promise<OrganizationResponse[]> {
    return api.get<OrganizationResponse[]>("/organizations").then((r) => r.data);
  },
  /** 组织详情（跨租户 / 不存在 → 404）。 */
  get(id: string): Promise<OrganizationResponse> {
    return api.get<OrganizationResponse>(`/organizations/${id}`).then((r) => r.data);
  },
};
