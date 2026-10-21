// @wbtime/logging · pino 封装。
//
// 关键约定：`mixin` 把 `request_id` 注入**每一条**日志。这样「request_id 在异步
// 调用链中贯通」不是口头承诺，而是每条日志可观测的事实 —— 测试只需断言
// 深层异步调用里打出的日志也带同一个 request_id。

import pino from "pino";
import type { DestinationStream, Logger, LoggerOptions } from "pino";

import { ERROR_HTTP_STATUS } from "@wbtime/core";
import type { ErrorCode } from "@wbtime/core";

import { getRequestId } from "./request-context.js";

export interface CreateLoggerOptions extends Omit<LoggerOptions, "mixin"> {
  /** 输出目标；缺省为 stdout（进程级默认，便于容器采集）。 */
  readonly destination?: DestinationStream;
}

export const DEFAULT_LOG_LEVEL = "info";

export function createLogger(options: CreateLoggerOptions = {}): Logger {
  const { destination, ...rest } = options;
  const base: LoggerOptions = {
    level: rest.level ?? DEFAULT_LOG_LEVEL,
    ...rest,
    // 每条日志都带上上下文中的 request_id；无上下文时**不写该字段**（键缺席 ≠ null）。
    mixin(): Record<string, unknown> {
      const requestId = getRequestId();
      return requestId === undefined ? {} : { request_id: requestId };
    },
  };
  return destination === undefined ? pino(base) : pino(base, destination);
}

/** 进程级默认 logger。测试与子进程应各自 createLogger，避免互相污染。 */
export const logger: Logger = createLogger();

/** 带固定绑定的子 logger（模块名 / 组件名等）。 */
export function childLogger(bindings: Record<string, unknown>, parent: Logger = logger): Logger {
  return parent.child(bindings);
}

/**
 * 错误落日志：带错误码与其 HTTP 状态（错误码 → 状态映射来自 contracts/errors.json）。
 * 这样排查时不必再翻码表。
 *
 * 关键约定：`Error` 实例整只放进 `err` 字段，**由 pino 默认的 `err` 序列化器**
 * 输出 `type` / `message` / `stack`。为什么不自己拼 `{ name, message }`：
 * 那样堆栈直接丢失，日志里只剩一句话，线上排查时无法定位抛出点 —— 而堆栈恰恰是
 * 错误日志唯一不可替代的信息。非 `Error` 抛出物（字符串 / 数字 / 普通对象）没有
 * `stack`，但同样不能只剩固定文案，故把原始值记进 `thrown` 与它的 `typeof`。
 */
export function logError(
  log: Logger,
  error: unknown,
  context: Record<string, unknown> = {},
): void {
  const code = extractErrorCode(error);
  const payload: Record<string, unknown> = { ...context };
  if (code !== undefined) {
    payload["error_code"] = code;
    payload["error_http_status"] = ERROR_HTTP_STATUS[code];
  }
  if (error instanceof Error) {
    log.error({ ...payload, err: error }, error.message);
    return;
  }
  log.error({ ...payload, thrown: String(error), thrown_type: typeof error }, "非 Error 实例被抛出");
}

function extractErrorCode(error: unknown): ErrorCode | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string") return undefined;
  return code in ERROR_HTTP_STATUS ? (code as ErrorCode) : undefined;
}
