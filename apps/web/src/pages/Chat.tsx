import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Composer } from "@/components/chat/Composer";
import { MessageList } from "@/components/chat/MessageList";
import { EmptyState } from "@/components/common/EmptyState";
import { Badge } from "@/components/ui/badge";
import { useAgents } from "@/hooks/useAgents";
import { useChatStream } from "@/hooks/useChatStream";
import { useConversationMessages } from "@/hooks/useConversations";
import { useTranslation } from "@/i18n";
import { queryKeys } from "@/lib/query";
import { useAuthGateStore } from "@/stores/authGateStore";
import { toChatMessage, useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";

// 冻结契约 C3（V0.4.5 B1 · F-03）：`SANDBOX_STRENGTH_NOTE` 常量**保留并继续对外导出**
// （合规明示已迁移至设置弹窗「系统」分区，供 WS-C 复用）；本文件仅移除 Chat 主区的
// banner **展示**（假定 A-1），**不改**常量名/定义，亦不删除常量来源 `lib/chat.ts`。
export { SANDBOX_STRENGTH_NOTE } from "@/lib/chat";

/**
 * Chat 页面（W7 / T1-32；V0.4.5 B1 追加波 · WS-B / F-03；B3 · F-09 去重；B4 · F-19.3 / F-20.3）。
 *
 * 聊天主区（精简后）：
 * - **删除**「会话 / 时间线」两栏与其切换按钮、Agent「请选择」下拉、顶部沙箱强度 banner
 *   （假定 A-1；`SANDBOX_STRENGTH_NOTE` 常量保留并对外导出）；
 * - 聊天面板**满宽**（单列常驻，不再随两栏开关切换 `grid`）；
 * - sub-header（`data-testid="chat-titlebar"`）**仅保留容器**（承载流式态 Badge）：
 *   V0.4.5 B3·F-09 起，**会话标题**迁至 `Topbar`（去重，§2.4），本文件不再渲染标题文字，
 *   并**去除 `border-b`**（ref07「中间不要横线」）；
 * - 消费查询参数 **`?c=<conversationId>`**（冻结契约 C1；写入方 WS-A 侧栏搜索）→ 选中对应
 *   会话并载入其历史消息。
 *
 * V0.4.5 B4 追加：
 * - **F-19.3**：`handleSend` 首行经 `requireAuth` 门控——未登录 → 打开登录弹窗并登记待发送，
 *   登录成功后 `runPending` 执行原发送（已登录路径行为不变）；
 * - **F-20.3**：**无消息** → 欢迎区（`EmptyState`）+ 输入台**同屏竖向居中**（ChatGPT 空态形态）；
 *   **有消息** → 消息列表 + 输入台**置底**。
 *
 * 保留：`EmptyState` 欢迎态（chips 点击回填输入）、`MessageList`、`Composer` **常驻**、
 * `pageSearch` opt-in（`Topbar` 内联搜索仍可用）、`error` 行；会话 / 时间线**数据流**
 * （`EventTimeline` 组件、`chatStore.timeline`）一律保留（假定 A-2，纯 UI 下线）。
 */
export function Chat() {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const { data: agents } = useAgents();

  const [agentId, setAgentId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  // 批 F · F1：深链指向的会话查询失败（404 已删除 / 其它）→ 用户可见提示开关。
  const [deepLinkMissing, setDeepLinkMissing] = useState(false);

  // 查询参数（C1 `?c=` 会话深链；V0.4.6 `?agent=` 专家预选）。
  const [searchParams, setSearchParams] = useSearchParams();
  const queryAgentId = searchParams.get("agent");

  // 本页 opt-in 页面搜索（卸载时复位，避免残留到其它页面）。
  const pageSearch = useUiStore((state) => state.pageSearch);
  const setPageSearch = useUiStore((state) => state.setPageSearch);
  useEffect(() => {
    setPageSearch({ enabled: true, placeholder: "搜索会话与消息…" });
    return () => {
      setPageSearch({ enabled: false, query: "" });
    };
  }, [setPageSearch]);
  const searchKeyword = pageSearch.query.trim().toLowerCase();

  const messages = useChatStore((state) => state.messages);
  const streaming = useChatStore((state) => state.streaming);
  const error = useChatStore((state) => state.error);
  const setMessages = useChatStore((state) => state.setMessages);

  // F-19.3：认证门控（未登录 → 登录弹窗）。
  const requireAuth = useAuthGateStore((state) => state.requireAuth);

  // 批 F · F1：拿完整查询状态（不只 data）——error 分支供深链失效自愈。
  const historyQuery = useConversationMessages(conversationId);
  const { data: history, isError: historyFailed } = historyQuery;

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

  // V0.4.6 · D3：`?agent=<id>` 预选专家（专家卡「开始对话」落地页）。
  // 仅在 agents 列表加载完成且该 id **存在** 时生效；非法 / 已删除 id 静默忽略（交由下方默认选中）。
  const appliedQueryAgentRef = useRef<string | null>(null);
  const hasValidQueryAgent =
    Boolean(queryAgentId) && (agents ?? []).some((agent) => agent.id === queryAgentId);
  useEffect(() => {
    if (!queryAgentId || appliedQueryAgentRef.current === queryAgentId) {
      return;
    }
    if (!agents) {
      return;
    }
    if (!agents.some((agent) => agent.id === queryAgentId)) {
      return;
    }
    appliedQueryAgentRef.current = queryAgentId;
    setAgentId(queryAgentId);
  }, [queryAgentId, agents]);

  // 默认选中首个 Agent（存在合法 `?agent=` 预选时不覆盖）。
  useEffect(() => {
    if (agentId || hasValidQueryAgent) {
      return;
    }
    if (agents && agents.length > 0) {
      setAgentId(agents[0].id);
    }
  }, [agents, agentId, hasValidQueryAgent]);

  // 载入历史消息到流式缓冲（切换会话时）。
  useEffect(() => {
    if (!conversationId || !history) {
      return;
    }
    setMessages(history.map(toChatMessage));
    useChatStore.getState().setActiveConversationId(conversationId);
    useChatStore.setState({ timeline: [], error: null });
  }, [conversationId, history, setMessages]);

  // 冻结契约 C1：消费 `?c=<id>`（WS-A 侧栏搜索写入）→ 选中对应会话并进入其聊天页。
  // 以 ref 记录已应用的 id，避免同一 `c` 反复触发（无 `c` = 新会话，不动现状）。
  const queryConversationId = searchParams.get("c");
  const appliedQueryIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!queryConversationId || appliedQueryIdRef.current === queryConversationId) {
      return;
    }
    appliedQueryIdRef.current = queryConversationId;
    setConversationId(queryConversationId);
    setMessages([]);
    setDeepLinkMissing(false);
    useChatStore.getState().setActiveConversationId(queryConversationId);
    useChatStore.setState({ timeline: [], error: null });
  }, [queryConversationId, setMessages]);

  // 批 F · F1：深链历史查询失败（404 会话已删 / 其它错误）→ 自愈，杜绝「静默空态 + 脏 id 残留」：
  // ① 清深链选中态（本地 `conversationId` + `chatStore.activeConversationId`）——
  //    确保下一条消息**不会**带着脏 id 发送（`sendMessage` 的 fallback 取 store 值，见
  //    `useChatStream` effectiveConversationId）；
  // ② `?c=` 从 URL **replace** 掉（保留其它查询参数；不产生历史记录）；
  // ③ 显示用户可见提示（i18n `chat.deepLink.missing`，欢迎态上方一行）。
  useEffect(() => {
    if (!conversationId || !historyFailed) {
      return;
    }
    setConversationId(null);
    useChatStore.getState().setActiveConversationId(null);
    setDeepLinkMissing(true);
    setSearchParams(
      (previous: URLSearchParams) => {
        const next = new URLSearchParams(previous);
        next.delete("c");
        return next;
      },
      { replace: true },
    );
  }, [conversationId, historyFailed, setSearchParams]);

  const handleSend = (): void => {
    const text = input.trim();
    if (!text || streaming) {
      return;
    }
    // Bug6d：无 Agent（列表为空 / 加载失败）时明示，不再静默。
    if (!agentId) {
      useUiStore.getState().showToast({ title: "请先选择 Agent" });
      return;
    }
    // F-19.3：受限操作门控——已登录 → 立即执行原发送；未登录 → 打开登录弹窗并登记待发送。
    requireAuth(() => {
      setInput("");
      void sendMessage(text, conversationId);
    });
  };

  // 本页搜索 → 过滤当前消息（仅本页数据，不动其它页面）。
  const visibleMessages = searchKeyword
    ? messages.filter((message) => message.content.toLowerCase().includes(searchKeyword))
    : messages;
  const hasMessages = visibleMessages.length > 0;

  // 输入台节点（两布局分支复用；同一时刻仅其一渲染）。
  const composerNode = (
    <Composer
      value={input}
      onChange={setInput}
      onSend={handleSend}
      streaming={streaming}
      onCancel={cancel}
      agentId={agentId}
      onAgentChange={setAgentId}
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 聊天面板满宽：中栏 `section` 独占宽度（去掉 grid，改单列常驻）。 */}
      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card">
        {/* 标题栏容器：会话标题已迁至 Topbar（F-09 去重）；此处仅保留流式态 Badge，去横线。 */}
        <header data-testid="chat-titlebar" className="flex flex-none items-center gap-2 px-4 py-2">
          {streaming ? (
            <Badge variant="secondary" className="ml-auto">
              流式接收中…
            </Badge>
          ) : null}
        </header>

        {hasMessages ? (
          // 有消息：消息列表 + 输入台**置底**（F-20.3）。
          <>
            <div className="flex-1 overflow-auto p-4">
              <MessageList messages={visibleMessages} />
            </div>

            {error ? (
              <p className="flex-none px-4 text-sm text-destructive" data-testid="chat-error">
                {error}
              </p>
            ) : null}

            {/* Composer 常驻（对话与运行态不消失）。 */}
            <div className="flex-none border-t border-border p-3">{composerNode}</div>
          </>
        ) : (
          // 无消息：欢迎区 + 输入台**同屏竖向居中**（ChatGPT 空态形态，F-20.3）。
          <div className="flex flex-1 flex-col items-center justify-center gap-6 overflow-auto p-4">
            {/* 批 F · F1：深链会话不存在 / 已删除 → 欢迎态上方一行提示（不静默）。 */}
            {deepLinkMissing ? (
              <p data-testid="chat-deeplink-missing" className="text-sm text-muted-foreground">
                {t("chat.deepLink.missing")}
              </p>
            ) : null}

            <EmptyState
              chips={[
                // B-01：欢迎态 chips 走 i18n（点击仍回填输入框，行为不变）。
                t("chat.greeting.chip.1"),
                t("chat.greeting.chip.2"),
                t("chat.greeting.chip.3"),
              ]}
              onChip={(chip) => setInput(chip)}
            />

            <div className="w-full">{composerNode}</div>

            {error ? (
              <p className="text-sm text-destructive" data-testid="chat-error">
                {error}
              </p>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
