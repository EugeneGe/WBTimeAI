import { create } from "zustand";

import type { ChatMessage, ChatRole, TimelineEntry } from "@/types";

/**
 * Chat Zustand store（**纯客户端状态**：当前会话 / 流式缓冲 / 时间线 / UI 态，D6）。
 *
 * ⚠️ **禁止**在此存放服务端真相源数据（会话 / 消息列表的查询走 TanStack Query）；
 *    本 store 仅承载「当前会话的流式增量缓冲」与「事件时间线」等客户端态。
 */

/** 会话消息角色归一化（后端可能返回任意 role 字面值）。 */
function normalizeRole(role: string): ChatRole {
  switch (role) {
    case "system":
    case "user":
    case "assistant":
    case "tool":
      return role;
    default:
      return "assistant";
  }
}

/** 将服务端消息映射为 UI 视图消息。 */
export function toChatMessage(input: {
  id: string;
  role: string;
  content: string;
  created_at?: string | null;
}): ChatMessage {
  return {
    id: input.id,
    role: normalizeRole(input.role),
    content: input.content ?? "",
    createdAt: input.created_at ?? null,
  };
}

/** Chat store 状态与动作。 */
export interface ChatState {
  /** 当前会话标识（缺省 = 新会话，首条消息时服务端就地创建）。 */
  activeConversationId: string | null;
  /** 当前 Run 标识（`agent.started` 后写入，供断连续传）。 */
  activeRunId: string | null;
  /** 消息缓冲（含本地用户消息 + 流式增量拼接的助手消息）。 */
  messages: ChatMessage[];
  /** 事件时间线（`tool.*` / `mcp.*` / `thinking`）。 */
  timeline: TimelineEntry[];
  /** 是否正在流式接收。 */
  streaming: boolean;
  /** 最近一次错误（流式中断 / `agent.error`）。 */
  error: string | null;
  /** 已接收的最大 `seq`（`Last-Event-ID` 续传起点）。 */
  lastEventId: number | null;

  reset: () => void;
  setActiveConversationId: (id: string | null) => void;
  setActiveRunId: (id: string | null) => void;
  setMessages: (messages: ChatMessage[]) => void;
  beginRun: () => void;
  pushUserMessage: (content: string, id?: string) => void;
  appendDelta: (messageId: string, delta: string) => void;
  upsertTimelineEntry: (entry: TimelineEntry) => void;
  completeTimelineEntry: (id: string, patch: Partial<TimelineEntry>) => void;
  setLastEventId: (seq: number | null) => void;
  finishRun: () => void;
  failRun: (message: string) => void;
}

const INITIAL = {
  activeConversationId: null as string | null,
  activeRunId: null as string | null,
  messages: [] as ChatMessage[],
  timeline: [] as TimelineEntry[],
  streaming: false,
  error: null as string | null,
  lastEventId: null as number | null,
};

/** 自增本地 id（用户消息占位 / 兜底）。 */
let localSeq = 0;
function nextLocalId(prefix: string): string {
  localSeq += 1;
  return `${prefix}-${localSeq}`;
}

export const useChatStore = create<ChatState>((set) => ({
  ...INITIAL,
  reset: () => set({ ...INITIAL }),
  setActiveConversationId: (id) => set({ activeConversationId: id }),
  setActiveRunId: (id) => set({ activeRunId: id }),
  setMessages: (messages) => set({ messages }),
  beginRun: () =>
    set({
      streaming: true,
      error: null,
      timeline: [],
      activeRunId: null,
      lastEventId: null,
    }),
  pushUserMessage: (content, id) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: id ?? nextLocalId("user"), role: "user" as const, content },
      ],
    })),
  appendDelta: (messageId, delta) =>
    set((state) => {
      const index = state.messages.findIndex((message) => message.id === messageId);
      if (index === -1) {
        // 首次见到该 message_id → 新建流式助手消息（增量起点）。
        return {
          messages: [
            ...state.messages,
            { id: messageId, role: "assistant" as const, content: delta, streaming: true },
          ],
        };
      }
      const messages = state.messages.slice();
      const current = messages[index];
      messages[index] = { ...current, content: current.content + delta, streaming: true };
      return { messages };
    }),
  upsertTimelineEntry: (entry) =>
    set((state) => {
      const index = state.timeline.findIndex((item) => item.id === entry.id);
      if (index === -1) {
        return { timeline: [...state.timeline, entry] };
      }
      const timeline = state.timeline.slice();
      timeline[index] = { ...timeline[index], ...entry };
      return { timeline };
    }),
  completeTimelineEntry: (id, patch) =>
    set((state) => {
      const index = state.timeline.findIndex((item) => item.id === id);
      if (index === -1) {
        return {};
      }
      const timeline = state.timeline.slice();
      timeline[index] = { ...timeline[index], ...patch };
      return { timeline };
    }),
  setLastEventId: (seq) => set({ lastEventId: seq }),
  finishRun: () =>
    set((state) => ({
      streaming: false,
      activeRunId: null,
      messages: state.messages.map((message) =>
        message.streaming ? { ...message, streaming: false } : message,
      ),
    })),
  failRun: (message) =>
    set((state) => ({
      streaming: false,
      error: message,
      messages: state.messages.map((item) =>
        item.streaming ? { ...item, streaming: false } : item,
      ),
    })),
}));
