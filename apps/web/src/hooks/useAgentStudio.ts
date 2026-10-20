import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { agentService } from "@/services/agent";
import type { AgentStudioDraft, AgentVersionResponse } from "@/types";

/**
 * Agent Studio hooks（TanStack Query；W8 / T2-41；设计 §2.13）。
 *
 * - **基础 hooks 复用**既有 `hooks/useAgents.ts`（列表 / 详情 / 版本 / 创建 / 更新）——
 *   经 `useStudio*` 别名重导出，**避免重复实现**（服务状态唯一真相源）；
 * - **新增** {@link usePublishAgentDraft}：由跨面板草稿合成发布请求，产生新 `agent_version`。
 */
export {
  useAgent as useStudioAgent,
  useAgentVersions as useStudioAgentVersions,
  useAgents as useStudioAgents,
  useCreateAgent as useCreateStudioAgent,
  useUpdateAgent as useUpdateStudioAgent,
  usePublishAgent as useStudioPublishVersion,
} from "./useAgents";

/** 发布入参：目标 Agent + Studio 草稿。 */
export interface PublishAgentDraftInput {
  /** 目标 Agent 标识。 */
  id: string;
  /** 跨面板合成草稿。 */
  draft: AgentStudioDraft;
}

/**
 * 由 Studio 草稿发布新版本（一次发布 = 一个新 `agent_version`）。
 *
 * 成功后失效该 Agent 的详情 / 版本列表与 Agent 列表（对齐 `usePublishAgent` 口径）。
 */
export function usePublishAgentDraft(): UseMutationResult<
  AgentVersionResponse,
  unknown,
  PublishAgentDraftInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: PublishAgentDraftInput) => agentService.publishDraft(input.id, input.draft),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent(version.agent_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentVersions(version.agent_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents });
    },
  });
}
