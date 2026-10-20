import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { knowledgeService } from "@/services/knowledge";
import { useAuthStore } from "@/stores/authStore";
import type {
  CreateDocumentRequest,
  CreateKnowledgeBaseRequest,
  SearchRequest,
  UpdateKnowledgeBaseRequest,
} from "@/types";

/**
 * Knowledge hooks（TanStack Query；W6 / T2-35；设计 §2.6）。
 *
 * - 知识库 / 文档为**服务状态**（`useQuery`）；`enabled` 依认证态；
 * - 查询 hook **原样返回 useQuery 结果**：`data` / `isLoading` / `isError` / `error` /
 *   `refetch` 全部透传（B-16 四态消费：错误面板 + 重试），`data` 字段名不变，
 *   既有调用方零破坏；
 * - 检索试跑为**动作**（`useMutation`），结果由组件持态（不缓存）。
 */

/** 知识库列表（透传 `isError` / `error` / `refetch` 供页内错误面板）。 */
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

/** 某知识库下的文档列表（`knowledgeBaseId` 为空时不请求；携 `status` 进度；透传四态）。 */
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

/** 更新知识库（改名 / 描述）mutation（B-19a；invalidate 列表与详情）。 */
export function useUpdateKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      knowledgeBaseId,
      payload,
    }: {
      knowledgeBaseId: string;
      payload: UpdateKnowledgeBaseRequest;
    }) => knowledgeService.updateBase(knowledgeBaseId, payload),
    onSuccess: (base) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBases });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBase(base.id) });
    },
  });
}

/** 删除知识库 mutation（B-19a；invalidate 列表 + 该库文档 / 详情）。 */
export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (knowledgeBaseId: string) => knowledgeService.deleteBase(knowledgeBaseId),
    onSuccess: (_data, knowledgeBaseId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBases });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBase(knowledgeBaseId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents(knowledgeBaseId) });
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
