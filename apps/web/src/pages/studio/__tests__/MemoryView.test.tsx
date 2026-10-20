// ---------------------------------------------------------------------------
// WBTimeAI · MemoryView 单测（W6 / T2-35 · U-P2-30；M06-03 删除二次确认 / 空态补充 / 404 中性提示）
//
// 覆盖：① 按 scope 浏览（含来源 Run）；② 删除（**二次确认**）；③ 取消不提交；
//       ④ 404 中性提示 vs 5xx 红字；⑤ 空态「占位存储期」说明。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MemoryView } from "@/pages/studio/MemoryView";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

// --- jsdom 补丁：radix Select（floating-ui）所需最小实现 ---
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
  // jsdom 未实现 PointerEvent；radix Select 依赖 `pointerType === "mouse"`，
  // 故需保留 pointerType 字段（不能简单用 MouseEvent 顶替）。
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    pointerType: string;
    isPrimary: boolean;
    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
      this.pointerId = params.pointerId ?? 1;
      this.pointerType = params.pointerType ?? "mouse";
      this.isPrimary = params.isPrimary ?? true;
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent;
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

/** 经 radix Select 触发器选中项。 */
function selectRadixOption(triggerTestId: string, optionTestId: string): void {
  fireEvent.pointerDown(screen.getByTestId(triggerTestId), {
    button: 0,
    ctrlKey: false,
    pointerType: "mouse",
  });
  fireEvent.click(screen.getByTestId(optionTestId));
}

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
  afterEach(() => {
    // 复位默认语言，避免污染其他测试文件（vitest 同进程复用 store）。
    useI18nStore.setState({ language: "en" });
  });

  beforeEach(() => {
    // 文案断言均为中文 → 用例内显式指定 `zh-CN`（默认语言是 `en`）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("按 scope 浏览并展示来源 Run", async () => {
    renderView();
    expect(await screen.findByTestId("memory-row-mem1")).toBeInTheDocument();
    expect(screen.getByTestId("memory-source-mem1")).toHaveTextContent("run-1");

    // 切换 scope_type（触发按过滤重取）。
    selectRadixOption("memory-scope-type", "memory-scope-type-user");
    expect(await screen.findByTestId("memory-row-mem1")).toBeInTheDocument();
  });

  it("删除一条记忆（M06-03：先二次确认再提交）", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/memory/:memoryId", ({ request }) => {
        deleted.push(new URL(request.url).pathname);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderView();
    const deleteButton = await screen.findByTestId("memory-delete-mem1");
    fireEvent.click(deleteButton);

    // ① 点击「删除」只开确认弹窗，不立即提交。
    const dialog = await screen.findByTestId("memory-delete-dialog");
    expect(dialog).toHaveTextContent("删除后不可恢复");
    expect(screen.queryByTestId("memory-feedback")).toBeNull();
    expect(deleted).toHaveLength(0);

    // ② 确认后才提交 → 反馈「记忆已删除」。
    fireEvent.click(screen.getByTestId("memory-delete-confirm"));
    const feedback = await screen.findByTestId("memory-feedback");
    expect(feedback).toHaveTextContent("记忆已删除");
    // 批 E7：断言**成功语义**本身——文案精确、语气非错误（非红字）、DELETE 命中该条。
    expect(feedback.textContent).toBe("记忆已删除");
    expect(feedback.className).not.toContain("text-destructive");
    expect(deleted).toEqual(["/api/v1/memory/mem1"]);
    await waitFor(() => expect(screen.queryByTestId("memory-delete-dialog")).toBeNull());
  });

  it("M06-03：取消确认 → 不提交删除", async () => {
    let deleted = 0;
    server.use(
      http.delete("/api/v1/memory/:memoryId", () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderView();

    fireEvent.click(await screen.findByTestId("memory-delete-mem1"));
    fireEvent.click(await screen.findByTestId("memory-delete-cancel"));

    await waitFor(() => expect(screen.queryByTestId("memory-delete-dialog")).toBeNull());
    expect(deleted).toBe(0);
    expect(screen.queryByTestId("memory-feedback")).toBeNull();
  });

  it("M06-03：删除 404 → 中性提示（非红字）；5xx → 红字原文", async () => {
    server.use(
      http.delete("/api/v1/memory/:memoryId", () =>
        HttpResponse.json({ code: "NOT_FOUND", message: "记忆不存在", data: {} }, { status: 404 }),
      ),
    );
    renderView();

    fireEvent.click(await screen.findByTestId("memory-delete-mem1"));
    fireEvent.click(await screen.findByTestId("memory-delete-confirm"));

    const feedback = await screen.findByTestId("memory-feedback");
    expect(feedback).toHaveTextContent("占位存储期：该记忆不在可删除范围内");
    expect(feedback.className).not.toContain("text-destructive");

    // 5xx：保持红字提示（原先的错误文案通路）。
    server.use(
      http.delete("/api/v1/memory/:memoryId", () =>
        HttpResponse.json(
          { code: "INTERNAL_ERROR", message: "服务异常", data: {} },
          { status: 500 },
        ),
      ),
    );
    fireEvent.click(screen.getByTestId("memory-delete-mem1"));
    fireEvent.click(await screen.findByTestId("memory-delete-confirm"));

    await waitFor(() =>
      expect(screen.getByTestId("memory-feedback")).toHaveTextContent("服务异常"),
    );
    expect(screen.getByTestId("memory-feedback").className).toContain("text-destructive");
  });

  it("M06-03：空态追加「占位存储期」说明", async () => {
    server.use(http.get("/api/v1/memory", () => shell([])));
    renderView();

    expect(await screen.findByTestId("memory-empty")).toBeInTheDocument();
    expect(screen.getByTestId("memory-empty-hint")).toHaveTextContent(
      "当前为占位存储期，列表为空属预期",
    );
  });
});
