// ---------------------------------------------------------------------------
// WBTimeAI · ProfileSection（设置·个人）单测（V0.4.6 · B-17 扩充）
//
// 覆盖：身份卡保持不动（显示名 / 邮箱回显）+ **四格只读信息**
// （username / display-name / email / user-id；显示名空 → 「—（点铅笔设置）」；
// 用户 ID 走 mono + title 全文）。数据源 `useMe()`（msw `/users/me` handler）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { ProfileSection } from "@/components/settings/sections/ProfileSection";
import { server } from "@/test/setup";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";

/** 渲染 ProfileSection（QueryClient + Router 上下文；useAuth.logout 依赖 navigate）。 */
function renderProfile() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProfileSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProfileSection（设置·个人）", () => {
  beforeEach(() => {
    // 语言固定 zh-CN（产品默认中文界面；对齐 ExpertsTab.test 范式）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("四格只读信息渲染（username / email / user-id 值正确）", async () => {
    renderProfile();

    const username = await screen.findByTestId("settings-profile-field-username");
    await waitFor(() => expect(username).toHaveTextContent("admin"));
    expect(screen.getByTestId("settings-profile-field-email")).toHaveTextContent("admin@local.dev");
    const userId = screen.getByTestId("settings-profile-field-user-id");
    expect(userId).toHaveTextContent("usr_01a13e2e");
    // title 悬浮全文挂在 dd 上。
    expect(within(userId).getByText("usr_01a13e2e")).toHaveAttribute("title", "usr_01a13e2e");
  });

  it("显示名为空 → 「—（点铅笔设置）」；有值 → 回显", async () => {
    const first = renderProfile();
    const displayName = await screen.findByTestId("settings-profile-field-display-name");
    expect(displayName).toHaveTextContent("—（点铅笔设置）");
    first.unmount();

    server.use(
      http.get("/api/v1/users/me", () =>
        HttpResponse.json(
          {
            code: 0,
            message: "ok",
            data: {
              id: "usr_01a13e2e",
              tenant_id: "t1",
              username: "admin",
              email: "admin@local.dev",
              display_name: "观序同学",
              is_active: true,
              is_superuser: true,
              created_at: null,
            },
            request_id: "test-request",
          },
          { status: 200 },
        ),
      ),
    );
    renderProfile();
    const updated = await screen.findByTestId("settings-profile-field-display-name");
    await waitFor(() => expect(updated).toHaveTextContent("观序同学"));
  });

  it("身份卡保持不动（显示名 / 邮箱回显 + 用量区 + 退出登录）", async () => {
    renderProfile();
    expect(await screen.findByTestId("settings-profile")).toBeInTheDocument();
    expect(screen.getByTestId("settings-profile-usage")).toBeInTheDocument();
    expect(screen.getByTestId("settings-profile-logout")).toBeInTheDocument();
  });
});
