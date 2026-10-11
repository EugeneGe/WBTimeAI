import { useCallback, useEffect, useRef } from "react";

import {
  asNumber,
  asRecord,
  asString,
  isTerminalEvent,
  parseSseFrame,
  splitSseFrames,
} from "@/lib/chat";
import { chatService } from "@/services/chat";
import { useChatStore } from "@/stores/chatStore";
import type { ChatStreamEvent, RunAgentRequest, TimelineEntry } from "@/types";

/**
 * Chat SSE 流式对接 hook（W7 / T1-32）。
 *
 * 关键能力：
 * - 经 **`fetch` 流**对接 `POST /agents/{id}/run`（`Accept: text/event-stream`）；
 * - **增量拼接** `message.delta`（写入 {@link useChatStore}）；
 * - **事件时间线**：`tool.started/completed`、`mcp.*`、`agent.thinking`；
 * - **断连重试 + `Last-Event-ID` 续传**：流未终态即中断 → 以已收最大 `seq` 经
 *   `GET /runs/{id}/events`（携带 `Last-Event-ID`）续传，最多 `maxRetries` 次；
 * - 终态（`agent.completed` / `agent.error`）后结束。
 *
 * 服务端真相源（会话 / 消息）仍走 TanStack Query；本 hook 仅维护客户端流式缓冲。
 */

/** 默认最大重试次数（断连续传）。 */
export const DEFAULT_MAX_RETRIES = 3;

/** 默认重试退避基数（毫秒，线性退避）。 */
export const DEFAULT_RETRY_DELAY_MS = 300;

/** hook 选项。 */
export interface UseChatStreamOptions {
  /** 目标 Agent（为空则无法发送）。 */
  agentId: string | null;
  /** 绑定 Workspace（可选）。 */
  workspaceId?: string | null;
  /** 最大重试次数（缺省 {@link DEFAULT_MAX_RETRIES}）。 */
  maxRetries?: number;
  /** 重试退避基数毫秒（缺省 {@link DEFAULT_RETRY_DELAY_MS}）。 */
  retryDelayMs?: number;
  /** 流正常终态回调（供页面失效 Query 缓存）。 */
  onCompleted?: () => void;
  /** 流失败回调（已重试仍失败 / `agent.error`）。 */
  onError?: (message: string) => void;
}

/** hook 返回值。 */
export interface UseChatStreamResult {
  /** 是否正在流式接收。 */
  streaming: boolean;
  /** 最近一次错误。 */
  error: string | null;
  /** 发送一条消息并开始流式执行。 */
  sendMessage: (message: string, conversationId?: string | null) => Promise<void>;
  /** 取消当前流（断连即取消，INLINE 语义）。 */
  cancel: () => void;
}

/** 线性退避延时。 */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** 将任意错误归一化为可读文案。 */
function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

/** 流式进度（跨 `onEvent` 回调可变，用对象承载以避免 TS 收窄）。 */
interface StreamProgress {
  runId: string | null;
  lastEventId: number | null;
}

