import { API_BASE, api } from "@/lib/api";
import { getAccessToken } from "@/lib/token";
import type { RunAgentRequest, RunEventResponse, RunResponse } from "@/types";

/**
 * Chat / Run 服务（W7 / T1-32）。
 *
 * - 运行 Agent：`POST /agents/{id}/run`（`Accept: text/event-stream` → **SSE 流**）；
 *   经 **`fetch` 流**对接（axios 不适合流式增量读取）；
 * - 续传 / 回放：`GET /runs/{id}/events`（`Last-Event-ID` 头优先，`?after_seq` 回退）；
 * - 取消：`POST /runs/{id}/cancel`（INLINE 断连即取消）。
 *
 * ⚠️ SSE 为**只读输出通道**（执行由 Run 驱动）；前端仅经 `/api/v1`。
 */

/** 构造带 Bearer 鉴权的请求头（SSE 亦需鉴权）。 */
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

/** 生成幂等键（同键同体复用首次 Run；前端重试安全）。 */
function generateIdempotencyKey(): string {
  const globalCrypto: Crypto | undefined =
    typeof globalThis !== "undefined" ? (globalThis.crypto as Crypto | undefined) : undefined;
  if (globalCrypto && typeof globalCrypto.randomUUID === "function") {
    return globalCrypto.randomUUID();
  }
  return `astra-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export const chatService = {
  /** 运行 Agent 并返回 SSE 流响应（`Accept: text/event-stream`）。 */
  openRunStream(
    agentId: string,
    payload: RunAgentRequest,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<Response> {
    return fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}/run`, {
      method: "POST",
      headers: authHeaders({
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      }),
      body: JSON.stringify(payload),
      signal,
    });
  },
  /** 断连续传：拉取 `seq > lastEventId` 的事件（SSE）。 */
  openRunEventsStream(
    runId: string,
    lastEventId: number | null,
    signal?: AbortSignal,
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (lastEventId !== null) {
      headers["Last-Event-ID"] = String(lastEventId);
    }
    return fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/events`, {
      method: "GET",
      headers: authHeaders(headers),
      signal,
    });
  },
  /** Run 详情。 */
  getRun(runId: string): Promise<RunResponse> {
    return api.get<RunResponse>(`/runs/${runId}`).then((r) => r.data);
  },
  /** 取消 Run。 */
  cancelRun(runId: string): Promise<RunResponse> {
    return api.post<RunResponse>(`/runs/${runId}/cancel`).then((r) => r.data);
  },
  /** 事件回放 / 续传（JSON 列表，供 TanStack Query 使用）。 */
  listRunEvents(runId: string, afterSeq?: number): Promise<RunEventResponse[]> {
    return api
      .get<RunEventResponse[]>(`/runs/${runId}/events`, {
        params: afterSeq !== undefined ? { after_seq: afterSeq } : undefined,
      })
      .then((r) => r.data);
  },
  /** 生成幂等键（导出供 hook / 测试复用）。 */
  generateIdempotencyKey,
};
