import { api } from "@/lib/api";
import type {
  ConversationMessageResponse,
  ConversationResponse,
  CreateConversationRequest,
} from "@/types";

/**
 * Conversation 服务（`/conversations` 系列 API，W7 / T1-32）。
 *
 * 服务端数据（会话 / 消息）经 TanStack Query 消费，见 `hooks/useConversations.ts`。
 */
export const conversationService = {
  /** 会话列表（当前租户）。 */
  list(): Promise<ConversationResponse[]> {
    return api.get<ConversationResponse[]>("/conversations").then((r) => r.data);
  },
  /** 会话详情（跨租户 / 不存在 → 404）。 */
  get(id: string): Promise<ConversationResponse> {
    return api.get<ConversationResponse>(`/conversations/${id}`).then((r) => r.data);
  },
  /** 创建会话。 */
  create(payload: CreateConversationRequest): Promise<ConversationResponse> {
    return api.post<ConversationResponse>("/conversations", payload).then((r) => r.data);
  },
  /** 会话消息列表（按创建顺序）。 */
  listMessages(id: string): Promise<ConversationMessageResponse[]> {
    return api
      .get<ConversationMessageResponse[]>(`/conversations/${id}/messages`)
      .then((r) => r.data);
  },
};
