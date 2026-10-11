import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { queryKeys } from "@/lib/query";
import { authService } from "@/services/auth";
import { useAuthStore } from "@/stores/authStore";
import type { LoginRequest, RegisterRequest, UserResponse } from "@/types";

/** 读取本人信息（登录后引导；写入 authStore 供 UI 展示）。 */
export function useMe() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const setUser = useAuthStore((state) => state.setUser);
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async (): Promise<UserResponse> => {
      const user = await authService.me();
      setUser(user);
      return user;
    },
    enabled: isAuthenticated,
    retry: false,
  });
}

/** 本人设备会话列表。 */
export function useDevices() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.devices,
    queryFn: () => authService.devices(),
    enabled: isAuthenticated,
  });
}

/** 认证动作（登录 / 注册 / 登出）及其会话副作用。 */
export function useAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setSession = useAuthStore((state) => state.setSession);
  const clearSession = useAuthStore((state) => state.clearSession);

  const login = useMutation({
    mutationFn: (payload: LoginRequest) => authService.login(payload),
    onSuccess: (tokens) => {
      setSession({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
      void queryClient.invalidateQueries();
      navigate("/");
    },
  });

  const register = useMutation({
    mutationFn: (payload: RegisterRequest) => authService.register(payload),
    onSuccess: (tokens) => {
      setSession({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
      void queryClient.invalidateQueries();
      navigate("/");
    },
  });

  const logout = useMutation({
    mutationFn: () => authService.logout(),
    onSettled: () => {
      clearSession();
      queryClient.clear();
      navigate("/login");
    },
  });

  return { login, register, logout };
}
