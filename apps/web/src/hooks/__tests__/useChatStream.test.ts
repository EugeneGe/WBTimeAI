// ---------------------------------------------------------------------------
// Astra AI · useChatStream 单测（W7 / T1-35 · U-P1-26）
//
// 覆盖（≥3 条为 SSE 流式相关 · D14）：
//   ① `message.delta` **增量拼接**（store 纯语义 + msw SSE 流两条断言）；
//   ③ **断连后重试 + `Last-Event-ID` 续传**（msw 拦截 SSE 分片）。
//
// msw 拦截 `text/event-stream`，**不依赖真实后端**。
// ---------------------------------------------------------------------------
import { act, renderHook } from "@testing-library/react";
import { http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";
import { sseFrame, sseResponse } from "@/test/msw-handlers";
import { server } from "@/test/setup";
import { useChatStore } from "@/stores/chatStore";

describe("useChatStream", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  afterEach(() => {
    useChatStore.getState().reset();
  });

  it("appendDelta 对同一 message_id 做增量拼接（不新建重复消息）", () => {
    useChatStore.getState().appendDelta("m1", "Hel");
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].content).toBe("Hel");

    useChatStore.getState().appendDelta("m1", "lo");
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].content).toBe("Hello");
    expect(useChatStore.getState().messages[0].role).toBe("assistant");
  });

  it("经 msw SSE 流增量拼接 message.delta（含终态 agent.completed）", async () => {
    const { result } = renderHook(() => useChatStream({ agentId: "a1", retryDelayMs: 0 }));

    await act(async () => {
      await result.current.sendMessage("你好");
    });

    const messages = useChatStore.getState().messages;
    expect(messages.filter((message) => message.role === "user")).toHaveLength(1);
    const assistants = messages.filter((message) => message.role === "assistant");
    expect(assistants).toHaveLength(1);
    expect(assistants[0].content).toBe("Hello");
    expect(useChatStore.getState().streaming).toBe(false);
    expect(useChatStore.getState().error).toBeNull();
  });

  it("断连后重试并携带 Last-Event-ID 续传（GET /runs/{id}/events）", async () => {
    let seenLastEventId: string | null = null;
    let eventsCalls = 0;

    server.use(
      // 首次 POST：发出 2 帧后**无终态即关闭** → 模拟断连。
      http.post("/api/v1/agents/:agentId/run", () =>
        sseResponse([
          sseFrame({ id: 1, event: "agent.started", data: { run_id: "run-x", agent_id: "a1" } }),
          sseFrame({ id: 2, event: "message.delta", data: { message_id: "m1", delta: "Hel" } }),
        ]),
      ),
      // 续传 GET：断言 `Last-Event-ID` 头，返回余下帧直至终态。
      http.get("/api/v1/runs/:runId/events", ({ request }) => {
        eventsCalls += 1;
        seenLastEventId = request.headers.get("Last-Event-ID");
        return sseResponse([
          sseFrame({ id: 3, event: "message.delta", data: { message_id: "m1", delta: "lo" } }),
          sseFrame({
            id: 4,
            event: "tool.started",
            data: { run_id: "run-x", tool_call_id: "tc1", tool: "git", input: {} },
          }),
          sseFrame({
            id: 5,
            event: "tool.completed",
            data: {
              run_id: "run-x",
              tool_call_id: "tc1",
              status: "SUCCESS",
              output: {},
              duration_ms: 12,
            },
          }),
          sseFrame({ id: 6, event: "agent.completed", data: { run_id: "run-x" } }),
        ]);
      }),
    );

    const { result } = renderHook(() =>
      useChatStream({ agentId: "a1", retryDelayMs: 0, maxRetries: 2 }),
    );

    await act(async () => {
      await result.current.sendMessage("go");
    });

    // ① 触发了一次续传；② 续传起点 = 已收最大 seq。
    expect(eventsCalls).toBe(1);
    expect(seenLastEventId).toBe("2");

    // ③ 增量拼接继续（"Hel" + "lo"）。
    const assistant = useChatStore
      .getState()
      .messages.find((message) => message.role === "assistant");
    expect(assistant?.content).toBe("Hello");

    // ④ 断连前的 tool.started 之后，续传补全 tool.completed 时间线。
    const toolEntry = useChatStore.getState().timeline.find((entry) => entry.kind === "tool");
    expect(toolEntry).toBeDefined();
    expect(toolEntry?.name).toBe("git");
    expect(toolEntry?.status).toBe("completed");
    expect(toolEntry?.durationMs).toBe(12);

    expect(useChatStore.getState().streaming).toBe(false);
  });

  it("agent.error 终态以错误收尾并触发 onError（不触发 onCompleted）", async () => {
    const onCompleted = vi.fn();
    const onError = vi.fn();

    server.use(
      http.post("/api/v1/agents/:agentId/run", () =>
        sseResponse([
          sseFrame({ id: 1, event: "agent.started", data: { run_id: "run-e", agent_id: "a1" } }),
          sseFrame({ id: 2, event: "agent.error", data: { run_id: "run-e", error: "boom" } }),
        ]),
      ),
    );

    const { result } = renderHook(() =>
      useChatStream({ agentId: "a1", retryDelayMs: 0, onCompleted, onError }),
    );

    await act(async () => {
      await result.current.sendMessage("go");
    });

    expect(onError).toHaveBeenCalledWith("boom");
    expect(onCompleted).not.toHaveBeenCalled();
    expect(useChatStore.getState().error).toBe("boom");
    expect(useChatStore.getState().streaming).toBe(false);
  });
});
