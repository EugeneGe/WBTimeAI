import { describeTimelineEntry } from "@/lib/chat";
import { cn } from "@/lib/cn";
import type { TimelineEntry } from "@/types";

/** 状态点样式。 */
const STATUS_DOT: Record<TimelineEntry["status"], string> = {
  running: "bg-blue-500 animate-pulse",
  completed: "bg-emerald-500",
  error: "bg-destructive",
};

/**
 * 事件时间线（W7 / T1-32）。
 *
 * 将 `tool.started/completed`、`mcp.started/completed`、`agent.thinking` 渲染为
 * 「正在调用 … / 已完成 …」时间线条目（文案由 {@link describeTimelineEntry} 生成）。
 */
export function EventTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="event-timeline-empty">
        暂无工具事件
      </p>
    );
  }

  return (
    <ol className="space-y-2" data-testid="event-timeline">
      {entries.map((entry) => (
        <li
          key={entry.id}
          data-testid={`timeline-entry-${entry.kind}`}
          className="flex items-start gap-2"
        >
          <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", STATUS_DOT[entry.status])} />
          <div className="min-w-0">
            <p className="text-xs">{describeTimelineEntry(entry)}</p>
            {entry.durationMs !== undefined ? (
              <p className="text-[11px] text-muted-foreground">{entry.durationMs} ms</p>
            ) : null}
            {entry.error ? <p className="text-[11px] text-destructive">{entry.error}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
