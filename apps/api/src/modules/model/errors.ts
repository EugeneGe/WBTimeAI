// @wbtime/api · Model 层错误归一化（T3-02）。
//
// 为什么错误码只有 `INTERNAL_ERROR` 一个（**不是失误**）：
//   契约 `contracts/errors.json` 共 30 码，**没有** `PROVIDER_*` / `RATE_LIMITED` /
//   `UPSTREAM_*`。自造码会直接破坏「错误码 ≡ 契约」门禁（B-1），且与 py 线不等价 ——
//   py 的 `ProviderError` 同样把所有厂商错误归到 `INTERNAL_ERROR`，靠 `data` 里的
//   `retryable` / `http_status` 区分（`_old/.../providers/base.py:43-60`）。
//   ⇒ 本文件照抄该口径：**码固定，类型放 `errorType`**。
//
// 四类（任务卡 T3-02 验收 ①）：
//   `rate_limited`（429）· `provider_5xx`（500/502/503/504）· `timeout` · `invalid_request`（其余 4xx）
//   **`invalid_request` 恒不重试**（重试一个参数错误只会重复失败并放大计费）。

/** Provider 错误类型（四类）。 */
export const PROVIDER_ERROR_TYPES = [
  "rate_limited",
  "provider_5xx",
  "timeout",
  "invalid_request",
] as const;

export type ProviderErrorType = (typeof PROVIDER_ERROR_TYPES)[number];

/** 可重试的三类（`invalid_request` 不在其中）。 */
const RETRYABLE_TYPES: ReadonlySet<ProviderErrorType> = new Set<ProviderErrorType>([
  "rate_limited",
  "provider_5xx",
  "timeout",
]);

/** 契约错误码（固定值；理由见文件头）。 */
export const PROVIDER_ERROR_CODE = "INTERNAL_ERROR" as const;

export interface ProviderErrorInit {
  readonly errorType: ProviderErrorType;
  readonly provider?: string;
  readonly model?: string;
  readonly httpStatus?: number | null;
  readonly retryable?: boolean;
  readonly cause?: unknown;
  readonly data?: Readonly<Record<string, unknown>>;
}

/**
 * Provider 层错误。
 *
 * `retryable` 默认由 `errorType` 决定，但**允许显式覆盖**（例如上游给了 `Retry-After`
 * 的长等待，可主动降级为不重试）；`invalid_request` 即使显式传 `true` 也会被压回 `false`。
 */
export class ProviderError extends Error {
  readonly code = PROVIDER_ERROR_CODE;
  readonly errorType: ProviderErrorType;
  readonly retryable: boolean;
  readonly provider: string | null;
  readonly model: string | null;
  readonly httpStatus: number | null;
  readonly data: Readonly<Record<string, unknown>>;

  constructor(message: string, init: ProviderErrorInit) {
    super(message, init.cause === undefined ? undefined : { cause: init.cause });
    this.name = "ProviderError";
    this.errorType = init.errorType;
    this.retryable = init.errorType === "invalid_request" ? false : (init.retryable ?? RETRYABLE_TYPES.has(init.errorType));
    this.provider = init.provider ?? null;
    this.model = init.model ?? null;
    this.httpStatus = init.httpStatus ?? null;
    this.data = Object.freeze({
      error_type: this.errorType,
      retryable: this.retryable,
      http_status: this.httpStatus,
      provider: this.provider,
      model: this.model,
      ...init.data,
    });
  }

  /** 落到 `audit_log.metadata` / 日志用的扁平结构（不含 message，避免泄内容）。 */
  toData(): Record<string, unknown> {
    return { ...this.data };
  }
}

/** 某个 `errorType` 是否默认可重试。 */
export function isRetryableProviderErrorType(errorType: ProviderErrorType): boolean {
  return RETRYABLE_TYPES.has(errorType);
}

/**
 * HTTP 状态码 → 错误类型。
 *
 * 分类规则只看数量级：`429` → 限流；`>=500` → 上游故障；`4xx`（含 418 这类罕见码）
 * → 调用方错误（**不重试**）。**没有 HTTP 状态**的异常（网络中断 / 未知抛出）才落到
 * `provider_5xx`（见 `toProviderError`）—— 那才是"宁可多试一次"的场景。
 */
export function classifyHttpStatus(status: number): ProviderErrorType {
  if (status === 429) return "rate_limited";
  if (status >= 500) return "provider_5xx";
  if (status >= 400) return "invalid_request";
  return "provider_5xx";
}

/** Node/undici 的超时与取消类错误名（不依赖具体类，避免跨版本 import）。 */
const TIMEOUT_ERROR_NAMES: ReadonlySet<string> = new Set([
  "AbortError",
  "TimeoutError",
  "HeadersTimeoutError",
  "BodyTimeoutError",
  "ConnectTimeoutError",
]);

interface HttpLikeError {
  readonly status?: unknown;
  readonly statusCode?: unknown;
  readonly response?: { readonly status?: unknown };
}

/**
 * 把任意抛出物归一为 {@link ProviderError}。
 *
 * 已经是 `ProviderError` 的原样返回（保留原始 `errorType`，不二次归类）。
 */
export function toProviderError(
  error: unknown,
  defaults: { readonly provider?: string; readonly model?: string } = {},
): ProviderError {
  if (error instanceof ProviderError) return error;

  const candidate = error as HttpLikeError | null;
  const status =
    typeof candidate?.status === "number"
      ? candidate.status
      : typeof candidate?.statusCode === "number"
        ? candidate.statusCode
        : typeof candidate?.response?.status === "number"
          ? candidate.response.status
          : null;

  const name = error instanceof Error ? error.name : "";
  const isTimeout =
    TIMEOUT_ERROR_NAMES.has(name) ||
    (error instanceof Error && /timeout|timed out/i.test(error.message));

  const errorType: ProviderErrorType =
    status !== null ? classifyHttpStatus(status) : isTimeout ? "timeout" : "provider_5xx";

  return new ProviderError(error instanceof Error ? error.message : String(error), {
    errorType,
    provider: defaults.provider,
    model: defaults.model,
    httpStatus: status,
    cause: error,
  });
}
