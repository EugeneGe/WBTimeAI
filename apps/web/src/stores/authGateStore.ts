import { create } from "zustand";

import { hasStoredSession } from "@/lib/token";
import { useAuthStore } from "@/stores/authStore";

/**
 * 认证门控 Zustand store（V0.4.5 B4 · F-19.3，**纯客户端状态**）。
 *
 * 用途：匿名用户可正常渲染整个应用外壳（`RequireAuth` 已放宽），但**受限操作**
 * （如发送消息）仍需登录——`requireAuth(cb)` 作为统一门控点：
 * - **已登录**（内存 `isAuthenticated` 或 localStorage 存在会话）→ **立即执行** `cb` 并返回 `true`；
 * - **未登录** → **打开登录弹窗**并登记 `pending = cb`，返回 `false`（调用方据此中断原操作）。
 *
 * 登录成功后由 `LoginDialog` 调用 `runPending()` 执行此前登记的回调（如「发送」），
 * 随后关闭弹窗。契约对齐裁定 §4.5（`open / pending / requireAuth / closeLogin / runPending`）。
 */
export interface AuthGateState {
  /** 登录弹窗是否打开。 */
  open: boolean;
  /** 待执行回调（登录成功后经 `runPending` 执行）。 */
  pending: (() => void) | null;
  /** 已登录 → 直接执行 `cb` 并返回 `true`；未登录 → 开弹窗登记 `pending` 并返回 `false`。 */
  requireAuth: (cb: () => void) => boolean;
  /** 关闭登录弹窗（并清空待执行回调）。 */
  closeLogin: () => void;
  /** 登录成功后执行 `pending`（由 `LoginDialog` 调用），随后关闭弹窗。 */
  runPending: () => void;
}

/** 判定当前是否已登录（内存态 或 localStorage 会话）。 */
function isAuthenticated(): boolean {
  return useAuthStore.getState().isAuthenticated || hasStoredSession();
}

export const useAuthGateStore = create<AuthGateState>((set, get) => ({
  open: false,
  pending: null,
  requireAuth: (cb) => {
    if (isAuthenticated()) {
      cb();
      return true;
    }
    set({ open: true, pending: cb });
    return false;
  },
  closeLogin: () => set({ open: false, pending: null }),
  runPending: () => {
    const { pending } = get();
    set({ open: false, pending: null });
    pending?.();
  },
}));
