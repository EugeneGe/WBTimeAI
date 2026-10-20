import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { agentService } from "@/services/agent";
import { useAuthStore } from "@/stores/authStore";
import type { CreateAgentRequest, PublishRequest, UpdateAgentRequest } from "@/types";

/** Agent 列表。 */
export function useAgents() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.agents,
    queryFn: () => agentService.list(),
    enabled: isAuthenticated,
  });
}

/** Agent 详情（`id` 为空时不请求）。 */
export function useAgent(id: string | null) {
  return useQuery({
    queryKey: queryKeys.agent(id ?? ""),
    queryFn: () => agentService.get(id as string),
    enabled: Boolean(id),
  });
}

/** Agent 版本列表（不可变快照）。 */
export function useAgentVersions(id: string | null) {
  return useQuery({
    queryKey: queryKeys.agentVersions(id ?? ""),
    queryFn: () => agentService.listVersions(id as string),
    enabled: Boolean(id),
  });
}

/** 创建 Agent mutation（成功失效列表）。 */
export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateAgentRequest) => agentService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents });
    },
  });
}

/** 更新 Agent mutation（成功失效列表与详情）。 */
export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; payload: UpdateAgentRequest }) =>
      agentService.update(input.id, input.payload),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent(agent.id) });
    },
  });
}

/** 发布 AgentVersion mutation（发布即切换 `current_version_id`）。 */
export function usePublishAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; payload: PublishRequest }) =>
      agentService.publish(input.id, input.payload),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agent(version.agent_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentVersions(version.agent_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents });
    },
  });
}
