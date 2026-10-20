import { api } from "@/lib/api";
import type {
  CreateProjectRequest,
  EnvironmentResponse,
  FileContentResponse,
  FileObjectResponse,
  ProjectResponse,
} from "@/types";

/** 文件列表查询参数（`GET /workspaces/{id}/files`）。 */
export interface ListWorkspaceFilesParams {
  prefix?: string | null;
  limit?: number;
  offset?: number;
}

/** 列表分页参数。 */
export interface PageParams {
  limit?: number;
  offset?: number;
}

/**
 * 项目 / 工作区文件 / 运行环境服务（`/projects` + `/workspaces/{id}/files|environment`，W10 / T2-49）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 * 🔴 文件能力未装配时后端返回 **503**（`DEPENDENCY_MISSING`）——由 Page 层捕获渲染降级态。
 */
export const projectService = {
  /** 项目列表（`workspace_id` 必填）。 */
  list(workspaceId: string, params?: PageParams): Promise<ProjectResponse[]> {
    return api
      .get<ProjectResponse[]>("/projects", {
        params: { workspace_id: workspaceId, limit: params?.limit, offset: params?.offset },
      })
      .then((r) => r.data);
  },

  /** 创建项目。 */
  create(payload: CreateProjectRequest): Promise<ProjectResponse> {
    return api.post<ProjectResponse>("/projects", payload).then((r) => r.data);
  },

  /** 项目详情（跨租户 / 不存在 → 404）。 */
  get(id: string): Promise<ProjectResponse> {
    return api.get<ProjectResponse>(`/projects/${id}`).then((r) => r.data);
  },

  /** 工作区文件清单（经 `Storage`；参数为 `prefix`）。 */
  listFiles(workspaceId: string, params?: ListWorkspaceFilesParams): Promise<FileObjectResponse[]> {
    return api
      .get<FileObjectResponse[]>(`/workspaces/${workspaceId}/files`, {
        params: {
          prefix: params?.prefix ?? undefined,
          limit: params?.limit,
          offset: params?.offset,
        },
      })
      .then((r) => r.data);
  },

  /** 读取工作区文件内容（经 `Storage`；base64 承载）。 */
  readFile(workspaceId: string, path: string): Promise<FileContentResponse> {
    return api
      .get<FileContentResponse>(`/workspaces/${workspaceId}/files/content`, { params: { path } })
      .then((r) => r.data);
  },

  /** 运行环境清单（敏感项 masked）。 */
  listEnvironments(workspaceId: string): Promise<EnvironmentResponse[]> {
    return api
      .get<EnvironmentResponse[]>(`/workspaces/${workspaceId}/environment`)
      .then((r) => r.data);
  },

  /** 运行环境详情（跨租户 / 不存在 → 404；敏感项 masked）。 */
  getEnvironment(workspaceId: string, environmentId: string): Promise<EnvironmentResponse> {
    return api
      .get<EnvironmentResponse>(`/workspaces/${workspaceId}/environment/${environmentId}`)
      .then((r) => r.data);
  },
};