/** 消费一次 SSE 响应体（增量解析 + 逐事件回调）。 */
async function consumeStream(
  response: Response,
  handlers: { signal: AbortSignal; onEvent: (event: ChatStreamEvent) => void },
): Promise<{ terminal: boolean; errored: boolean }> {
  const body = response.body;
  if (!body) {
    return { terminal: false, errored: true };
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = splitSseFrames(buffer);
      buffer = rest;
      for (const frame of frames) {
        if (handlers.signal.aborted) {
          return { terminal, errored: false };
        }
        const event = parseSseFrame(frame);
        if (!event) {
          continue;
        }
        handlers.onEvent(event);
        if (isTerminalEvent(event.channel)) {
          terminal = true;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
  return { terminal, errored: false };
}

/** 将 SSE 事件分派到 chatStore（增量拼接 + 时间线）。 */
function dispatchEvent(event: ChatStreamEvent): void {
  const store = useChatStore.getState();
  const { channel, payload, seq } = event;
  switch (channel) {
    case "agent.started": {
      const runId = asString(payload.run_id);
      if (runId) {
        store.setActiveRunId(runId);
      }
      break;
    }
    case "agent.thinking": {
      store.upsertTimelineEntry({
        id: `thinking-${seq ?? "x"}`,
        kind: "thinking",
        status: "running",
        name: "思考",
        seq,
      });
      break;
    }
    case "message.delta": {
      const messageId = asString(payload.message_id) ?? "assistant";
      const delta = asString(payload.delta) ?? "";
      if (delta.length > 0) {
        store.appendDelta(messageId, delta);
      }
      break;
    }
    case "tool.started": {
      const id = asString(payload.tool_call_id) ?? `tool-${seq ?? "x"}`;
      const entry: TimelineEntry = {
        id,
        kind: "tool",
        status: "running",
        name: asString(payload.tool) ?? asString(payload.tool_name) ?? "tool",
        input: asRecord(payload.input),
        seq,
      };
      store.upsertTimelineEntry(entry);
      break;
    }
    case "tool.completed": {
      const id = asString(payload.tool_call_id) ?? `tool-${seq ?? "x"}`;
      const status = asString(payload.status);
      store.completeTimelineEntry(id, {
        status: status === "FAILED" || status === "DENIED" ? "error" : "completed",
        output: asRecord(payload.output),
        durationMs: asNumber(payload.duration_ms),
        error: asString(payload.error) ?? undefined,
        seq,
      });
      break;
    }
    case "mcp.started": {
      const id = asString(payload.tool_call_id) ?? `mcp-${seq ?? "x"}`;
      store.upsertTimelineEntry({
        id,
        kind: "mcp",
        status: "running",
        name: asString(payload.tool) ?? asString(payload.server) ?? "mcp",
        input: asRecord(payload.input),
        seq,
      });
      break;
    }
    case "mcp.completed": {
      const id = asString(payload.tool_call_id) ?? `mcp-${seq ?? "x"}`;
      const status = asString(payload.status);
      store.completeTimelineEntry(id, {
        status: status === "FAILED" || status === "DENIED" ? "error" : "completed",
        output: asRecord(payload.output),
        durationMs: asNumber(payload.duration_ms),
        seq,
      });
      break;
    }
    case "agent.completed": {
      store.finishRun();
      break;
    }
    case "agent.error": {
      store.failRun(asString(payload.error) ?? "Agent 执行失败");
      break;
    }
    default:
      break;
  }
}

/**
 * SSE 流式对接 hook（见文件头说明）。
 */
export function useChatStream(options: UseChatStreamOptions): UseChatStreamResult {
  const {
    agentId,
    workspaceId = null,
    maxRetries = DEFAULT_MAX_RETRIES,
    retryDelayMs = DEFAULT_RETRY_DELAY_MS,
    onCompleted,
    onError,
  } = options;

  const abortRef = useRef<AbortController | null>(null);
  const streaming = useChatStore((state) => state.streaming);
  const error = useChatStore((state) => state.error);

  // 卸载时中断在途流，避免泄漏。
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const cancel = useCallback((): void => {
    const controller = abortRef.current;
    const runId = useChatStore.getState().activeRunId;
    if (controller) {
      controller.abort();
      abortRef.current = null;
    }
    if (runId) {
      void chatService.cancelRun(runId).catch(() => undefined);
    }
    useChatStore.getState().finishRun();
  }, []);

  const sendMessage = useCallback(
    async (message: string, conversationId?: string | null): Promise<void> => {
      if (!agentId) {
        useChatStore.getState().failRun("请先选择 Agent");
        onError?.("请先选择 Agent");
        return;
      }

      // 中断上一次在途流（同一会话顺序执行）。
      abortRef.current?.abort();

      const store = useChatStore.getState();
      store.beginRun();
      store.pushUserMessage(message);

      const controller = new AbortController();
      abortRef.current = controller;
      const idempotencyKey = chatService.generateIdempotencyKey();
      const request: RunAgentRequest = {
        message,
        conversation_id: conversationId ?? useChatStore.getState().activeConversationId,
        workspace_id: workspaceId,
      };

      const progress: StreamProgress = { runId: null, lastEventId: null };
      let terminal = false;
      let attempt = 0;
      let lastError: string | null = null;

      const onEvent = (event: ChatStreamEvent): void => {
        if (event.seq !== null) {
          progress.lastEventId = event.seq;
          useChatStore.getState().setLastEventId(event.seq);
        }
        if (event.channel === "agent.started") {
          const rid = asString(event.payload.run_id);
          if (rid) {
            progress.runId = rid;
          }
        }
        dispatchEvent(event);
      };

      while (!terminal) {
        let response: Response | null = null;
        try {
          response = progress.runId
            ? await chatService.openRunEventsStream(
                progress.runId,
                progress.lastEventId,
                controller.signal,
              )
            : await chatService.openRunStream(agentId, request, idempotencyKey, controller.signal);
        } catch (err) {
          if (controller.signal.aborted) {
            break;
          }
          lastError = toErrorMessage(err);
          response = null;
        }

        if (response) {
          if (!response.ok) {
            lastError = `流式请求失败（HTTP ${response.status}）`;
          } else {
            try {
              const outcome = await consumeStream(response, { signal: controller.signal, onEvent });
              terminal = outcome.terminal;
              if (outcome.errored) {
                lastError = lastError ?? "流式响应体为空";
              }
            } catch (err) {
              if (controller.signal.aborted) {
                break;
              }
              lastError = toErrorMessage(err);
            }
          }
        }

        if (terminal || controller.signal.aborted) {
          break;
        }
        attempt += 1;
        if (attempt > maxRetries) {
          break;
        }
        await delay(retryDelayMs * attempt);
      }

      abortRef.current = null;

      if (controller.signal.aborted) {
        useChatStore.getState().finishRun();
        return;
      }

      if (terminal) {
        useChatStore.getState().finishRun();
        const currentError = useChatStore.getState().error;
        if (currentError) {
          // `agent.error` 终态：以错误收尾（不再触发完成回调）。
          onError?.(currentError);
        } else {
          onCompleted?.();
        }
        return;
      }

      const failure = lastError ?? "连接中断，重试失败";
      useChatStore.getState().failRun(failure);
      onError?.(failure);
    },
    [agentId, workspaceId, maxRetries, retryDelayMs, onCompleted, onError],
  );

  return { streaming, error, sendMessage, cancel };
}
