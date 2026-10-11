// ---------------------------------------------------------------------------
// Astra AI · MemoryView 单测（W6 / T2-35 · U-P2-30）
//
// 覆盖：① 按 scope 浏览（含来源 Run）；② 删除。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { MemoryView } from "@/pages/studio/MemoryView";
import { useAuthStore } from "@/stores/authStore";

/** 渲染 Memory 视图（带独立 QueryClient；命中 msw 契约 handler）。 */
function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryView />
    </QueryClientProvider>,
  );
}

describe("MemoryView", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("按 scope 浏览并展示来源 Run", async () => {
    renderView();
    expect(await screen.findByTestId("memory-row-mem1")).toBeInTheDocument();
    expect(screen.getByTestId("memory-source-mem1")).toHaveTextContent("run-1");

    // 切换 scope_type（触发按过滤重取）。
    fireEvent.change(screen.getByTestId("memory-scope-type"), { target: { value: "user" } });
    expect(await screen.findByTestId("memory-row-mem1")).toBeInTheDocument();
  });

  it("删除一条记忆", async () => {
    renderView();
    const deleteButton = await screen.findByTestId("memory-delete-mem1");
    fireEvent.click(deleteButton);
    const feedback = await screen.findByTestId("memory-feedback");
    expect(feedback).toHaveTextContent("记忆已删除");
  });
});
