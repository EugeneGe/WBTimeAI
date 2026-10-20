// ---------------------------------------------------------------------------
// WBTimeAI · SettingsWindow 独立窗口页单测（V0.4.5 B5 · F-26.5 / F-29）
//
// 覆盖：
//   ① **铺满窗口（F-29）**：根容器 `h-screen w-screen`、无 `p-4` / `justify-center` /
//      `max-w-3xl` / 卡片 `rounded-xl border shadow-sm`（改前「缩水卡片」形态已废弃）；
//   ② 两栏铺满：左导航列固定宽（`w-[200px]`）且撑满高度（`h-full`）+ 右内容区
//      `flex-1` 且 `overflow-y-auto`（滚动只发生在内容区）；
//   ③ 深链 `?section=` 驱动导航高亮（`aria-current="page"`），点击导航切换分区并同步 URL；
//   ④ 容器根 `font-size` 接 `uiStore.fontSize`。
//
// 说明：初始分区取 `shortcuts`（纯展示、零数据依赖）；分区切换目标取 `help`（同为纯展示）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { SettingsWindow } from "@/pages/SettingsWindow";
import { useUiStore } from "@/stores/uiStore";

/** 路由探针：渲染当前 `pathname + search`，供 `?section=` 同步断言。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 渲染设置独立窗口页（路由上下文 + 探针）。 */
function renderWindow(initialEntry = "/settings?section=shortcuts"): void {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <SettingsWindow />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("SettingsWindow · 铺满窗口两栏（V0.4.5 B5·F-29）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ fontSize: 14 });
  });

  it("根容器铺满窗口：h-screen + w-screen，且无卡片外框/居中留白", () => {
    renderWindow();

    const root = screen.getByTestId("settings-window");
    expect(root.className).toContain("h-screen");
    expect(root.className).toContain("w-screen");
    // 改前「缩水卡片」样式一律不得回归。
    expect(root.className).not.toContain("max-w-3xl");
    expect(root.className).not.toContain("justify-center");
    expect(root.className).not.toContain("p-4");
    expect(root.className).not.toContain("rounded-xl");
    expect(root.className).not.toContain("shadow-sm");
  });

  it("内部两栏铺满：左导航固定宽且撑满高度，右内容 flex-1 + 纵向滚动", () => {
    renderWindow();

    const nav = screen.getByTestId("settings-window-nav");
    expect(nav.className).toContain("w-[200px]");
    expect(nav.className).toContain("h-full");
    expect(nav.className).toContain("shrink-0");
    // 独立窗口态不再受弹窗 `max-h-[70vh]` 限制（否则导航列底部留大片空白）。
    expect(nav.className).not.toContain("max-h-[70vh]");

    const content = screen.getByTestId("settings-window-content");
    expect(content.className).toContain("flex-1");
    expect(content.className).toContain("min-w-0");
    expect(content.className).toContain("overflow-y-auto");
  });

  it("深链 ?section=shortcuts → 导航高亮该分区并渲染快捷键内容", () => {
    renderWindow();

    expect(screen.getByTestId("settings-window-nav-shortcuts")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByTestId("settings-shortcuts")).toBeInTheDocument();
  });

  it("点击导航切换分区 → 内容切换且 URL ?section= 同步", () => {
    renderWindow();

    fireEvent.click(screen.getByTestId("settings-window-nav-help"));

    expect(screen.getByTestId("location-probe")).toHaveTextContent("/settings?section=help");
    expect(screen.getByTestId("settings-window-nav-help")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByTestId("settings-shortcuts")).toBeNull();
  });

  it("字体大小接 uiStore.fontSize（容器根 font-size）", () => {
    useUiStore.setState({ fontSize: 16 });
    renderWindow();

    expect(screen.getByTestId("settings-window")).toHaveStyle({ fontSize: "16px" });
  });
});
