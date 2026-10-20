import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { conversationService } from "@/services/conversation";
import { useAuthStore } from "@/stores/authStore";
import type { ConversationResponse, CreateConversationRequest } from "@/types";

/** 会话列表。 */
export function useConversations() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.conversations,
    queryFn: () => conversationService.list(),
    enabled: isAuthenticated,
  });
}

/** 会话详情（`id` 为空时不请求）。 */
export function useConversation(id: string | null) {
  return useQuery({
    queryKey: queryKeys.conversation(id ?? ""),
    queryFn: () => conversationService.get(id as string),
    enabled: Boolean(id),
  });
}

/** 会话消息列表（按创建顺序）。 */
export function useConversationMessages(id: string | null) {
  return useQuery({
    queryKey: queryKeys.conversationMessages(id ?? ""),
    queryFn: () => conversationService.listMessages(id as string),
    enabled: Boolean(id),
  });
}

/** 创建会话 mutation（成功失效列表）。 */
export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateConversationRequest) => conversationService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    },
  });
}

/** 重命名会话入参（F-09 / §4.4）。 */
export interface RenameConversationInput {
  id: string;
  title: string;
}

/**
 * 重命名会话 mutation（成功失效会话列表 + 该会话详情；F-09）。
 *
 * `PUT /conversations/{id}` 落库后，`conversations` 列表（Topbar 标题来源）与
 * `conversation(id)` 详情缓存即时刷新。
 */
export function useRenameConversation() {
  const queryClient = useQueryClient();
  return useMutation<ConversationResponse, unknown, RenameConversationInput>({
    mutationFn: ({ id, title }) => conversationService.update(id, { title }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversation(variables.id) });
    },
  });
}
