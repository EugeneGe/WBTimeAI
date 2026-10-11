// ---------------------------------------------------------------------------
// Astra AI · KnowledgeManager 单测（W6 / T2-35 · U-P2-30）
//
// 覆盖：① 文档 `status` 索引进度展示；② 检索试跑（命中 + 引用 + 检索路提示）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { KnowledgeManager } from "@/pages/studio/KnowledgeManager";
import { useAuthStore } from "@/stores/authStore";

/** 渲染 Knowledge Manager（带独立 QueryClient；命中 msw 契约 handler）。 */
function renderManager() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <KnowledgeManager />
    </QueryClientProvider>,
  );
}

describe("KnowledgeManager", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("展示文档 status 索引进度", async () => {
    renderManager();
    // 首个知识库自动选中 → 文档列表加载。
    expect(await screen.findByTestId("kb-item-Handbook")).toBeInTheDocument();
    expect(await screen.findByTestId("doc-status-guide.md")).toHaveTextContent("READY");
    expect(screen.getByTestId("doc-progress-guide.md")).toBeInTheDocument();
  });

  it("检索试跑：命中 + 引用 + 关键字检索提示", async () => {
    renderManager();
    await screen.findByTestId("kb-item-Handbook");

    fireEvent.change(screen.getByTestId("search-query-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("search-submit"));

    // 命中（引用可回溯）。
    expect(await screen.findByTestId("search-hit-chk1")).toHaveTextContent("Hello world");
    expect(screen.getByTestId("search-hit-source-chk1")).toHaveTextContent("doc1");
    // 关键字路提示（非语义检索）。
    expect(screen.getByTestId("search-mode-hint")).toHaveTextContent("已使用关键字检索");
  });
});
