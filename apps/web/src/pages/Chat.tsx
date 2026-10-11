import { useEffect, useState } from "react";

import { EventTimeline } from "@/components/chat/EventTimeline";
import { MessageList } from "@/components/chat/MessageList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAgents } from "@/hooks/useAgents";
import { useChatStream } from "@/hooks/useChatStream";
import { useConversationMessages, useConversations } from "@/hooks/useConversations";
import { SANDBOX_STRENGTH_NOTE } from "@/lib/chat";
import { cn } from "@/lib/cn";
import { toChatMessage, useChatStore } from "@/stores/chatStore";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";

/**
 * Chat 页面（W7 / T1-32）。
 *
 * 单会话 Chat：会话列表 + 消息区（流式 `message.delta` 增量渲染）+ 事件时间线
 * （`tool.started/completed` → "正在调用 … / 已完成 …"）+ 输入框；SSE 经 `fetch` 流
 * 对接 `/agents/{id}/run`，断连重试 + `Last-Event-ID` 续传。
 *
 * 社区形态**明示**「沙箱强度：进程级隔离（非容器级）」（A-5）。
 */
export function Chat() {
  const queryClient = useQueryClient();
  const { data: agents } = useAgents();
  const { data: conversations } = useConversations();

  const [agentId, setAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");

  const messages = useChatStore((state) => state.messages);
  const timeline = useChatStore((state) => state.timeline);
  const streaming = useChatStore((state) => state.streaming);
  const error = useChatStore((state) => state.error);
  const setMessages = useChatStore((state) => state.setMessages);

  const { data: history } = useConversationMessages(conversationId);

  const { sendMessage, cancel } = useChatStream({
    agentId,
    onCompleted: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      const activeConversationId = useChatStore.getState().activeConversationId;
      if (activeConversationId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.conversationMessages(activeConversationId),
        });
      }
    },
  });

  // 默认选中首个 Agent。
  useEffect(() => {
    if (!agentId && agents && agents.length > 0) {
      setAgentId(agents[0].id);
    }
  }, [agents, agentId]);

  // 载入历史消息到流式缓冲（切换会话时）。
  useEffect(() => {
    if (!conversationId || !history) {
      return;
    }
    setMessages(history.map(toChatMessage));
    useChatStore.getState().setActiveConversationId(conversationId);
    useChatStore.setState({ timeline: [], error: null });
  }, [conversationId, history, setMessages]);

  const handleSelectConversation = (id: string) => {
    if (id === conversationId) {
      return;
    }
    setConversationId(id);
    setMessages([]);
    useChatStore.setState({ timeline: [], error: null });
  };

  const handleNewConversation = () => {
    setConversationId(null);
    setMessages([]);
    useChatStore.getState().setActiveConversationId(null);
    useChatStore.setState({ timeline: [], error: null });
  };

  const handleSend = (): void => {
    const text = input.trim();
    if (!text || streaming || !agentId) {
      return;
    }
    setInput("");
    void sendMessage(text, conversationId);
  };

  return (
    <div className="space-y-4">
      {/* 社区沙箱强度明示（A-5）。 */}
      <div
        data-testid="sandbox-strength"
        className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
      >
        {SANDBOX_STRENGTH_NOTE}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-[260px_1fr]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle>会话</CardTitle>
            <Button variant="outline" size="sm" onClick={handleNewConversation}>
              新会话
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-1">
              {(conversations ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">暂无会话</li>
              ) : (
                (conversations ?? []).map((conversation) => (
                  <li key={conversation.id}>
                    <button
                      type="button"
                      data-testid={`conversation-${conversation.id}`}
                      className={cn(
                        "w-full truncate rounded-md px-3 py-2 text-left text-sm hover:bg-accent",
                        conversationId === conversation.id && "bg-accent",
                      )}
                      onClick={() => handleSelectConversation(conversation.id)}
                    >
                      {conversation.title || conversation.id}
                    </button>
                  </li>
                ))
              )}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>对话</CardTitle>
            <div className="flex items-center gap-2 pt-2">
              <label htmlFor="chat-agent" className="text-xs text-muted-foreground">
                Agent
              </label>
              <select
                id="chat-agent"
                data-testid="chat-agent-select"
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={agentId ?? ""}
                onChange={(event) => setAgentId(event.target.value || null)}
              >
                <option value="">请选择</option>
                {(agents ?? []).map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
              {streaming ? <Badge variant="secondary">流式接收中…</Badge> : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <MessageList messages={messages} />

            <div className="rounded-md border p-3">
              <p className="mb-2 text-xs font-medium text-muted-foreground">事件时间线</p>
              <EventTimeline entries={timeline} />
            </div>

            {error ? (
              <p className="text-sm text-destructive" data-testid="chat-error">
                {error}
              </p>
            ) : null}

            <div className="flex items-end gap-2">
              <textarea
                data-testid="chat-input"
                className="h-20 flex-1 rounded-md border border-input bg-background p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="输入消息，回车发送（Shift+Enter 换行）"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    handleSend();
                  }
                }}
              />
              {streaming ? (
                <Button variant="outline" onClick={cancel}>
                  取消
                </Button>
              ) : (
                <Button data-testid="chat-send" onClick={handleSend} disabled={!agentId}>
                  发送
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
