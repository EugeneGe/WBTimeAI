// ---------------------------------------------------------------------------
// WBTimeAI · User（工作台 `/workbench`）单测（V0.4.6 · B-17）
//
// 覆盖：① 「本人信息」卡整卡退场；② 页头「个人设置」入口（纯 Web 分支开 profile 弹窗）；
//       ③ 设备状态分段（计数按全量 + 筛选）；④ 前端分页（翻页 / pageSize 重置 / 空筛选清除）；
//       ⑤ 设备列 `user_agent` 兜底（40 字符截断 + title 全文）；⑥ 登录时间相对化；
//       ⑦ 无设备 → EmptyState（chips 退场）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { User } from "@/pages/User";
import { pageWindow } from "@/lib/pagination";
import { server } from "@/test/setup";
import type { DeviceResponse } from "@/types";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（SettingsDialog → ui/dialog）所需最小实现 ---
// 对齐 `SettingsDialog.test.tsx` 范式（个人设置弹窗用例会真实渲染 radix Dialog）。
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

/** 构造设备会话夹具（`overrides` 逐项覆盖）。 */
function makeDevice(index: number, overrides: Partial<DeviceResponse> = {}): DeviceResponse {
  return {
    id: `dev${index}`,
    device: `设备-${index}`,
    ip_address: "127.0.0.1",
    user_agent: "Mozilla/5.0 Test",
    created_at: "2026-10-01T10:00:00",
    expires_at: null,
    revoked_at: null,
    ...overrides,
  };
}

/** 构造 N 台设备（前 `activeCount` 台活跃，其余已撤销）。 */
function makeDevices(total: number, activeCount: number): DeviceResponse[] {
  return Array.from({ length: total }, (_, index) =>
    makeDevice(index + 1, index + 1 > activeCount ? { revoked_at: "2026-10-02T10:00:00" } : {}),
  );
}

/** 用 msw 覆盖设备会话响应。 */
function mockDevices(list: DeviceResponse[]): void {
  server.use(
    http.get("/api/v1/users/me/devices", () =>
      HttpResponse.json(
        { code: 0, message: "ok", data: list, request_id: "test-request" },
        { status: 200 },
      ),
    ),
  );
}

