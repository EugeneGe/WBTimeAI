// ---------------------------------------------------------------------------
// WBTimeAI · Register 页单测（批 E6：表单级错误 a11y）
//
// 覆盖：
//   ① 品牌标题走 i18n `auth.register.title`；
//   ② **批 E6**：表单级错误只用 `role="alert"`（**不**叠加 `aria-live="polite"`，
//      两者语义冲突会让读屏播报时机不确定）。
//
// useAuth 内含 useMutation/useNavigate → 需 QueryClient + Router 上下文。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { en } from "@/i18n/locales/en";
import { Register } from "@/pages/Register";
import { useI18nStore } from "@/stores/i18nStore";
import { server } from "@/test/setup";

/** 渲染注册页（独立 QueryClient，禁用重试）。 */
function renderRegister() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Register />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Register · 批 E6（表单级错误 a11y）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
  });

  it("品牌标题走 i18n auth.register.title", () => {
    renderRegister();
    expect(screen.getByText(en["auth.register.title"])).toBeInTheDocument();
  });

  it("表单级错误只用 role=alert（不叠加 aria-live）", async () => {
    server.use(
      http.post("/api/v1/auth/register", () =>
        HttpResponse.json({ code: "CONFLICT", message: "用户名已存在", data: {} }, { status: 409 }),
      ),
    );
    renderRegister();

    fireEvent.change(screen.getByLabelText(en["auth.username"]), { target: { value: "u1" } });
    fireEvent.change(screen.getByLabelText(en["auth.email"]), {
      target: { value: "u1@example.com" },
    });
    fireEvent.change(screen.getByLabelText(en["auth.password"]), { target: { value: "secret1" } });
    fireEvent.click(screen.getByRole("button", { name: en["auth.register.submit"] }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("用户名已存在");
    expect(alert).not.toHaveAttribute("aria-live");
  });
});
