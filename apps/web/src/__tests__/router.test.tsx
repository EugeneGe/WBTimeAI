// ---------------------------------------------------------------------------
// WBTimeAI · 路由表单测（B-02，V0.4.6 BugFix）
//
// 覆盖：
//   ① 根路径 `/` → **重定向到主窗口 `/chat`**（`replace`，不再渲染工作台）；
//   ② 工作台可迁性：`/workbench` 路由存在（`matchRoutes` 命中）且**仍渲染工作台**（`User` 页）；
//   ③ 回归守卫：索引路由不再指向工作台页（原 `page(<User />)`）。
//
// 断言方式：直接对导出的 `APP_ROUTES`（真实路由表）断言 + 以 `MemoryRouter` 渲染该路由的
// 元素，避免拉起整壳（`RequireAuth` / `AppLayout` / msw 网络）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import {
  MemoryRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  matchRoutes,
  useLocation,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { APP_ROUTES } from "@/router";
import { useI18nStore } from "@/stores/i18nStore";

// 工作台页（`User`）经 `useMe` / `useDevices` 取数 → 打桩避免网络。
vi.mock("@/hooks/useAuth", () => ({
  useMe: () => ({
    data: { id: "u1", username: "alex", email: "alex@example.com", display_name: "Alex" },
    isLoading: false,
  }),
  useDevices: () => ({ data: [], isLoading: false }),
}));

/** 独立 QueryClient（禁用重试，避免用例间串扰）。 */
function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** 路由探针：渲染当前 `pathname`，供重定向断言。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

/** 索引路由条目（`/`）。 */
const INDEX_ROUTE = APP_ROUTES.find((route) => route.index === true);
/** 工作台路由条目（`/workbench`）。 */
const WORKBENCH_ROUTE = APP_ROUTES.find((route) => route.path === "workbench");

describe("router · B-02 默认落地页", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
  });

  it('索引路由存在且为 `<Navigate to="/chat" replace />`（不再渲染工作台）', () => {
    expect(INDEX_ROUTE).toBeDefined();
    const element = INDEX_ROUTE?.element as ReactElement<{ to: string; replace?: boolean }>;
    expect(element.type).toBe(Navigate);
    expect(element.props.to).toBe("/chat");
    expect(element.props.replace).toBe(true);
  });

  it("根路径 `/` 实际跳转到 `/chat`（挂载索引元素观察落点）", async () => {
    render(
      <QueryClientProvider client={newClient()}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route
              path="/"
              element={
                <>
                  <LocationProbe />
                  <Outlet />
                </>
              }
            >
              <Route index element={INDEX_ROUTE?.element} />
              <Route path="chat" element={<div data-testid="chat-stub">chat</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // 跳转生效：落在 `/chat` 占位页（而非工作台）。
    expect(await screen.findByTestId("chat-stub")).toBeInTheDocument();
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/chat");
    // 工作台标识不应出现（未渲染 `User` 页）。
    expect(screen.queryByTestId("workbench-entries")).toBeNull();
  });

  it("工作台仍在路由表中：`/workbench` 命中 `workbench` 条目", () => {
    expect(WORKBENCH_ROUTE).toBeDefined();
    const matches = matchRoutes(APP_ROUTES, "/workbench");
    expect(matches?.at(-1)?.route.path).toBe("workbench");
  });

  it("`/workbench` 仍渲染工作台（`User` 页：workbench-entries）", async () => {
    render(
      <QueryClientProvider client={newClient()}>
        <MemoryRouter initialEntries={["/workbench"]}>
          <Routes>
            <Route path="/workbench" element={WORKBENCH_ROUTE?.element} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("workbench-entries")).toBeInTheDocument();
  });
});
