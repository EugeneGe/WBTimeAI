/**
 * 令牌存储（D6 · Token 策略，定稿）。
 *
 * - **access token**：**仅内存**（模块级变量，**不落 localStorage**，随页面刷新丢失）；
 * - **refresh token**：**localStorage**（可撤销，服务端为权威）。
 *
 * ⚠️ 本模块**不含**任何后端 `mode` 判断（前端一律经 `/api/v1` 对接）。
 */

const REFRESH_TOKEN_KEY = "astra.refresh_token";

let accessToken: string | null = null;

/** 读取内存中的 access token。 */
export function getAccessToken(): string | null {
  return accessToken;
}

/** 写入 / 清空内存中的 access token。 */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** 读取 localStorage 中的 refresh token（异常环境返回 `null`）。 */
export function getRefreshToken(): string | null {
  try {
    return window.localStorage.getItem(REFRESH_TOKEN_KEY);
  } catch {
    return null;
  }
}

/** 写入 / 清空 localStorage 中的 refresh token。 */
export function setRefreshToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(REFRESH_TOKEN_KEY, token);
    } else {
      window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
  } catch {
    // 忽略隐私模式 / 存储不可用等异常。
  }
}

/** 同时清空 access（内存）与 refresh（localStorage）。 */
export function clearTokens(): void {
  accessToken = null;
  setRefreshToken(null);
}

/** 是否存在可用会话（内存 access 或 localStorage refresh 任一存在）。 */
export function hasStoredSession(): boolean {
  return Boolean(accessToken ?? getRefreshToken());
}