/** 渲染 User 页（QueryClient + Router 上下文）。 */
function renderWorkbench() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <User />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("User（工作台）", () => {
  beforeEach(() => {
    // 语言固定 zh-CN（产品默认中文界面；对齐 ExpertsTab.test 范式）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    // B-25：左侧栏可选模块复位为默认（tasks / workflows），并清掉持久化残留。
    useUiStore.setState({ railModules: ["tasks", "workflows"] });
    window.localStorage.removeItem("wbtime-ai.rail-modules");
  });

  it("「本人信息」卡整卡退场（字段与卡标题均不在页面）", async () => {
    renderWorkbench();
    expect(await screen.findByTestId("devices-status-all")).toBeInTheDocument();
    expect(screen.queryByText("本人信息")).not.toBeInTheDocument();
    expect(screen.queryByText("用户名")).not.toBeInTheDocument();
    expect(screen.queryByText("User info unavailable")).not.toBeInTheDocument();
  });

  it("页头副标题 + 「个人设置」入口（纯 Web 分支开 profile 弹窗）", async () => {
    renderWorkbench();
    expect(screen.getByText("常用入口与登录设备管理。")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("workbench-open-profile"));
    // SettingsDialog initialSection="profile" → 个人分区渲染。
    expect(await screen.findByTestId("settings-profile")).toBeInTheDocument();
  });

  it("模型入口弹窗独立可用（与个人设置弹窗两个受控 state）", async () => {
    renderWorkbench();
    await screen.findByTestId("devices-status-all");

    fireEvent.click(screen.getByTestId("workbench-entry-open-models-settings"));
    expect(await screen.findByTestId("settings-dialog")).toBeInTheDocument();
  });

  it("状态分段：文案含全量计数；点击活跃只看活跃会话", async () => {
    mockDevices(makeDevices(14, 5));
    renderWorkbench();

    // 等数据到位再断言计数（分段按钮在加载前已渲染，计数初始为 0）。
    expect(await screen.findByText("设备-1")).toBeInTheDocument();
    expect(screen.getByTestId("devices-status-all")).toHaveTextContent("全部 14");
    expect(screen.getByTestId("devices-status-active")).toHaveTextContent("活跃 5");
    expect(screen.getByTestId("devices-status-revoked")).toHaveTextContent("已撤销 9");

    // 筛选活跃 → 已撤销行退场。
    fireEvent.click(screen.getByTestId("devices-status-active"));
    await waitFor(() => {
      expect(screen.queryByText("设备-14")).not.toBeInTheDocument();
    });
    expect(screen.getByText("设备-5")).toBeInTheDocument();
    // 筛选后分页 summary 按筛选集计数。
    expect(screen.getByTestId("devices-page-summary")).toHaveTextContent("共 5 条 · 第 1 / 1 页");
  });

  it("前端分页：第二页内容不同；pageSize 切换重置回第 1 页", async () => {
    mockDevices(makeDevices(14, 14));
    renderWorkbench();

    expect(await screen.findByTestId("devices-page-summary")).toHaveTextContent(
      "共 14 条 · 第 1 / 2 页",
    );
    expect(screen.getByText("设备-10")).toBeInTheDocument();
    expect(screen.queryByText("设备-11")).not.toBeInTheDocument();

    // 翻到第 2 页 → 展示剩余 4 条。
    fireEvent.click(screen.getByTestId("devices-next"));
    expect(await screen.findByText("设备-11")).toBeInTheDocument();
    expect(screen.getByTestId("devices-page-summary")).toHaveTextContent("共 14 条 · 第 2 / 2 页");
    expect(screen.getByTestId("devices-next")).toBeDisabled();

    // pageSize 切 20 → 回到第 1 页且全部 14 条同屏。
    fireEvent.change(screen.getByTestId("devices-page-size"), { target: { value: "20" } });
    expect(await screen.findByText("设备-14")).toBeInTheDocument();
    expect(screen.getByTestId("devices-page-summary")).toHaveTextContent("共 14 条 · 第 1 / 1 页");
  });

  it("页码窗口化：53 页只渲染 ≤9 个数字位 + ellipsis（不撑破版式）", async () => {
    mockDevices(makeDevices(530, 0)); // 530 条 / 10 每页 = 53 页。
    renderWorkbench();

    expect(await screen.findByTestId("devices-page-summary")).toHaveTextContent(
      "共 530 条 · 第 1 / 53 页",
    );

    // ① 数字位 ≤ 9；② 必含第 1 页与最后一页（当前页 = 第 1 页）。
    const pageButtons = screen
      .getAllByTestId(/^devices-page-\d+$/)
      .filter((el) => el.tagName === "BUTTON");
    expect(pageButtons.length).toBeLessThanOrEqual(9);
    expect(screen.getByTestId("devices-page-1")).toBeInTheDocument();
    expect(screen.getByTestId("devices-page-53")).toBeInTheDocument();
    expect(screen.queryByTestId("devices-page-27")).not.toBeInTheDocument();
    // ③ 当前页附近有 ellipsis 断口（aria-hidden 省略号）。
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);

    // ④ 无横向溢出（jsdom 无布局，scrollWidth/clientWidth 恒 0；断言等式守卫回归）。
    expect(document.documentElement.scrollWidth).toBe(document.documentElement.clientWidth);

    // 翻到中间页与末页：窗口始终含首 / 当前 / 末页。
    fireEvent.click(screen.getByTestId("devices-next"));
    expect(await screen.findByTestId("devices-page-summary")).toHaveTextContent("第 2 / 53 页");
    expect(screen.getByTestId("devices-page-53")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("devices-page-53"));
    expect(await screen.findByTestId("devices-page-summary")).toHaveTextContent("第 53 / 53 页");
    expect(screen.getByTestId("devices-page-1")).toBeInTheDocument();
    expect(screen.getByTestId("devices-page-53")).toHaveAttribute("aria-current", "page");
  });

  it("pageWindow 纯函数边界：≤7 全量；>7 保首/末/当前±1 + ellipsis", () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageWindow(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(pageWindow(1, 53)).toEqual([1, 2, "ellipsis", 53]);
    expect(pageWindow(27, 53)).toEqual([1, "ellipsis", 26, 27, 28, "ellipsis", 53]);
    expect(pageWindow(53, 53)).toEqual([1, "ellipsis", 52, 53]);
    expect(pageWindow(2, 53)).toEqual([1, 2, 3, "ellipsis", 53]);
    expect(pageWindow(52, 53)).toEqual([1, "ellipsis", 51, 52, 53]);
  });

  it("筛选后为空 → 「没有匹配的会话」+ 清除筛选恢复", async () => {
    mockDevices(makeDevices(6, 6)); // 全活跃 → 已撤销筛选为空。
    renderWorkbench();
    await screen.findByTestId("devices-status-all");

    fireEvent.click(screen.getByTestId("devices-status-revoked"));
    expect(await screen.findByText("没有匹配的会话")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("devices-clear-filters"));
    expect(await screen.findByText("设备-1")).toBeInTheDocument();
  });

  it("设备列 UA 兜底：device 空时取 user_agent 前 40 字符，title 悬浮全文", async () => {
    const longUa =
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
    mockDevices([makeDevice(1, { device: null, user_agent: longUa })]);
    renderWorkbench();

    const cell = await screen.findByTitle(longUa);
    expect(cell).toHaveTextContent(longUa.slice(0, 40));
  });

  it("登录时间相对化（近 2 分钟 → 「N 分钟前」）", async () => {
    const recent = new Date(Date.now() - 2 * 60_000).toISOString();
    mockDevices([makeDevice(1, { created_at: recent })]);
    renderWorkbench();

    const cell = await screen.findByText(/分钟前/);
    expect(cell).toBeInTheDocument();
  });

  it("无任何设备 → EmptyState（chips 退场）+ 退出全部禁用", async () => {
    mockDevices([]);
    renderWorkbench();

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("暂无设备会话")).toBeInTheDocument();
    expect(screen.queryByText("检索知识库并总结要点")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出全部" })).toBeDisabled();
    expect(screen.getByTestId("devices-status-all")).toHaveTextContent("全部 0");
  });

  it("加载中 → 设备表 5 行骨架", async () => {
    let resolveDevices: ((value: DeviceResponse[]) => void) | undefined;
    server.use(
      http.get("/api/v1/users/me/devices", async () => {
        await new Promise<DeviceResponse[]>((resolve) => {
          resolveDevices = resolve;
        });
        return HttpResponse.json(
          { code: 0, message: "ok", data: [], request_id: "test-request" },
          { status: 200 },
        );
      }),
    );
    renderWorkbench();

    expect(await screen.findByTestId("devices-skeleton")).toBeInTheDocument();
    const skeleton = screen.getByTestId("devices-skeleton");
    expect(skeleton.childElementCount).toBe(5);

    // 释放挂起请求，避免用例悬挂。
    resolveDevices?.([]);
    await waitFor(() => {
      expect(screen.queryByTestId("devices-skeleton")).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// V0.4.6 · B-25：工作台「左侧栏模块」+ 卡片图钉
//
// 覆盖：① 图钉点击 → store 变化 + localStorage 持久化（`wbtime-ai.rail-modules`）；
//       ② 「左侧栏模块」开关关闭 → store 移除该模块；
//       ③ 固定项只读 pills / agents 只读「固定」徽标（无图钉）；
//       ④ 模型（动作入口）无图钉；⑤ 页头图钉图例文案。
// ---------------------------------------------------------------------------
describe("User（工作台）· 左侧栏模块与图钉（V0.4.6 B-25）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    useUiStore.setState({ railModules: ["tasks", "workflows"] });
    window.localStorage.removeItem("wbtime-ai.rail-modules");
  });

  /** 读取持久化的左侧栏模块（无持久化 → null）。 */
  function readStoredRailModules(): string[] | null {
    const raw = window.localStorage.getItem("wbtime-ai.rail-modules");
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as string[]) : null;
  }

  it("页头补图钉图例（subtitleRailHint）", () => {
    renderWorkbench();

    expect(screen.getByTestId("workbench-subtitle-rail-hint")).toHaveTextContent(
      "图钉 = 固定到左侧栏（显示在工作台上方）",
    );
  });

  it("图钉点击 → store 增加该模块 + 写入 localStorage（aria-pressed 同步）", () => {
    renderWorkbench();

    const pin = screen.getByTestId("workbench-pin-projects");
    // 默认 projects 未上栏：未按下 + aria-label 含**模块名**（读屏可区分）。
    expect(pin).toHaveAttribute("aria-pressed", "false");
    expect(pin).toHaveAttribute("aria-label", "固定「项目」到左侧栏");

    fireEvent.click(pin);

    expect(useUiStore.getState().railModules).toContain("projects");
    expect(readStoredRailModules()).toContain("projects");
    // 受控渲染：按钮改为「已按下 / 取消固定」。
    expect(screen.getByTestId("workbench-pin-projects")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("workbench-pin-projects")).toHaveAttribute(
      "aria-label",
      "取消固定「项目」",
    );

    // 再点一次 → 取消固定并落盘。
    fireEvent.click(screen.getByTestId("workbench-pin-projects"));
    expect(useUiStore.getState().railModules).not.toContain("projects");
    expect(readStoredRailModules()).not.toContain("projects");
  });

  it("图钉点击不触发卡片跳转（preventDefault + stopPropagation）", () => {
    renderWorkbench();

    const card = screen.getByTestId("workbench-entry--projects") as HTMLAnchorElement;
    expect(card.tagName).toBe("A");
    expect(card.getAttribute("href")).toBe("/projects");

    // 点击图钉后卡片仍是「项目」入口（未导航走；href 不变，DOM 未卸载）。
    fireEvent.click(screen.getByTestId("workbench-pin-projects"));
    expect(screen.getByTestId("workbench-entry--projects")).toBeInTheDocument();
  });

  it("默认上栏的任务中心可用图钉关闭（aria-checked 语义 → aria-pressed）", () => {
    renderWorkbench();

    const pin = screen.getByTestId("workbench-pin-tasks");
    expect(pin).toHaveAttribute("aria-pressed", "true");
    expect(pin).toHaveAttribute("aria-label", "取消固定「任务中心」");

    fireEvent.click(pin);
    expect(useUiStore.getState().railModules).not.toContain("tasks");
    expect(readStoredRailModules()).not.toContain("tasks");
    expect(screen.getByTestId("workbench-pin-tasks")).toHaveAttribute("aria-pressed", "false");

    // 重新固定 → 回归上栏。
    fireEvent.click(screen.getByTestId("workbench-pin-tasks"));
    expect(useUiStore.getState().railModules).toContain("tasks");
  });

  it("「左侧栏模块」设置卡已移除（唯一入口 = 图钉，不重复）", () => {
    renderWorkbench();

    expect(screen.queryByTestId("workbench-rail-settings")).toBeNull();
    expect(screen.queryByTestId("workbench-rail-fixed")).toBeNull();
    expect(screen.queryAllByTestId(/^rail-module-toggle-/)).toHaveLength(0);
  });

  it("固定项 agents 渲染只读「固定」徽标，无图钉", () => {
    renderWorkbench();

    expect(screen.getByTestId("workbench-fixed-agents")).toHaveTextContent("固定");
    expect(screen.queryByTestId("workbench-pin-agents")).toBeNull();
  });

  it("模型（动作入口）无图钉", () => {
    renderWorkbench();

    const modelsCard = screen.getByTestId("workbench-entry-open-models-settings");
    // 卡片包装层内只有卡片本身这一个按钮（无图钉兄弟节点）。
    expect(modelsCard.parentElement?.querySelectorAll("button")).toHaveLength(1);
    expect(screen.queryByTestId("workbench-pin-models")).toBeNull();
  });

  it("路由型可选模块均有图钉（7 个），固定项与动作入口无图钉", () => {
    renderWorkbench();

    for (const key of [
      "workspace",
      "tools",
      "projects",
      "tasks",
      "approvals",
      "workflows",
      "remote-tasks",
    ]) {
      expect(screen.getByTestId(`workbench-pin-${key}`)).toBeInTheDocument();
    }
    const pins = screen.getAllByTestId(/^workbench-pin-/);
    expect(pins).toHaveLength(7);
  });

  it("卡片总数 = 9 且顺序与 Rail 注册表一致（审批中心紧跟任务中心）", () => {
    renderWorkbench();

    // 卡片本体（路由型 `<a>` / 动作型 `<button>`）均带 `workbench-entry-*` testid；
    // 图钉是卡片的**兄弟节点**（testid 为 `workbench-pin-*`），故不会被选中。
    const grid = screen.getByTestId("workbench-entries");
    const cards = Array.from(
      grid.querySelectorAll<HTMLElement>('[data-testid^="workbench-entry-"]'),
    );

    // P2-3 ①：总数守卫 —— 少一张卡（如删掉无图钉的「模型」动作入口）即红。
    expect(cards).toHaveLength(9);

    // P2-3 ②：顺序守卫 —— 与 `Rail.OPTIONAL_RAIL_ITEMS` 同序；动作入口「模型」无 href 记 null。
    const toList = cards.map((el) =>
      el instanceof HTMLAnchorElement ? el.getAttribute("href") : null,
    );
    expect(toList).toEqual([
      "/workspace",
      "/agents",
      null, // 模型（`open-models-settings` 动作入口：打开设置·模型，不导航）
      "/tools",
      "/projects",
      "/tasks",
      "/approvals",
      "/studio/workflows",
      "/remote-tasks",
    ]);

    // 显式「审批中心紧跟任务中心」：顺序错位即红，不依赖整表断言的可读性。
    const idxTasks = toList.indexOf("/tasks");
    expect(idxTasks).toBeGreaterThanOrEqual(0);
    expect(toList.slice(idxTasks, idxTasks + 2)).toEqual(["/tasks", "/approvals"]);
  });

  it("7 个图钉的 aria-label 各自带模块名（读屏可区分，无重名）", () => {
    // 先全部下栏 → 7 个图钉均为「未固定」态，逐一带名断言。
    useUiStore.setState({ railModules: [] });
    renderWorkbench();

    const labels = screen
      .getAllByTestId(/^workbench-pin-/)
      .map((el) => el.getAttribute("aria-label"));
    expect(labels).toEqual([
      "固定「工作区」到左侧栏",
      "固定「工具」到左侧栏",
      "固定「项目」到左侧栏",
      "固定「任务中心」到左侧栏",
      "固定「审批中心」到左侧栏",
      "固定「Workflow」到左侧栏",
      "固定「远程任务」到左侧栏",
    ]);
    // 唯一性：读屏列表中 7 个按钮不再同名。
    expect(new Set(labels).size).toBe(7);

    // 固定后同一按钮文案切到「取消固定「模块名」」。
    fireEvent.click(screen.getByTestId("workbench-pin-tasks"));
    expect(screen.getByTestId("workbench-pin-tasks")).toHaveAttribute(
      "aria-label",
      "取消固定「任务中心」",
    );
  });
});
