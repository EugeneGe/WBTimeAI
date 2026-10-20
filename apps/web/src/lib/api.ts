import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { getAccessToken, getRefreshToken } from "@/lib/token";
import { useAuthStore } from "@/stores/authStore";
import type { ApiError, TokenResponse } from "@/types";

/**
 * axios 实例（D6 · Token 刷新策略，定稿）。
 *
 * - `baseURL` = `VITE_API_BASE`（默认 `/api/v1`，经 Vite proxy 到后端）；
 * - 请求拦截：注入 `Authorization: Bearer <access>`；
 * - **成功响应统一响应壳（总纲 §11.1）**：`{code,message,data,request_id}` →
 *   拦截器**解壳**（`response.data = shell.data`），服务层仍直接拿到业务 DTO；
 * - 响应拦截：401 → **单飞去重**刷新（共享同一 Promise）→ 写回两 token →
 *   原请求**重试一次**；刷新失败 → `clearSession()` + 跳 `/login`。
 *
 * ⚠️ 本模块**不含**任何后端 `mode` 判断。
 */

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

/** 统一响应壳（总纲 §11.1；成功 `code=0`，失败为 `ErrorCode` 字面值）。 */
export interface ResponseShell<T = unknown> {
  code: number | string;
  message: string;
  data: T;
  request_id?: string;
}

/** 判定响应体是否为统一响应壳。 */
export function isResponseShell(value: unknown): value is ResponseShell {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "message" in value &&
    "data" in value
  );
}

/** 标记已重试的请求配置（避免无限重试）。 */
interface RetriableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

const AUTH_ENDPOINTS = ["/auth/login", "/auth/register", "/auth/refresh"];

function isAuthEndpoint(url?: string): boolean {
  if (!url) {
    return false;
  }
  return AUTH_ENDPOINTS.some((endpoint) => url.includes(endpoint));
}

/** 判定任意值是否**已是归一化后的** {@link ApiError} 形状（幂等短路用）。 */
function isApiErrorShape(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiError).code === "string" &&
    typeof (value as ApiError).message === "string" &&
    typeof (value as ApiError).data === "object" &&
    (value as ApiError).data !== null
  );
}

/**
 * 将任意错误归一化为 {@link ApiError}。
 *
 * 🔴 **幂等**：输入**已是** {@link ApiError} 形状（如响应拦截器归一化后的错误，被各页 `onError`
 *    二次传入）→ **原样返回**，避免二次归一吞掉服务端 `message`（退化为恒「未知错误」）。
 *    非归一化输入行为不变。
 */
export function toApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const body = (error.response?.data ?? {}) as Partial<ApiError>;
    return {
      code: body.code ?? `HTTP_${error.response?.status ?? "NETWORK"}`,
      message: body.message ?? error.message ?? "请求失败",
      data: body.data ?? {},
      status: error.response?.status,
    };
  }
  if (isApiErrorShape(error)) {
    return error;
  }
  if (error instanceof Error) {
    return { code: "CLIENT_ERROR", message: error.message, data: {} };
  }
  return { code: "UNKNOWN_ERROR", message: "未知错误", data: {} };
}

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

/** 在途 refresh（单飞去重：并发 401 共享同一 Promise）。 */
let refreshInFlight: Promise<string> | null = null;

/** 使用 refresh token 换取新令牌组，并写回两 token（旋转）。 */
async function requestRefresh(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("缺少 refresh token");
  }
  // 使用裸 axios，避免经过本实例的拦截器造成递归。
  const response = await axios.post<ResponseShell<TokenResponse>>(
    `${API_BASE}/auth/refresh`,
    { refresh_token: refreshToken },
    { headers: { "Content-Type": "application/json" } },
  );
  // 裸 axios 不经本实例的解壳拦截器 → 手动取 `data`。
  const tokens = response.data.data;
  useAuthStore.getState().setSession({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
  });
  return tokens.access_token;
}

function redirectToLogin(): void {
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

api.interceptors.response.use(
  (response) => {
    // 统一响应壳（总纲 §11.1）：成功体 `{code:0,message:"ok",data,request_id}` → 解壳。
    const body: unknown = response.data;
    if (isResponseShell(body)) {
      response.data = body.data;
    }
    return response;
  },
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined;
    const status = error.response?.status;

    if (status === 401 && config && !config._retry && !isAuthEndpoint(config.url)) {
      config._retry = true;
      try {
        if (!refreshInFlight) {
          refreshInFlight = requestRefresh().finally(() => {
            refreshInFlight = null;
          });
        }
        const newAccessToken = await refreshInFlight;
        config.headers.set("Authorization", `Bearer ${newAccessToken}`);
        return await api.request(config);
      } catch (refreshError) {
        useAuthStore.getState().clearSession();
        redirectToLogin();
        return Promise.reject(toApiError(refreshError));
      }
    }

    return Promise.reject(toApiError(error));
  },
);
