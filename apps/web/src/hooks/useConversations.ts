import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { conversationService } from "@/services/conversation";
import { useAuthStore } from "@/stores/authStore";
import type { CreateConversationRequest } from "@/types";

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
