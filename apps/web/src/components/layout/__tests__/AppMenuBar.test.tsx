// ---------------------------------------------------------------------------
// WBTimeAI · AppMenuBar「帮助」菜单设置/关于入口回归（V0.4.6 BugFix · B-03）
//
// 用户实测：登录后「帮助 → 设置」置灰不可点，而头像菜单的「设置」正常。
// 根因：菜单项 `disabled: !shellAvailable` + 无纯 Web 回落；头像菜单走
// `hasShellAction() ? shellAction(open-settings) : 页内 SettingsDialog`。
//
// 本测试锁两条口径：
//   ① 纯 Web（无 `window.wbtimeAiDesktop`）：设置 / 关于**可点击**并回落页内设置弹窗；
//      无等价入口的「初始化」仍禁用；
//   ② 壳内：设置 / 关于仍走 `shellAction`（不弹页内弹窗）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppMenuBar } from "@/components/layout/AppMenuBar";
import { useI18nStore } from "@/stores/i18nStore";

// 源码原文（Vite `?raw`）：用于断言四个菜单根均为非模态（B-04）。
import appMenuBarSource from "../AppMenuBar.tsx?raw";

/** 渲染顶栏菜单（`SettingsDialog` 依赖 react-query 上下文）。 */
function renderMenu(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/chat"]}>
        <AppMenuBar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 打开 radix DropdownMenu（键盘 Enter 打开，避免 jsdom 指针事件差异）。 */
function openDropdown(trigger: HTMLElement): void {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter", code: "Enter" });
}

/** 移除伪桌面壳（回到纯 Web 环境）。 */
function removeFakeShell(): void {
  (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = undefined;
}

describe("AppMenuBar · 帮助菜单设置入口（V0.4.6 B-03）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useI18nStore.setState({ language: "zh-CN" });
    removeFakeShell();
  });

  afterEach(() => {
    removeFakeShell();
  });

  it("纯 Web：帮助 → 设置 不再禁用，点击回落页内设置弹窗（默认个人分区）", async () => {
    renderMenu();
    openDropdown(screen.getByTestId("app-menu-help"));

    const item = screen.getByTestId("app-menu-item-help-settings");
    expect(item).not.toHaveAttribute("data-disabled");

    fireEvent.click(item);

    await waitFor(() => {
      expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    });
    expect(screen.getByTestId("settings-dialog-nav-profile")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("纯 Web：帮助 → 关于 回落设置·关于分区（同一根因）", async () => {
    renderMenu();
    openDropdown(screen.getByTestId("app-menu-help"));

    const item = screen.getByTestId("app-menu-item-help-about");
    expect(item).not.toHaveAttribute("data-disabled");

    fireEvent.click(item);

    await waitFor(() => {
      expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    });
    expect(screen.getByTestId("settings-dialog-nav-about")).toHaveAttribute("aria-current", "page");
  });

  it("纯 Web：帮助 → 初始化 无等价入口，仍保持禁用", () => {
    renderMenu();
    openDropdown(screen.getByTestId("app-menu-help"));

    expect(screen.getByTestId("app-menu-item-help-guide")).toHaveAttribute("data-disabled");
  });

  it("壳内：帮助 → 设置 走 shellAction(open-settings)，不弹页内弹窗", async () => {
    const shellAction = vi.fn();
    (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = { shellAction };

    renderMenu();
    openDropdown(screen.getByTestId("app-menu-help"));
    fireEvent.click(screen.getByTestId("app-menu-item-help-settings"));

    expect(shellAction).toHaveBeenCalledWith({ action: "open-settings", section: "profile" });
    await waitFor(() => {
      expect(screen.queryByTestId("settings-dialog")).not.toBeInTheDocument();
    });
  });

  it("壳内：帮助 → 关于 走 shellAction(about)", () => {
    const shellAction = vi.fn();
    (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = { shellAction };

    renderMenu();
    openDropdown(screen.getByTestId("app-menu-help"));
    fireEvent.click(screen.getByTestId("app-menu-item-help-about"));

    expect(shellAction).toHaveBeenCalledWith({ action: "about" });
  });

  it("菜单栏：四个顶级菜单均为非模态（B-04，保证一次点击直接切换）", () => {
    // jsdom 无法复现 Radix 的跨菜单 pointerdown 交互（模态层吞事件），
    // 故此处做源码级守卫：四个 `<DropdownMenu>` 必须全部 `modal={false}`。
    // 端到端行为由真机 Chrome（CDP）脚本覆盖（File→Edit→View→Help 单击切换）。
    const roots = appMenuBarSource.match(/<DropdownMenu\b[^>]*>/g) ?? [];

    expect(roots).toHaveLength(4);
    for (const root of roots) {
      expect(root).toContain("modal={false}");
    }
  });
});
