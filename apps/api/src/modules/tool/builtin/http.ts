/**
 * T3-10 · `http` 工具（出网默认**拒绝全部**，需显式白名单）。
 *
 * 三个必须说明的取舍
 * ----------------
 *   1. **默认拒绝**：`egressAllowlist` 为空 ⇒ 任何 URL 都拒。这是 py 的口径
 *      （`host_matches(host, []) === False`）。"默认放行内网之外"看起来更友好，
 *      但它把"谁能出网"这个决定交给了攻击者（用一个可控域名解析到外网即可）。
 *   2. **校验在请求之前**（反例「先执行后检查」）：`checkEgress` 先跑，通过才 `fetch`。
 *   3. **钉定 IP 未落地**：`checkEgress` 返回了首解析 IP，但本版 `fetch` 仍按域名连接
 *      —— 校验与连接之间有一个 DNS 窗口（`checkEgress` 的二次解析把窗口压到最小，
 *      但没消除）。真正的钉定需要自定义 `undici` dispatcher（按 IP 连接 + `Host` 头），
 *      属 V0.4.0 的出网治理波。**已登记为遗留**，不在这里假装做到了。
 *
 * 响应体上限
 * --------
 *   与 `filesystem` 的 8MB 一致：超过就截断并标 `truncated`（不让一次大响应把内存打爆）。
 */

import { checkEgress, EgressDeniedError } from "../guards/ssrf.js";
import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";

/** 响应体上限（字符）。 */
export const MAX_HTTP_BODY_CHARS = 8 * 1024 * 1024;

/** 缺省超时（毫秒）。 */
export const DEFAULT_HTTP_TIMEOUT_MS = 15_000;

/** 只允许这几种方法（`GET` 缺省）。 */
const ALLOWED_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]);

export const httpTool: BuiltinTool = {
  name: "http",
  requiresSandbox: false,

  async execute(args: Readonly<Record<string, unknown>>, context: ToolContext): Promise<ToolOutcome> {
    const startedAt = Date.now();
    const url = typeof args.url === "string" ? args.url : "";
    if (url === "") {
      return {
        ok: false,
        error: "url 必须是非空字符串",
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    const method = (args.method === undefined ? "GET" : String(args.method)).toUpperCase();
    if (!ALLOWED_METHODS.has(method)) {
      return {
        ok: false,
        error: `不支持的方法 ${JSON.stringify(args.method)}`,
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    // 闸 1：出网（**先于一切网络动作**）
    let pinnedIp: string;
    try {
      pinnedIp = await checkEgress(url, {
        ...(context.egressAllowlist === undefined ? {} : { allowlist: context.egressAllowlist }),
        ...(context.resolver === undefined ? {} : { resolver: context.resolver }),
      });
    } catch (error) {
      if (error instanceof EgressDeniedError) {
        return {
          ok: false,
          error: error.message,
          errorCode: "PERMISSION_DENIED",
          durationMs: Date.now() - startedAt,
        };
      }
      throw error;
    }

    // 闸 2：真实请求（超时用 `AbortSignal.timeout`，与运行时的取消解耦）
    const timeoutMs =
      typeof args.timeout_ms === "number" ? args.timeout_ms : DEFAULT_HTTP_TIMEOUT_MS;
    const headers = isPlainObject(args.headers) ? (args.headers as Record<string, string>) : {};

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        ...(typeof args.body === "string" && method !== "GET" && method !== "HEAD"
          ? { body: args.body }
          : {}),
        signal: AbortSignal.timeout(timeoutMs),
        redirect: "manual", // 不自动跟随：跟随会把"已校验的 URL"换成"未校验的 URL"
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const isTimeout = message.includes("aborted") || message.includes("timeout");
      return {
        ok: false,
        error: isTimeout ? "HTTP 请求超时" : `HTTP 请求失败：${message}`,
        errorCode: isTimeout ? "TOOL_TIMEOUT" : "INTERNAL_ERROR",
        durationMs: Date.now() - startedAt,
        ...(isTimeout ? { timedOut: true } : {}),
      };
    }

    // 3xx：不跟随，但明确回报（调用方据此决定要不要再发一次）
    if (response.status >= 300 && response.status < 400) {
      return {
        ok: true,
        output: {
          status: response.status,
          location: response.headers.get("location"),
          pinned_ip: pinnedIp,
          redirect_not_followed: true,
        },
        durationMs: Date.now() - startedAt,
      };
    }

    let body: string;
    try {
      body = await response.text();
    } catch (error) {
      return {
        ok: false,
        error: `读取响应体失败：${error instanceof Error ? error.message : String(error)}`,
        errorCode: "INTERNAL_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }
    const truncated = body.length > MAX_HTTP_BODY_CHARS;
    if (truncated) body = body.slice(0, MAX_HTTP_BODY_CHARS);

    const ok = response.status >= 200 && response.status < 300;
    return {
      ok,
      ...(ok
        ? {
            output: {
              status: response.status,
              headers: Object.fromEntries(response.headers.entries()),
              body,
              truncated,
              pinned_ip: pinnedIp,
            },
          }
        : { error: `HTTP ${response.status}`, errorCode: "INTERNAL_ERROR" }),
      durationMs: Date.now() - startedAt,
    };
  },
};

/** 简单对象判定（排除数组 / null）。 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
