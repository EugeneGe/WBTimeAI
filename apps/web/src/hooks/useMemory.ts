import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { memoryService } from "@/services/memory";
import { useAuthStore } from "@/stores/authStore";
import type { MemoryListParams } from "@/types";

/**
 * Memory hooks（TanStack Query；W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h）。
 *
 * - 浏览：按 scope 过滤（`useQuery`；`enabled` 依认证态）；
 * - 删除：`useMutation`，成功后失效当前过滤键。
 */

/** 记忆过滤键（集中派生，避免拼写漂移）。 */
function memoryFilterKey(params: MemoryListParams): string {
  return [params.scope_type ?? "", params.scope_id ?? "", params.kind ?? "", params.limit ?? ""]
    .map((part) => String(part))
    .join("|");
}

/** 按 scope 浏览记忆。 */
export function useMemories(params: MemoryListParams = {}) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.memories(memoryFilterKey(params)),
    queryFn: () => memoryService.list(params),
    enabled: isAuthenticated,
  });
}

/** 删除一条记忆 mutation。 */
export function useDeleteMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: string) => memoryService.remove(memoryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}
