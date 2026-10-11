import { api } from "@/lib/api";
import type { MemoryListParams, MemoryResponse } from "@/types";

/**
 * Memory 服务（`/memory/*` API，W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h）。
 *
 * - 浏览：按 `scope_type` / `scope_id` / `kind` 过滤（F-d query）；
 * - 删除：`DELETE /memory/{id}`（F-h）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 */
export const memoryService = {
  /** 按 scope 浏览记忆。 */
  list(params: MemoryListParams = {}): Promise<MemoryResponse[]> {
    return api.get<MemoryResponse[]>("/memory", { params }).then((r) => r.data);
  },
  /** 删除一条记忆。 */
  remove(memoryId: string): Promise<void> {
    return api.delete<void>(`/memory/${memoryId}`).then(() => undefined);
  },
};
