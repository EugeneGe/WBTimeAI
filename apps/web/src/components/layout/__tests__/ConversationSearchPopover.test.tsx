// ---------------------------------------------------------------------------
// WBTimeAI · ConversationSearchPopover 单测（V0.4.5 B1·F-02）
//
// 覆盖：
//   ① 打开入口（`sidebar-search`）→ 列表（`conv-search-list`）出现；
//   ② 列表项显示标题 + 智能体名 + `Alt+N` 视觉序号；
//   ③ 关键词按标题过滤（大小写不敏感）；
//   ④ 点击项 → `navigate("/chat?c=<id>")`（冻结契约 C1）并关闭弹层；
//   ⑤ 映射失败的会话不显示智能体标签。
//
// - 只读数据源（`useConversations` / `useAgents`）以 `vi.mock` 打桩；
// - 浮层为 `ui/popover`（radix）→ 补最小 jsdom 桩（范式对齐 Composer.test.tsx）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ConversationSearchPopover } from "@/components/layout/ConversationSearchPopover";

// --- jsdom 补丁：radix（popover / floating-ui）所需最小实现 ---
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe(): void {
      void 0;
    }
    unobserve(): void {
      void 0;
    }
    disconnect(): void {
      void 0;
    }
  } as unknown as typeof ResizeObserver;
}
if (typeof window.PointerEvent === "undefined") {
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = (): void => {
    void 0;
  };
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = (): boolean => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = (): void => {
    void 0;
  };
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = (): void => {
    void 0;
  };
}

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: [
      { id: "c1", title: "Guide Book", agent_id: "a1" },
      { id: "c2", title: "数据分析报告", agent_id: "a2" },
      { id: "c3", title: "杂项记录", agent_id: "aX" },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: [
      { id: "a1", name: "软件架构师" },
      { id: "a2", name: "数据分析专家" },
    ],
    isLoading: false,
  }),
}));

/** 路由探针：渲染当前 `pathname + search`，供导航断言。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 受控测试壳：持有 open 态。 */
function Harness({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <ConversationSearchPopover open={open} onOpenChange={setOpen} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ConversationSearchPopover · F-02", () => {
  it("点击入口 → 列表出现，含标题 / 智能体名 / Alt+N 视觉序号", () => {
    render(<Harness />);
    expect(screen.queryByTestId("conv-search-list")).toBeNull();

    fireEvent.click(screen.getByTestId("sidebar-search"));

    expect(screen.getByTestId("conv-search-list")).toBeInTheDocument();
    expect(screen.getByTestId("conv-search-item-c1")).toHaveTextContent("Guide Book");
    expect(screen.getByTestId("conv-search-item-c1")).toHaveTextContent("软件架构师");
    expect(screen.getByTestId("conv-search-alt-c1")).toHaveTextContent("Alt+1");
    expect(screen.getByTestId("conv-search-alt-c2")).toHaveTextContent("Alt+2");
  });

  it("关键词按标题过滤（大小写不敏感）", () => {
    render(<Harness defaultOpen />);

    fireEvent.change(screen.getByTestId("conv-search-input"), { target: { value: "guide" } });

    expect(screen.getByTestId("conv-search-item-c1")).toBeInTheDocument();
    expect(screen.queryByTestId("conv-search-item-c2")).toBeNull();
    expect(screen.queryByTestId("conv-search-item-c3")).toBeNull();
  });

  it("无匹配时展示空态文案", () => {
    render(<Harness defaultOpen />);

    fireEvent.change(screen.getByTestId("conv-search-input"), { target: { value: "zzz" } });

    expect(screen.getByTestId("conv-search-list")).toHaveTextContent("无匹配对话");
  });

  it("点击项 → navigate(`/chat?c=<id>`) 且关闭弹层", () => {
    render(<Harness defaultOpen />);

    fireEvent.click(screen.getByTestId("conv-search-item-c2"));

    expect(screen.getByTestId("location-probe")).toHaveTextContent("/chat?c=c2");
    expect(screen.queryByTestId("conv-search-list")).toBeNull();
  });

  it("映射失败的会话不显示智能体标签", () => {
    render(<Harness defaultOpen />);

    const item = screen.getByTestId("conv-search-item-c3");
    expect(item).toHaveTextContent("杂项记录");
    expect(item).not.toHaveTextContent("软件架构师");
    expect(item).not.toHaveTextContent("数据分析专家");
  });
});
