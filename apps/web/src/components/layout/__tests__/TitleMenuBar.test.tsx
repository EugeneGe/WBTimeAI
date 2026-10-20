// ---------------------------------------------------------------------------
// WBTimeAI · TitleMenuBar 单测（V0.4.5 B5 · F-30 顶栏两层化）
//
// 覆盖 F-30 关键口径（用户实测要求 ref28/ref29）：
//   ① 窗口最顶行为「品牌名 + 文件/编辑/视图/帮助 四菜单」，高度 42px、整宽；
//   ② 右侧 `pr-[140px]` 预留系统窗口按钮（overlay）区域；
//   ③ 根元素为窗口拖拽区（`WebkitAppRegion: drag`），菜单容器为 `no-drag`
//      （否则下拉按钮点不动）；
//   ④ 四个菜单入口 `app-menu-{file,edit,view,help}` 均存在。
//
// - `MemoryRouter` 提供 `AppMenuBar` 的 `useNavigate` 上下文；
// - 纯 Web（无 `window.wbtimeAiDesktop`）下：无等价入口的壳动作项（初始化 / 重启后端 / 缩放）
//   仍 disabled；设置 / 关于自 B-03 起回落页内设置弹窗，可点击。
// ---------------------------------------------------------------------------
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TitleMenuBar } from "@/components/layout/TitleMenuBar";
import { en } from "@/i18n/locales/en";
import { useI18nStore } from "@/stores/i18nStore";

/** 渲染 TitleMenuBar（Router 提供 navigate 上下文）。 */
function renderTitleMenuBar(): HTMLElement {
  render(
    <MemoryRouter initialEntries={["/chat"]}>
      <TitleMenuBar />
    </MemoryRouter>,
  );
  return screen.getByTestId("title-menu-bar");
}

describe("TitleMenuBar · V0.4.5 B5 · F-30", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    // 纯 Web 环境：无壳桥（壳动作项 disabled，但不影响渲染断言）。
    delete (window as unknown as Record<string, unknown>).wbtimeAiDesktop;
    vi.clearAllMocks();
  });

  it("渲染品牌名 + 顶栏菜单栏", () => {
    renderTitleMenuBar();

    expect(screen.getByText(en["app.name"])).toBeInTheDocument();
    expect(screen.getByTestId("app-menu-bar")).toBeInTheDocument();
  });

  it("四个菜单入口齐备：文件 / 编辑 / 视图 / 帮助", () => {
    renderTitleMenuBar();

    expect(screen.getByTestId("app-menu-file")).toBeInTheDocument();
    expect(screen.getByTestId("app-menu-edit")).toBeInTheDocument();
    expect(screen.getByTestId("app-menu-view")).toBeInTheDocument();
    expect(screen.getByTestId("app-menu-help")).toBeInTheDocument();
  });

  it("高度 42px（与壳侧 titleBarOverlay.height 一致）+ 整宽 + 右侧留白 140px", () => {
    const bar = renderTitleMenuBar();

    expect(bar.className).toContain("h-[42px]");
    expect(bar.className).toContain("w-full");
    expect(bar.className).toContain("flex-none");
    // 为 overlay 系统窗口按钮预留右侧空间。
    expect(bar.className).toContain("pr-[140px]");
  });

  it("根元素为窗口拖拽区，菜单容器为 no-drag", () => {
    const bar = renderTitleMenuBar();

    // jsdom 的 CSSStyleDeclaration 不认识 `-webkit-app-region`，
    // 但 React 以属性赋值方式写入，故读宿主对象属性校验（Chromium 内行为一致）。
    expect((bar.style as unknown as Record<string, unknown>).WebkitAppRegion).toBe("drag");

    const menuBar = screen.getByTestId("app-menu-bar");
    const menuContainer = menuBar.parentElement as HTMLElement;
    expect((menuContainer.style as unknown as Record<string, unknown>).WebkitAppRegion).toBe(
      "no-drag",
    );
  });

  it("品牌名在菜单之前（左端首位）", () => {
    const bar = renderTitleMenuBar();

    const children = Array.from(bar.children);
    const brandIndex = children.findIndex((el) => el.textContent === en["app.name"]);
    const menuIndex = children.findIndex((el) => el.contains(screen.getByTestId("app-menu-bar")));

    expect(brandIndex).toBe(0);
    expect(menuIndex).toBeGreaterThan(brandIndex);
  });
});
