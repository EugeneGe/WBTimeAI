import { api } from "@/lib/api";
import type {
  CreateWorkspaceRequest,
  UpdateWorkspaceSettingsRequest,
  WorkspaceResponse,
} from "@/types";

/** 工作区服务（创建 / 列表 / 详情 / 更新设置）。 */
export const workspaceService = {
  /** 创建工作区（需 `workspace:create` 权限）。 */
  create(payload: CreateWorkspaceRequest): Promise<WorkspaceResponse> {
    return api.post<WorkspaceResponse>("/workspaces", payload).then((r) => r.data);
  },
  /** 工作区列表（当前租户）。 */
  list(): Promise<WorkspaceResponse[]> {
    return api.get<WorkspaceResponse[]>("/workspaces").then((r) => r.data);
  },
  /** 工作区详情（跨租户 → 404）。 */
  get(id: string): Promise<WorkspaceResponse> {
    return api.get<WorkspaceResponse>(`/workspaces/${id}`).then((r) => r.data);
  },
  /** 更新工作区设置（需 `workspace:update` 权限）。 */
  updateSettings(id: string, payload: UpdateWorkspaceSettingsRequest): Promise<WorkspaceResponse> {
    return api.put<WorkspaceResponse>(`/workspaces/${id}/settings`, payload).then((r) => r.data);
  },
};
