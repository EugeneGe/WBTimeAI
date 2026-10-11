import { api } from "@/lib/api";
import type { ToolPermissionRequest, ToolPermissionResponse, ToolResponse } from "@/types";

/**
 * Tool 服务（`/tools/*` API，W7 / T1-34）。
 *
 * - 内置工具浏览器（首批 5 个 Tool）；
 * - 权限配置（agent × tool × effect × scope）：列表（按 `agent_id`）/ 授予 / 撤销。
 */
export const toolService = {
  /** 内置工具浏览器（注册表内工具）。 */
  list(): Promise<ToolResponse[]> {
    return api.get<ToolResponse[]>("/tools").then((r) => r.data);
  },
  /** 某 Agent 的 Tool 权限列表。 */
  listPermissions(agentId: string): Promise<ToolPermissionResponse[]> {
    return api
      .get<ToolPermissionResponse[]>("/tools/permissions", { params: { agent_id: agentId } })
      .then((r) => r.data);
  },
  /** 授予 / 更新一条 Tool 权限（`effect ∈ {ALLOW, DENY}`）。 */
  grant(payload: ToolPermissionRequest): Promise<ToolPermissionResponse> {
    return api.post<ToolPermissionResponse>("/tools/permissions", payload).then((r) => r.data);
  },
  /** 撤销一条 Tool 权限（幂等）。 */
  revoke(permissionId: string): Promise<void> {
    return api.delete<void>(`/tools/permissions/${permissionId}`).then(() => undefined);
  },
};
