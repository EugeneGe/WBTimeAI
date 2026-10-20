import { describeTimelineEntry } from "@/lib/chat";
import { cn } from "@/lib/cn";
import type { TimelineEntry } from "@/types";

/** 状态点样式（§4.1 语义色：`warning` 运行中 / `success` 完成 / `destructive` 失败）。 */
const STATUS_DOT: Record<TimelineEntry["status"], string> = {
  running: "bg-warning animate-pulse",
  completed: "bg-success",
  error: "bg-destructive",
};

/** EventTimeline 属性。 */
export interface EventTimelineProps {
  entries: TimelineEntry[];
  /** 点击条目回调（供 Chat 打开右侧栏预览）。 */
  onSelect?: (entry: TimelineEntry) => void;
}

/**
 * 事件时间线（W7 / T1-32；D-UI 体验优化波 · WS-C 旧色与字号收口）。
 *
 * 将 `tool.started/completed`、`mcp.started/completed`、`agent.thinking` 渲染为
 * 「正在调用 … / 已完成 …」时间线条目（文案由 {@link describeTimelineEntry} 生成）。
 * 提供 `onSelect` 时条目可点击（触发右侧栏标签页预览）。
 */
export function EventTimeline({ entries, onSelect }: EventTimelineProps) {
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
          <div className="min-w-0 flex-1">
            {onSelect ? (
              <button
                type="button"
                data-testid={`timeline-open-${entry.id}`}
                onClick={() => onSelect(entry)}
                className="w-full text-left text-xs hover:text-primary"
              >
                {describeTimelineEntry(entry)}
              </button>
            ) : (
              <p className="text-xs">{describeTimelineEntry(entry)}</p>
            )}
            {entry.durationMs !== undefined ? (
              <p className="text-xs text-muted-foreground">{entry.durationMs} ms</p>
            ) : null}
            {entry.error ? <p className="text-xs text-destructive">{entry.error}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
