// ---------------------------------------------------------------------------
// WBTimeAI · useChatStream 单测（W7 / T1-35 · U-P1-26）
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
    const { result } = renderHook(() =>
      useChatStream({ agentId: "a1", workspaceId: "ws-1", retryDelayMs: 0 }),
    );

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
      useChatStream({ agentId: "a1", workspaceId: "ws-1", retryDelayMs: 0, maxRetries: 2 }),
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
      useChatStream({ agentId: "a1", workspaceId: "ws-1", retryDelayMs: 0, onCompleted, onError }),
    );

    await act(async () => {
      await result.current.sendMessage("go");
    });

    expect(onError).toHaveBeenCalledWith("boom");
    expect(onCompleted).not.toHaveBeenCalled();
    expect(useChatStore.getState().error).toBe("boom");
    expect(useChatStore.getState().streaming).toBe(false);
  });

  it("新建会话缺 workspaceId → 引导选择工作区（F-4：不发请求、不静默 null）", async () => {
    const onError = vi.fn();
    let requested = false;
    server.use(
      http.post("/api/v1/agents/:agentId/run", () => {
        requested = true;
        return sseResponse([
          sseFrame({ id: 1, event: "agent.started", data: { run_id: "run-x", agent_id: "a1" } }),
          sseFrame({ id: 2, event: "agent.completed", data: { run_id: "run-x" } }),
        ]);
      }),
    );

    const { result } = renderHook(() => useChatStream({ agentId: "a1", retryDelayMs: 0, onError }));

    await act(async () => {
      await result.current.sendMessage("hi");
    });

    expect(requested).toBe(false);
    expect(onError).toHaveBeenCalledWith("请先选择工作区（新建会话须归属工作区）");
    expect(useChatStore.getState().error).toBe("请先选择工作区（新建会话须归属工作区）");
    expect(useChatStore.getState().streaming).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // AUD-06 · 审批 / 技能帧（原先这 3 帧在 parseSseFrame 阶段就被丢掉）
  // ---------------------------------------------------------------------------

  it("AUD-06 · 消费 approval.requested（待审批，工具名按 subject_ref 反查）+ skill.resolved", async () => {
    server.use(
      http.post("/api/v1/agents/:agentId/run", () =>
        sseResponse([
          sseFrame({ id: 1, event: "agent.started", data: { run_id: "run-ap", agent_id: "a1" } }),
          sseFrame({
            id: 2,
            event: "skill.resolved",
            data: { skill_name: "pdf", skill_id: "skill-1", version: "1.0.0" },
          }),
          // `tool.started` 恒先于审批帧（driver 的写入顺序）——工具名靠它反查。
          sseFrame({
            id: 3,
            event: "tool.started",
            data: { tool_call_id: "tc-9", tool_name: "shell", input: { command: "rm -rf /tmp/x" } },
          }),
          sseFrame({
            id: 4,
            event: "approval.requested",
            data: {
              approval_id: "appr-1",
              subject_type: "tool",
              subject_ref: "tc-9",
              requested_by: "user-1",
            },
          }),
        ]),
      ),
    );

    const { result } = renderHook(() =>
      useChatStream({ agentId: "a1", workspaceId: "ws-1", retryDelayMs: 0, maxRetries: 0 }),
    );

    await act(async () => {
      await result.current.sendMessage("删一下");
    });

    const { approval, skills } = useChatStore.getState();
    expect(skills).toHaveLength(1);
    expect(skills[0]).toMatchObject({ name: "pdf", skillId: "skill-1", version: "1.0.0" });

    expect(approval).not.toBeNull();
    expect(approval?.approvalId).toBe("appr-1");
    expect(approval?.status).toBe("pending");
    // 帧里没有工具名 ⇒ 必须由 subject_ref 反查（不是编的、也不是 subject_type）。
    expect(approval?.toolName).toBe("shell");
  });

  it("AUD-06 · approval.decided(APPROVED) ⇒ 状态转 approved，并保留工具名与决议人", async () => {
    server.use(
      http.post("/api/v1/agents/:agentId/run", () =>
        sseResponse([
          sseFrame({ id: 1, event: "agent.started", data: { run_id: "run-ap2", agent_id: "a1" } }),
          sseFrame({
            id: 2,
            event: "tool.started",
            data: { tool_call_id: "tc-1", tool_name: "git", input: {} },
          }),
          sseFrame({
            id: 3,
            event: "approval.requested",
            data: { approval_id: "appr-2", subject_type: "tool", subject_ref: "tc-1" },
          }),
          sseFrame({
            id: 4,
            event: "approval.decided",
            data: { approval_id: "appr-2", status: "APPROVED", decided_by: "user-9" },
          }),
          sseFrame({ id: 5, event: "agent.completed", data: { run_id: "run-ap2" } }),
        ]),
      ),
    );

    const { result } = renderHook(() =>
      useChatStream({ agentId: "a1", workspaceId: "ws-1", retryDelayMs: 0 }),
    );

    await act(async () => {
      await result.current.sendMessage("提交");
    });

    const { approval } = useChatStore.getState();
    expect(approval?.status).toBe("approved");
    expect(approval?.decidedBy).toBe("user-9");
    expect(approval?.toolName).toBe("git");
  });

  it("AUD-06 · approval.decided(REJECTED) ⇒ rejected；PENDING（超时）同样算驳回", () => {
    const store = useChatStore.getState();
    store.beginRun();
    store.setApprovalRequested({ approvalId: "a-1", subjectRef: null, subjectType: "tool", seq: 1 });
    store.setApprovalDecided({ approvalId: "a-1", status: "REJECTED", decidedBy: "u", seq: 2 });
    expect(useChatStore.getState().approval?.status).toBe("rejected");

    // 超时（drive 侧 `decided.status === "PENDING"` ⇒ 按 DENY 处理）不得显示成"仍在等待"。
    store.setApprovalRequested({ approvalId: "a-2", subjectRef: null, subjectType: "shell", seq: 3 });
    store.setApprovalDecided({ approvalId: "a-2", status: "PENDING", decidedBy: "u", seq: 4 });
    expect(useChatStore.getState().approval?.status).toBe("rejected");
    expect(useChatStore.getState().approval?.toolName).toBe("shell");

    // clearApproval 后不再显示（页面延时自动消失走的就是它）。
    store.clearApproval();
    expect(useChatStore.getState().approval).toBeNull();
  });
});
