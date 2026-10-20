// ---------------------------------------------------------------------------
// WBTimeAI · EventTimeline 单测（W7 / T1-35 · U-P1-26 ②）
//
// 覆盖：`tool.started/completed`、`mcp.started/completed` 渲染为工具时间线条目
// （"正在调用 … / 已完成 …"）、`agent.thinking`、空态；D-UI WS-C 追加「onSelect 可点击」。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventTimeline } from "@/components/chat/EventTimeline";
import type { TimelineEntry } from "@/types";

/** 构造时间线条目。 */
function entry(
  partial: Partial<TimelineEntry> & Pick<TimelineEntry, "id" | "kind" | "status" | "name">,
): TimelineEntry {
  return { seq: null, ...partial };
}

describe("EventTimeline", () => {
  it("tool.started 渲染为「正在调用 …」", () => {
    render(
      <EventTimeline
        entries={[entry({ id: "tc1", kind: "tool", status: "running", name: "git", seq: 4 })]}
      />,
    );
    expect(screen.getByText("正在调用 git…")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-entry-tool")).toBeInTheDocument();
  });

  it("tool.completed 渲染为「已完成 …」并显示耗时", () => {
    render(
      <EventTimeline
        entries={[
          entry({
            id: "tc1",
            kind: "tool",
            status: "completed",
            name: "git",
            durationMs: 42,
            seq: 5,
          }),
        ]}
      />,
    );
    expect(screen.getByText("已完成 git")).toBeInTheDocument();
    expect(screen.getByText("42 ms")).toBeInTheDocument();
  });

  it("mcp.completed 渲染为「已完成 MCP …」", () => {
    render(
      <EventTimeline
        entries={[entry({ id: "mc1", kind: "mcp", status: "completed", name: "search", seq: 7 })]}
      />,
    );
    expect(screen.getByText("已完成 MCP search")).toBeInTheDocument();
  });

  it("tool 失败条目渲染为「… 调用失败」", () => {
    render(
      <EventTimeline
        entries={[
          entry({
            id: "tc2",
            kind: "tool",
            status: "error",
            name: "shell",
            error: "exit 1",
            seq: 8,
          }),
        ]}
      />,
    );
    expect(screen.getByText("shell 调用失败")).toBeInTheDocument();
    expect(screen.getByText("exit 1")).toBeInTheDocument();
  });

  it("空态提示", () => {
    render(<EventTimeline entries={[]} />);
    expect(screen.getByTestId("event-timeline-empty")).toBeInTheDocument();
  });

  it("提供 onSelect 时条目可点击并回调（D-UI WS-C 右侧栏预览入口）", () => {
    const onSelect = vi.fn();
    render(
      <EventTimeline
        entries={[entry({ id: "tc9", kind: "tool", status: "completed", name: "git", seq: 9 })]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("timeline-open-tc9"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe("tc9");
  });
});
