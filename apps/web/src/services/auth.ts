import { api } from "@/lib/api";
import type {
  DeviceResponse,
  LoginRequest,
  MessageResponse,
  RegisterRequest,
  TokenResponse,
  UpdateUserRequest,
  UserResponse,
} from "@/types";

/**
 * 认证 / 本人信息服务（仅经 `/api/v1`，见 §2T.0.1 契约映射表）。
 *
 * ⚠️ components / pages **不**直接调用 axios，统一经此服务层。
 */
export const authService = {
  /** 注册（成功即自动登录，返回令牌组）。 */
  register(payload: RegisterRequest): Promise<TokenResponse> {
    return api.post<TokenResponse>("/auth/register", payload).then((r) => r.data);
  },
  /** 登录（连续失败 → HTTP 423）。 */
  login(payload: LoginRequest): Promise<TokenResponse> {
    return api.post<TokenResponse>("/auth/login", payload).then((r) => r.data);
  },
  /** 登出（撤销当前会话）。 */
  logout(): Promise<MessageResponse> {
    return api.post<MessageResponse>("/auth/logout").then((r) => r.data);
  },
  /** 刷新令牌（旧 refresh 撤销后 → 401）。 */
  refresh(refreshToken: string): Promise<TokenResponse> {
    return api
      .post<TokenResponse>("/auth/refresh", { refresh_token: refreshToken })
      .then((r) => r.data);
  },
  /** 读取本人信息。 */
  me(): Promise<UserResponse> {
    return api.get<UserResponse>("/users/me").then((r) => r.data);
  },
  /** 更新本人信息（Phase 0 仅 `display_name`）。 */
  updateMe(payload: UpdateUserRequest): Promise<UserResponse> {
    return api.put<UserResponse>("/users/me", payload).then((r) => r.data);
  },
  /** 本人设备会话列表。 */
  devices(): Promise<DeviceResponse[]> {
    return api.get<DeviceResponse[]>("/users/me/devices").then((r) => r.data);
  },
  /** 退出全部（撤销当前用户全部会话）。 */
  logoutAll(): Promise<MessageResponse> {
    return api.post<MessageResponse>("/users/me/logout-all").then((r) => r.data);
  },
};
