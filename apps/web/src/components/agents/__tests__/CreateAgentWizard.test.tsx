// ---------------------------------------------------------------------------
// WBTimeAI · CreateAgentWizard 单测（W7 / T1-35 · U-P1-26 ④）
//
// 覆盖：创建向导**四步顺序固定**（选择模型 → 配置 Prompt → 选择 Tool → 绑定 Workspace）
// 且可完成（POST /agents → POST /agents/{id}/publish）；服务端数据经 msw 拦截。
//
// 注意：选择模型 / 绑定 Workspace 已由原生 `<select>` 迁移至
// `@/components/ui/select` 原语（D-UI 体验优化波 · WS-P1 / DU-5），
// 交互走键盘可达路径（与原语单测一致）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateAgentWizard } from "@/components/agents/CreateAgentWizard";
import { useAuthStore } from "@/stores/authStore";

// Radix Select 依赖的 jsdom 缺失 API（指针捕获 / 滚动 / ResizeObserver）。
beforeAll(() => {
  const proto = Element.prototype as Element & {
    hasPointerCapture?: (pointerId: number) => boolean;
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
  }
  if (typeof proto.setPointerCapture !== "function") {
    proto.setPointerCapture = () => {};
  }
  if (typeof proto.releasePointerCapture !== "function") {
    proto.releasePointerCapture = () => {};
  }
  if (typeof HTMLElement.prototype.scrollIntoView !== "function") {
    HTMLElement.prototype.scrollIntoView = () => {};
  }
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
  }
});

/** 渲染向导（带独立 QueryClient；mock 全部命中 msw 契约 handler）。 */
function renderWizard(onCreated = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CreateAgentWizard onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return { onCreated };
}

/** 以键盘路径在 Radix Select 中选中给定名称的项（打开 → 高亮首项 → Enter）。 */
async function selectOption(testId: string, optionName: string): Promise<void> {
  const trigger = screen.getByTestId(testId);
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  await screen.findByRole("option", { name: optionName });
  fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowDown" });
  fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Enter" });
}

describe("CreateAgentWizard", () => {
  beforeEach(() => {
    // 使依赖 `isAuthenticated` 的查询（providers / tools / workspaces）启用。
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("四步向导顺序固定且可完成", async () => {
    const { onCreated } = renderWizard();

    // 步骤标题顺序固定（与设计 §2.14 / §3-#26 一致）。
    expect(screen.getByTestId("wizard-step-0")).toHaveTextContent("选择模型");
    expect(screen.getByTestId("wizard-step-1")).toHaveTextContent("配置 Prompt");
    expect(screen.getByTestId("wizard-step-2")).toHaveTextContent("选择 Tool");
    expect(screen.getByTestId("wizard-step-3")).toHaveTextContent("绑定 Workspace");

    // ---- 第 1 步：选择模型 ----
    await selectOption("provider-select", "OpenAI");
    await selectOption("model-select", "gpt-4o-mini");
    fireEvent.click(screen.getByTestId("wizard-next"));

    // ---- 第 2 步：配置 Prompt ----
    fireEvent.change(screen.getByTestId("agent-name-input"), { target: { value: "Coder" } });
    fireEvent.change(screen.getByTestId("agent-prompt-input"), {
      target: { value: "You are a coding agent." },
    });
    fireEvent.click(screen.getByTestId("wizard-next"));

    // ---- 第 3 步：选择 Tool ----
    await screen.findByTestId("tool-option-git");
    fireEvent.click(screen.getByTestId("tool-option-git"));
    fireEvent.click(screen.getByTestId("wizard-next"));

    // ---- 第 4 步：绑定 Workspace ----
    await selectOption("workspace-select", "Demo Workspace");
    fireEvent.click(screen.getByTestId("wizard-finish"));

    // ---- 完成 ----
    const success = await screen.findByTestId("wizard-success");
    expect(success).toHaveTextContent("创建完成");
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated.mock.calls[0][0]).toMatchObject({ id: "a1", name: "Coder" });
  });
});
