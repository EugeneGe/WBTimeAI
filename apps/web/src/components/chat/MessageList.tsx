import { cn } from "@/lib/cn";
import type { ChatMessage, ChatRole } from "@/types";

/** 角色中文标签。 */
const ROLE_LABEL: Record<ChatRole, string> = {
  system: "系统",
  user: "我",
  assistant: "助手",
  tool: "工具",
};

/** 角色气泡样式。 */
const ROLE_STYLE: Record<ChatRole, string> = {
  system: "bg-muted text-muted-foreground",
  user: "bg-primary text-primary-foreground",
  assistant: "bg-card",
  tool: "bg-muted",
};

/**
 * 消息列表（W7 / T1-32）。
 *
 * 流式渲染 `message.delta` 增量拼接后的助手消息（`streaming` 时追加光标）。
 */
export function MessageList({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="message-empty">
        暂无消息，输入内容开始对话。
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="message-list">
      {messages.map((message) => (
        <div
          key={message.id}
          data-testid={`message-${message.role}`}
          className={cn("max-w-[85%] rounded-xl border p-3", ROLE_STYLE[message.role])}
        >
          <div className="mb-1 text-xs font-medium opacity-70">{ROLE_LABEL[message.role]}</div>
          <p className="whitespace-pre-wrap break-words text-sm">
            {message.content}
            {message.streaming ? <span className="ml-0.5 animate-pulse">▍</span> : null}
          </p>
        </div>
      ))}
    </div>
  );
}
