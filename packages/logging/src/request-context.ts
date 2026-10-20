// @wbtime/logging · request_id 上下文。
//
// 这是本项目对旧 Python 线 `request_id` 语义的继承方式：旧线靠
// contextvars + middleware 把 request_id 注入到整条调用链；TS 线没有
// contextvars，等价物是 `AsyncLocalStorage` —— 只要请求入口处 `withRequestId`
// 包住 dispatch，后续任意深度的 `await` / Promise 链里 `getRequestId()` 都能取到
// 同一个值（包括未被 await 的分支，因为 ALS 沿**异步资源**传播，与 Promise 链无关）。
//
// 响应壳的 `request_id` 与响应头 `X-Request-Id` 同源（契约 §11.1），
// 因此这里必须是唯一取值入口，不允许各模块自己传参透传。

import { AsyncLocalStorage } from "node:async_hooks";

/** request_id 的存储载体。不导出实例本身，避免外部绕过封装直接 set。 */
const requestIdStore = new AsyncLocalStorage<string>();

/** 当前异步上下文中的 request_id；不在任何请求上下文内时为 undefined。 */
export function getRequestId(): string | undefined {
  return requestIdStore.getStore();
}

/** 强制取值：不在上下文内时抛错（用于「必须有 request_id」的落库 / 出帧路径）。 */
export function requireRequestId(): string {
  const requestId = requestIdStore.getStore();
  if (requestId === undefined) {
    throw new Error("requireRequestId: 当前异步上下文没有 request_id（未在 withRequestId 内调用）");
  }
  return requestId;
}

/**
 * 在给定的 request_id 上下文内执行 `fn`。
 *
 * 同步函数与返回 Promise 的函数都支持：返回值原样透出，`await` 语义由调用方决定。
 */
export function withRequestId<T>(requestId: string, fn: () => T): T {
  return requestIdStore.run(requestId, fn);
}

/** 是否处于某个 request_id 上下文中（便于测试与兜底分支判别）。 */
export function hasRequestId(): boolean {
  return requestIdStore.getStore() !== undefined;
}
