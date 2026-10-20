// ---------------------------------------------------------------------------
// WBTimeAI · Workspace 单测（V0.4.6 · B-23 工作区页重排）
//
// 覆盖：
//   ① 左列列表：名称 / 类型 / 创建时间（MM-DD）；
//   ② 选中工作区 → 右侧详情三格 + JSON 设置区；
//   ③ 新建工作区弹窗（`workspace:create` 守卫内）→ 创建成功反馈；
//   ④ 非法 JSON → 行内报错且**不发** `PUT /workspaces/{id}/settings`；
//   ⑤ 「格式化」按 2 空格重排 JSON；
//   ⑥ 「复制 ID」走 `navigator.clipboard.writeText` 并就地反馈「已复制」；
//   ⑦ 页面**无**「删除 / 重命名」文案（能力缺口不在本单，界面不放假按钮）。
//
// 以 msw 打桩冻结 DTO（snake_case + 统一响应壳）；断言请求命中的**路径**。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { Workspace } from "@/pages/Workspace";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** jsdom 缺失的指针 / 滚动 / 观察器 API（Radix Dialog 需要）。 */
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

/** 工作区夹具 A（`settings` 含嵌套对象，供格式化 / 重置用例）。 */
const WS_A = {
  id: "w1",
  tenant_id: "t1",
  owner_id: "u1",
  name: "研发中心",
  workspace_type: "TEAM",
  settings: { default_branch: "main", sandbox: { network: "offline" } },
  config: {},
  created_at: "2026-10-10T09:12:00",
  updated_at: "2026-10-18T17:20:00",
};

/** 工作区夹具 B（类型 / 创建时间差异）。 */
const WS_B = {
  ...WS_A,
  id: "w2",
  name: "个人沙箱",
  workspace_type: "PERSONAL",
  settings: {},
  created_at: "2026-10-14T10:00:00",
  updated_at: "2026-10-15T10:00:00",
};

/** 新建返回的工作区（201）。 */
const WS_NEW = { ...WS_A, id: "w3", name: "数据平台", settings: {} };

/** `PUT` 调用计数（断言「非法 JSON 不发请求」）。 */
let putCount = 0;

/** `navigator.clipboard.writeText` 桩（用例内复位）。 */
const writeText = vi.fn(() => Promise.resolve());

/** 渲染 Workspace（独立 QueryClient + Router 上下文，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/workspace"]}>
        <Workspace />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Workspace", () => {
  beforeEach(() => {
    putCount = 0;
    writeText.mockClear();
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });

    server.use(
      http.get("/api/v1/workspaces", () => shell([WS_A, WS_B])),
      http.get("/api/v1/workspaces/:workspaceId", ({ params }) =>
        shell(params.workspaceId === "w2" ? WS_B : params.workspaceId === "w3" ? WS_NEW : WS_A),
      ),
      http.post("/api/v1/workspaces", () => shell(WS_NEW, 201)),
      http.put("/api/v1/workspaces/:workspaceId/settings", () => {
        putCount += 1;
        return shell(WS_A);
      }),
    );
  });

  it("左列列表展示类型与创建时间", async () => {
    renderPage();

    const rowA = await screen.findByTestId("workspace-row-w1");
    expect(rowA).toHaveTextContent("研发中心");
    expect(rowA).toHaveTextContent("TEAM");
    // 项目数只读缓存：未访问项目页 → `—`；创建时间按 MM-DD 展示。
    expect(screen.getByTestId("workspace-row-meta-w1")).toHaveTextContent("TEAM · — · 10-10");

    expect(screen.getByTestId("workspace-row-meta-w2")).toHaveTextContent("PERSONAL · — · 10-14");
  });

  it("选中工作区展示详情信息与设置区", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("workspace-row-w1"));

    expect(await screen.findByTestId("workspace-id")).toHaveTextContent("w1");
    expect(screen.getByTestId("workspace-created-at")).toHaveTextContent("2026-10-10 09:12");
    expect(screen.getByTestId("workspace-settings-input")).toHaveValue(
      JSON.stringify(WS_A.settings, null, 2),
    );
    expect(screen.getByTestId("workspace-json-status")).toHaveTextContent("合法");
  });

  it("新建工作区弹窗：创建成功后关闭并选中", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("workspace-create-open"));
    fireEvent.change(await screen.findByTestId("workspace-name-input"), {
      target: { value: "数据平台" },
    });
    fireEvent.click(screen.getByTestId("workspace-create-submit"));

    expect(await screen.findByTestId("workspace-feedback")).toHaveTextContent("创建成功");
    await waitFor(() => expect(screen.queryByTestId("workspace-create-dialog")).toBeNull());
    expect(await screen.findByTestId("workspace-id")).toHaveTextContent("w3");
  });

  it("非法 JSON：行内报错且不发 PUT", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("workspace-row-w1"));

    fireEvent.change(await screen.findByTestId("workspace-settings-input"), {
      target: { value: "{ oops" },
    });

    expect(screen.getByTestId("workspace-json-status")).toHaveTextContent("非法");
    expect(screen.getByTestId("workspace-json-error")).toHaveTextContent("JSON 非法");

    fireEvent.click(screen.getByTestId("workspace-settings-save"));

    expect(screen.getByTestId("workspace-feedback")).toHaveTextContent("未提交");
    expect(putCount).toBe(0);
  });

  it("格式化按钮按 2 空格重排 JSON", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("workspace-row-w1"));

    const raw = '{"b":1,"a":[2,3]}';
    fireEvent.change(await screen.findByTestId("workspace-settings-input"), {
      target: { value: raw },
    });
    fireEvent.click(screen.getByTestId("workspace-json-format"));

    expect(screen.getByTestId("workspace-settings-input")).toHaveValue(
      JSON.stringify(JSON.parse(raw), null, 2),
    );
  });

  it("复制 ID 调用 clipboard 并就地反馈「已复制」", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("workspace-row-w1"));

    fireEvent.click(await screen.findByTestId("workspace-copy-id"));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("w1"));
    await waitFor(() =>
      expect(screen.getByTestId("workspace-copy-id")).toHaveTextContent("已复制"),
    );
  });

  it("页面无「删除 / 重命名」入口与文案", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("workspace-row-w1"));
    expect(await screen.findByTestId("workspace-id")).toBeInTheDocument();

    expect(screen.queryByText(/删除/)).toBeNull();
    expect(screen.queryByText(/重命名/)).toBeNull();
  });
});
