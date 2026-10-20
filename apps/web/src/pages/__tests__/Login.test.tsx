// ---------------------------------------------------------------------------
// WBTimeAI · Login 页单测（V0.4.4 品牌字中文化 + V0.4.5 B4 · F-19.2 文案修订）
//
// 覆盖：
//   ① 品牌标题「登录 观序智能平台」（zh-CN 口径）；
//   ② **F-19.2**：移除「初始管理员凭据」提示段（`login-default-admin-hint` 不存在，Q4=c）；
//   ③ **F-19.2**：「口令」→「密码」（副标题「使用用户名与密码登录」+ 密码标签）；
//   ④ **批 E6**：表单级错误只用 `role="alert"`（**不**叠加 `aria-live="polite"`）。
//
// useAuth 内含 useMutation/useNavigate → 需 QueryClient + Router 上下文。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { en } from "@/i18n/locales/en";
import { Login } from "@/pages/Login";
import { useI18nStore } from "@/stores/i18nStore";
import { server } from "@/test/setup";

function renderLogin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Login · V0.4.5 B4 · F-19.2（文案修订）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
  });

  it("品牌标题中文化（zh-CN）：登录 观序智能平台", () => {
    useI18nStore.setState({ language: "zh-CN" });
    renderLogin();
    expect(screen.getByText("登录 观序智能平台")).toBeInTheDocument();
    expect(screen.getByText("使用用户名与密码登录")).toBeInTheDocument();
  });

  it("默认英文：标题走 i18n auth.login.title", () => {
    renderLogin();
    expect(screen.getByText(en["auth.login.title"])).toBeInTheDocument();
  });

  it("F-19.2：移除「初始管理员凭据」提示段（login-default-admin-hint 不存在）", () => {
    renderLogin();
    expect(screen.queryByTestId("login-default-admin-hint")).toBeNull();
    expect(screen.queryByText(/初始管理员/)).toBeNull();
  });

  it("F-19.2：「口令」→「密码」（标签 + 副标题）", () => {
    renderLogin();
    // 密码标签走 i18n auth.password。
    expect(screen.getByLabelText(en["auth.password"])).toBeInTheDocument();
    // 旧「口令」文案不再出现。
    expect(screen.queryByText("口令")).toBeNull();
  });

  it("批 E6：表单级错误只用 role=alert（不叠加 aria-live）", async () => {
    server.use(
      http.post("/api/v1/auth/login", () =>
        HttpResponse.json(
          { code: "UNAUTHORIZED", message: "用户名或密码错误", data: {} },
          { status: 401 },
        ),
      ),
    );
    renderLogin();

    fireEvent.change(screen.getByLabelText(en["auth.username"]), { target: { value: "u1" } });
    fireEvent.change(screen.getByLabelText(en["auth.password"]), { target: { value: "p1" } });
    fireEvent.click(screen.getByRole("button", { name: en["auth.login.submit"] }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("用户名或密码错误");
    // `role="alert"` 隐含 assertive；再叠 `aria-live="polite"` 会让播报时机不确定。
    expect(alert).not.toHaveAttribute("aria-live");
  });
});
