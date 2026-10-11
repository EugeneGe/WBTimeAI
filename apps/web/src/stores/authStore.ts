import { create } from "zustand";

import {
  clearTokens,
  getAccessToken,
  hasStoredSession,
  setAccessToken,
  setRefreshToken,
} from "@/lib/token";
import type { UserResponse } from "@/types";

/**
 * 认证 / 会话 Zustand store（**仅客户端状态**，D6）。
 *
 * - `accessToken` / `user` / `permissions` 均为**客户端状态**（非服务真相源）；
 * - 服务真相源（`/users/me` 等）由 TanStack Query 负责，本 store 仅镜像展示所需字段。
 */

/** Phase 0：Community 默认 `admin = *` 通配（注册用户自动授予 admin 角色）。 */
export const COMMUNITY_WILDCARD_PERMISSIONS: readonly string[] = ["*"];

/**
 * 推导用户权限集。
 *
 * Phase 0 后端**无独立权限清单端点**，且 Community「一个租户 + `admin=*` 通配」，
 * 注册即授予 admin 角色；因此已登录用户权限集为 `["*"]`。
 * （未来接入权限清单端点时，改为按用户加载。）
 */
export function derivePermissions(user: UserResponse | null): string[] {
  if (!user) {
    return [];
  }
  return [...COMMUNITY_WILDCARD_PERMISSIONS];
}

/** 会话写入载荷。 */
export interface SessionPayload {
  accessToken: string;
  refreshToken?: string;
  user?: UserResponse | null;
  permissions?: string[];
}

/** 认证 store 状态与动作。 */
export interface AuthState {
  accessToken: string | null;
  user: UserResponse | null;
  permissions: string[];
  isAuthenticated: boolean;
  setSession: (payload: SessionPayload) => void;
  setUser: (user: UserResponse | null) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: getAccessToken(),
  user: null,
  permissions: [],
  isAuthenticated: hasStoredSession(),
  setSession: ({ accessToken, refreshToken, user, permissions }) => {
    setAccessToken(accessToken);
    if (refreshToken) {
      setRefreshToken(refreshToken);
    }
    set((state) => ({
      accessToken,
      user: user ?? state.user,
      permissions: permissions ?? [...COMMUNITY_WILDCARD_PERMISSIONS],
      isAuthenticated: true,
    }));
  },
  setUser: (user) =>
    set({
      user,
      permissions: derivePermissions(user),
      isAuthenticated: Boolean(user),
    }),
  clearSession: () => {
    clearTokens();
    set({
      accessToken: null,
      user: null,
      permissions: [],
      isAuthenticated: false,
    });
  },
}));
