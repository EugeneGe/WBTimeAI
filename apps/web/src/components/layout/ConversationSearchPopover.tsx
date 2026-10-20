import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAgents } from "@/hooks/useAgents";
import { useConversations } from "@/hooks/useConversations";
import { cn } from "@/lib/cn";

/**
 * 对话搜索弹层（V0.4.5 B1·F-02）。
 *
 * 侧栏头部「搜索」入口（`sidebar-search`）的受控弹层：顶部搜索框 + 所有对话列表。
 *
 * - 数据源：`useConversations()`（会话列表）+ `useAgents()`（`agent_id` → 智能体名映射）；
 * - 排序/过滤：关键词按**标题**本地过滤（`useMemo` + `toLowerCase().includes`）；
 * - 点击列表项标题 → `navigate(`/chat?c=<id>`)`（**冻结契约 C1**，由 WS-A 写入、
 *   WS-B `Chat` 以 `useSearchParams` 读取 `c` 消费）；随后关闭弹层；
 * - 列表项右侧显示对应智能体名（映射失败则不显示）；左侧 `Alt+N` **仅作视觉序号**
 *   （第 1~9 项），本波**不绑定**真实键盘事件（假定 A-4b，可逆）。
 *
 * 弹层浮层复用 `ui/popover`（radix），零新增依赖。
 */
export interface ConversationSearchPopoverProps {
  /** 受控开合态（由 `Sidebar` 持有）。 */
  open: boolean;
  /** 开合态变更回调（radix 受控模式；Esc / 点击外部关闭亦经此回调）。 */
  onOpenChange: (open: boolean) => void;
}

export function ConversationSearchPopover({ open, onOpenChange }: ConversationSearchPopoverProps) {
  const navigate = useNavigate();
  const { data: conversations } = useConversations();
  const { data: agents } = useAgents();
  const [keyword, setKeyword] = useState("");

  // `agent_id` → 智能体名（映射失败 = undefined → 不显示标签）。
  const agentNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const agent of agents ?? []) {
      map.set(agent.id, agent.name);
    }
    return map;
  }, [agents]);

  const items = useMemo(() => {
    const list = conversations ?? [];
    const needle = keyword.trim().toLowerCase();
    const filtered = needle
      ? list.filter((conversation) => (conversation.title ?? "").toLowerCase().includes(needle))
      : list;
    return filtered.map((conversation) => ({
      id: conversation.id,
      title: conversation.title || "未命名会话",
      agentName: agentNameById.get(conversation.agent_id),
    }));
  }, [conversations, keyword, agentNameById]);

  const handleSelect = (id: string): void => {
    // 冻结契约 C1：路由查询参数名固定为 `c`。
    navigate(`/chat?c=${id}`);
    onOpenChange(false);
  };

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="sidebar-search"
          aria-label="搜索对话"
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground"
        >
          <Search className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        side="bottom"
        sideOffset={6}
        data-testid="conv-search-popover"
        className="w-80 p-2"
      >
        {/* 顶部搜索框 */}
        <div className="mb-2 flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2">
          <Search className="h-3.5 w-3.5 flex-none text-muted-foreground" />
          <Input
            data-testid="conv-search-input"
            value={keyword}
            placeholder="搜索对话"
            onChange={(event) => setKeyword(event.target.value)}
            className="h-6 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
          />
        </div>

        {/* 所有对话列表 */}
        <ul
          data-testid="conv-search-list"
          aria-label="对话列表"
          className="flex max-h-72 flex-col gap-0.5 overflow-y-auto"
        >
          {items.length === 0 ? (
            <li className="px-2 py-3 text-center text-xs text-muted-foreground">
              {keyword.trim() ? "无匹配对话" : "暂无对话"}
            </li>
          ) : (
            items.map((item, index) => (
              <li key={item.id}>
                <button
                  type="button"
                  data-testid={`conv-search-item-${item.id}`}
                  onClick={() => handleSelect(item.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-accent/15",
                  )}
                >
                  {/* Alt+N 仅视觉序号（第 1~9 项；假定 A-4b）。 */}
                  {index < 9 ? (
                    <span
                      aria-hidden
                      data-testid={`conv-search-alt-${item.id}`}
                      className="flex-none rounded border border-border px-1 text-[10px] leading-tight text-muted-foreground"
                    >
                      {`Alt+${index + 1}`}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1 truncate">{item.title}</span>
                  {item.agentName ? (
                    <span className="flex-none rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {item.agentName}
                    </span>
                  ) : null}
                </button>
              </li>
            ))
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
