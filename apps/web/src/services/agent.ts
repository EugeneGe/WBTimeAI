import { api } from "@/lib/api";
import type {
  AgentResponse,
  AgentStudioDraft,
  AgentVersionResponse,
  CreateAgentRequest,
  PublishRequest,
  UpdateAgentRequest,
} from "@/types";
import { draftToPublishRequest } from "@/types";

/**
 * Agent 服务（`/agents` 系列 API，W7 / T1-33）。
 *
 * - 列表 / 创建 / 详情 / 更新（`PUT /agents/{id}`）；
 * - 版本列表（不可变快照）/ 发布（**发布即切换 `current_version_id`**）。
 *
 * 运行（SSE）不在此处，见 `services/chat.ts`（`fetch` 流式）。
 *
 * W8 / T2-41 追加：{@link agentService.publishDraft}（**加性**，由 Studio 草稿合成发布）。
 */
export const agentService = {
  /** Agent 列表（当前租户；`page` / `page_size` 可选）。 */
  list(params?: { page?: number; page_size?: number }): Promise<AgentResponse[]> {
    return api.get<AgentResponse[]>("/agents", { params }).then((r) => r.data);
  },
  /** 创建 Agent（`DRAFT`，无当前版本）。 */
  create(payload: CreateAgentRequest): Promise<AgentResponse> {
    return api.post<AgentResponse>("/agents", payload).then((r) => r.data);
  },
  /** Agent 详情（跨租户 / 不存在 → 404）。 */
  get(id: string): Promise<AgentResponse> {
    return api.get<AgentResponse>(`/agents/${id}`).then((r) => r.data);
  },
  /** 更新 Agent（名称 / 描述 / 状态，缺省字段不变）。 */
  update(id: string, payload: UpdateAgentRequest): Promise<AgentResponse> {
    return api.put<AgentResponse>(`/agents/${id}`, payload).then((r) => r.data);
  },
  /** Agent 版本列表（不可变快照）。 */
  listVersions(id: string): Promise<AgentVersionResponse[]> {
    return api.get<AgentVersionResponse[]>(`/agents/${id}/versions`).then((r) => r.data);
  },
  /** 发布一个新版本（一次发布 = 一个新版本，并切换 `current_version_id`）。 */
  publish(id: string, payload: PublishRequest): Promise<AgentVersionResponse> {
    return api.post<AgentVersionResponse>(`/agents/${id}/publish`, payload).then((r) => r.data);
  },
  /**
   * 由 **Agent Studio 草稿**发布新版本（W8 / T2-41，**加性**方法）。
   *
   * 跨面板配置经 {@link draftToPublishRequest} 单点合成 `PublishRequest`，
   * 复用既有发布端点（**不新增后端契约**），产生一个新的 `agent_version`。
   */
  publishDraft(id: string, draft: AgentStudioDraft): Promise<AgentVersionResponse> {
    return agentService.publish(id, draftToPublishRequest(draft));
  },
};
