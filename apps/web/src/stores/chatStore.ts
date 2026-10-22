import { create } from "zustand";

import type {
  ChatApprovalState,
  ChatMessage,
  ChatRole,
  ResolvedSkillRef,
  TimelineEntry,
} from "@/types";

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
  /**
   * 当前审批态（AUD-06：`approval.requested` / `approval.decided` 的客户端投影）。
   *
   * 为什么必须有它：后端在跑需要审批的工具时会停在 `WAITING_APPROVAL` 等 15s，
   * **超时即按 DENY 处理**（工具不执行）。前端原先完全不消费这两帧 ⇒ 用户在聊天里
   * 只看到"卡住"，然后工具"莫名失败"，没有任何可操作提示。
   */
  approval: ChatApprovalState | null;
  /** 本次 run 已解析的技能（`skill.resolved`；解析不到时不发帧，故只增不减）。 */
  skills: ResolvedSkillRef[];
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
  /**
   * 记录一条审批请求（`approval.requested`）。
   *
   * @param input `approvalId` / `subjectRef`（= tool_call id）/ `subjectType` / `seq`。
   *   **工具名不在帧里**，由 `subjectRef` 在时间线上反查（见 {@link ChatApprovalState}）。
   */
  setApprovalRequested: (input: {
    approvalId: string;
    subjectRef: string | null;
    subjectType: string | null;
    seq: number | null;
  }) => void;
  /** 记录审批决议（`approval.decided`；`APPROVED` ⇒ approved，其余终态 ⇒ rejected）。 */
  setApprovalDecided: (input: {
    approvalId: string | null;
    status: string | null;
    decidedBy: string | null;
    seq: number | null;
  }) => void;
  /** 清掉审批提示（决议后由页面延时调用；切会话 / 新 run 时也清）。 */
  clearApproval: () => void;
  /** 追加一条已解析技能（同 `skillId` 去重）。 */
  addResolvedSkill: (skill: ResolvedSkillRef) => void;
  finishRun: () => void;
  failRun: (message: string) => void;
}

const INITIAL = {
  activeConversationId: null as string | null,
  activeRunId: null as string | null,
  messages: [] as ChatMessage[],
  timeline: [] as TimelineEntry[],
  approval: null as ChatApprovalState | null,
  skills: [] as ResolvedSkillRef[],
  streaming: false,
  error: null as string | null,
  lastEventId: null as number | null,
};

/**
 * 审批决议状态的归一化。
 *
 * 后端 `approval.decided.status` 写的是审批行状态（大写 `APPROVED` / `REJECTED` …），
 * 契约样例写的是小写 `approved` —— 两边都见得到，故按**大小写无关**判定：
 * 只有 `APPROVED` 算通过，其余**已知终态**一律算驳回（`REJECTED` / `DENIED` / `EXPIRED`）。
 * 未知值回落 `pending`：宁可继续显示"等待审批"，也不谎报"通过了"。
 */
function normalizeApprovalStatus(status: string | null): "pending" | "approved" | "rejected" {
  if (status === null) {
    return "pending";
  }
  const normalized = status.trim().toUpperCase();
  if (normalized === "APPROVED") {
    return "approved";
  }
  if (
    normalized === "REJECTED" ||
    normalized === "DENIED" ||
    normalized === "EXPIRED" ||
    // 决议帧里出现 `PENDING` = **等到超时都没人处理**，后端随即按 DENY 处理
    // （`driver.ts::#askApproval`：`rejected = status !== "APPROVED"`）。
    // 若把它显示成"仍在等待"，用户会一直等一个永远不会到来的决议。
    normalized === "PENDING"
  ) {
    return "rejected";
  }
  return "pending";
}

/**
 * 由 `subject_ref`（tool_call id）在时间线上反查工具名。
 *
 * 帧里没有工具名（见 {@link ChatApprovalState} 的说明）；`tool.started` 恒先于
 * `approval.requested` 落库/下发，所以能查到。查不到 ⇒ 回落 `subject_type`，
 * **不编造**工具名。
 */
function toolNameOf(timeline: readonly TimelineEntry[], subjectRef: string | null, subjectType: string | null): string {
  if (subjectRef !== null) {
    const entry = timeline.find((item) => item.id === subjectRef);
    if (entry !== undefined && entry.name !== "") {
      return entry.name;
    }
  }
  return subjectType ?? "tool";
}

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
      approval: null,
      skills: [],
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
  setApprovalRequested: (input) =>
    set((state) => ({
      approval: {
        approvalId: input.approvalId,
        toolName: toolNameOf(state.timeline, input.subjectRef, input.subjectType),
        status: "pending" as const,
        seq: input.seq,
      },
    })),
  setApprovalDecided: (input) =>
    set((state) => {
      // 决策帧可能先于请求帧到达（续传 / 重连时只补到后半段）⇒ 此时也要建状态，
      // 否则"已经驳回"这件事在界面上完全不存在。
      const base: ChatApprovalState = state.approval ?? {
        approvalId: input.approvalId ?? "unknown",
        toolName: "tool",
        status: "pending" as const,
        seq: input.seq,
      };
      // 只有同一条审批的决议才改状态（避免迟到的旧决议覆盖新的审批请求）。
      if (input.approvalId !== null && base.approvalId !== input.approvalId) {
        return {};
      }
      return {
        approval: {
          ...base,
          status: normalizeApprovalStatus(input.status),
          decidedBy: input.decidedBy,
          seq: input.seq ?? base.seq,
        },
      };
    }),
  clearApproval: () => set({ approval: null }),
  addResolvedSkill: (skill) =>
    set((state) => {
      const exists = state.skills.some(
        (item) => item.name === skill.name && item.version === skill.version,
      );
      return exists ? {} : { skills: [...state.skills, skill] };
    }),
  finishRun: () =>
    set((state) => ({
      streaming: false,
      activeRunId: null,
      // run 已终态 ⇒ 还停在 pending 的审批不会再有决议了（后端超时即 DENY），
      // 继续显示"等待审批"只会误导用户去点一个已经不存在的审批。
      approval: state.approval !== null && state.approval.status === "pending" ? null : state.approval,
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
