import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { knowledgeService } from "@/services/knowledge";
import { useAuthStore } from "@/stores/authStore";
import type { CreateDocumentRequest, CreateKnowledgeBaseRequest, SearchRequest } from "@/types";

/**
 * Knowledge hooks（TanStack Query；W6 / T2-35；设计 §2.6）。
 *
 * - 知识库 / 文档为**服务状态**（`useQuery`）；`enabled` 依认证态；
 * - 检索试跑为**动作**（`useMutation`），结果由组件持态（不缓存）。
 */

/** 知识库列表。 */
export function useKnowledgeBases() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.knowledgeBases,
    queryFn: () => knowledgeService.listBases(),
    enabled: isAuthenticated,
  });
}

/** 知识库详情（`knowledgeBaseId` 为空时不请求）。 */
export function useKnowledgeBase(knowledgeBaseId: string | null) {
  return useQuery({
    queryKey: queryKeys.knowledgeBase(knowledgeBaseId ?? ""),
    queryFn: () => knowledgeService.getBase(knowledgeBaseId as string),
    enabled: Boolean(knowledgeBaseId),
  });
}

/** 某知识库下的文档列表（`knowledgeBaseId` 为空时不请求；携 `status` 进度）。 */
export function useDocuments(knowledgeBaseId: string | null, options?: { poll?: boolean }) {
  const poll = options?.poll ?? false;
  return useQuery({
    queryKey: queryKeys.documents(knowledgeBaseId ?? ""),
    queryFn: () => knowledgeService.listDocuments(knowledgeBaseId as string),
    enabled: Boolean(knowledgeBaseId),
    // 索引进度轮询：仅在显式要求时开启（默认关闭，避免无谓抖动）。
    refetchInterval: poll ? 3_000 : false,
  });
}

/** 创建知识库 mutation。 */
export function useCreateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateKnowledgeBaseRequest) => knowledgeService.createBase(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBases });
    },
  });
}

/** 登记文档 mutation。 */
export function useCreateDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      knowledgeBaseId,
      payload,
    }: {
      knowledgeBaseId: string;
      payload: CreateDocumentRequest;
    }) => knowledgeService.createDocument(knowledgeBaseId, payload),
    onSuccess: (document) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents(document.knowledge_base_id),
      });
    },
  });
}

/** 检索试跑 mutation（按需触发；命中 + 引用 + 检索路 `mode`）。 */
export function useSearchKnowledge() {
  return useMutation({
    mutationFn: (payload: SearchRequest) => knowledgeService.search(payload),
  });
}
