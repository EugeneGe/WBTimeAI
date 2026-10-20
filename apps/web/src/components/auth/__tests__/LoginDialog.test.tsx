// ---------------------------------------------------------------------------
// WBTimeAI · LoginDialog 单测（V0.4.5 B4 · F-19.2 / F-19.3）
//
// 覆盖：
//   ① `open=false` → 不渲染弹窗内容（radix Dialog 关态不挂载）；
//   ② `open=true` → 渲染用户名 / 密码 / 提交（冻结 testid）；
//   ③ 提交 → `login.mutate` 被调用（RHF+zod 与 Login 页同口径）；
//   ④ **登录成功** → `runPending()` 执行登记的 pending（如「发送」）并关闭弹窗；
//   ⑤ 校验：空提交 → 显示 i18n 必填错误、不调用登录。
//
// - `useAuth` 以 `vi.mock` 打桩（闭态不发网络）；
// - radix `ui/dialog` 浮层 → 补最小 jsdom 桩（对齐 Composer.test.tsx 范式）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginDialog } from "@/components/auth/LoginDialog";
import { en } from "@/i18n/locales/en";
import { useAuthGateStore } from "@/stores/authGateStore";
import { useI18nStore } from "@/stores/i18nStore";

// --- jsdom 补丁：radix（dialog / floating-ui）所需最小实现 ---
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

// `useAuth` 打桩：暴露稳定 spy 供断言。
const authSpy = vi.hoisted(() => ({ mutate: vi.fn() }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    login: { mutate: authSpy.mutate, isPending: false },
    register: { mutate: vi.fn(), isPending: false },
    logout: { mutate: vi.fn(), isPending: false },
  }),
}));

describe("LoginDialog · V0.4.5 B4 · F-19.2 / F-19.3", () => {
  beforeEach(() => {
    authSpy.mutate.mockReset();
    useI18nStore.setState({ language: "en" });
    useAuthGateStore.setState({ open: false, pending: null });
  });

  it("open=false → 不渲染弹窗内容", () => {
    render(<LoginDialog />);
    expect(screen.queryByTestId("login-dialog")).toBeNull();
  });

  it("open=true → 渲染用户名 / 密码 / 提交", () => {
    useAuthGateStore.setState({ open: true });
    render(<LoginDialog />);

    expect(screen.getByTestId("login-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("login-dialog-username")).toBeInTheDocument();
    expect(screen.getByTestId("login-dialog-password")).toBeInTheDocument();
    expect(screen.getByTestId("login-dialog-submit")).toBeInTheDocument();
  });

  it("提交 → login.mutate 被调用（用户名 / 密码）", async () => {
    useAuthGateStore.setState({ open: true });
    render(<LoginDialog />);

    fireEvent.change(screen.getByTestId("login-dialog-username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("login-dialog-password"), { target: { value: "123456" } });
    fireEvent.click(screen.getByTestId("login-dialog-submit"));

    await waitFor(() =>
      expect(authSpy.mutate).toHaveBeenCalledWith(
        { username: "admin", password: "123456" },
        expect.any(Object),
      ),
    );
  });

  it("登录成功 → runPending 执行 pending 并关闭弹窗", async () => {
    const pending = vi.fn();
    authSpy.mutate.mockImplementationOnce((_values: unknown, options: unknown) => {
      (options as { onSuccess?: () => void } | undefined)?.onSuccess?.();
    });
    useAuthGateStore.setState({ open: true, pending });

    render(<LoginDialog />);
    fireEvent.change(screen.getByTestId("login-dialog-username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("login-dialog-password"), { target: { value: "123456" } });
    fireEvent.click(screen.getByTestId("login-dialog-submit"));

    await waitFor(() => expect(pending).toHaveBeenCalledTimes(1));
    expect(useAuthGateStore.getState().open).toBe(false);
    expect(useAuthGateStore.getState().pending).toBeNull();
  });

  it("校验：空提交 → 显示 i18n 必填错误、不调用登录", async () => {
    useAuthGateStore.setState({ open: true });
    render(<LoginDialog />);

    fireEvent.click(screen.getByTestId("login-dialog-submit"));

    expect(await screen.findByText(en["auth.error.usernameRequired"])).toBeInTheDocument();
    expect(authSpy.mutate).not.toHaveBeenCalled();
  });
});
