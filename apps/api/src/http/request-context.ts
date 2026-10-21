// apps/api · request_id 上下文（AsyncLocalStorage 贯通）。
//
// 契约事实（`contracts/envelope.schema.json` → `x-wbtimeai.field_invariance.request_id`）：
// `request_id` **键恒在**、值可 `null`，且 **== 响应头 `X-Request-Id`**（「体 == 头」，
// 旧仓实测 4/4 探针）。因此本文件是**唯一取值入口**，绝不允许各模块自己传参透传，
// 否则「体 == 头」早晚会在某条分支上失守。
//
// 载体复用 `@wbtime/logging` 的 `AsyncLocalStorage`（同一个 store 实例）：pino 的
// `mixin` 也从那里读 request_id，若这里另起一个 ALS，日志里的 request_id 与响应体里
// 的就会是两条独立链路 —— 那种「看着都有 request_id 但其实不是一个」的状态最难查。
//
// 取值优先级（契约 `middleware_stack.note`）：**先**请求头 `X-Request-Id`（上游网关 /
// 客户端已带），**缺失才**生成。生成的 id 用于填充响应头与响应体两处。

import { randomUUID } from "node:crypto";

import { getRequestId, withRequestId } from "@wbtime/logging";
import type { FastifyInstance, FastifyRequest } from "fastify";

declare module "fastify" {
  interface FastifyRequest {
    /** 本次请求的 request_id（与响应头 `X-Request-Id`、响应体 `request_id` 同源）。 */
    requestId: string;
  }
}

/** 响应头名（小写：Node 的 http 头在入站侧一律小写）。 */
export const REQUEST_ID_HEADER = "x-request-id";

/**
 * 缺失请求头时的 id 生成器。
 *
 * **已知偏差（已登记，不静默假称 v7）**：契约注释写的是 UUIDv7（RFC 9562），但
 * Node v22.22.2 没有内置 v7 生成器（只有 `crypto.randomUUID()`，即 v4）。本版按
 * 施工口径先返回 **UUIDv4**，并把偏差写进 `02-施工/施工记录/T2-02.md`；**不得**
 * 在注释或文档里把它说成 v7（版本号可实测：第 13 位 16 进制是 `4`，v7 应为 `7`）。
 *
 * @returns RFC 4122 v4 形态的 36 字符 id。
 */
export function generateRequestId(): string {
  return randomUUID();
}

/**
 * 从入站请求头里取 request_id。
 *
 * 只接受**非空字符串**：`X-Request-Id` 重复出现时 Node 会给出数组，数组一律视为
 * 「未提供」（不猜哪一个是真的）；空白串同样视为未提供。
 *
 * @param raw `request.headers[REQUEST_ID_HEADER]` 的原始值。
 * @returns 归一化（trim 后）的 id，或 `null`（未提供）。
 */
export function readRequestIdHeader(raw: string | string[] | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * 决定本次请求的 request_id：优先请求头，缺失才生成。
 *
 * @param raw 入站请求头原始值。
 * @returns 非空 request_id。
 */
export function resolveRequestId(raw: string | string[] | undefined): string {
  return readRequestIdHeader(raw) ?? generateRequestId();
}

/** 当前异步上下文里的 request_id；不在请求上下文内时为 `undefined`。 */
export function currentRequestId(): string | undefined {
  return getRequestId();
}

/**
 * 在给定 request_id 的异步上下文内执行 `fn`（直接委托 `@wbtime/logging`，
 * 目的是让「上下文载体只有一份」这件事在代码里只有一个入口）。
 */
export function runInRequestContext<T>(requestId: string, fn: () => T): T {
  return withRequestId(requestId, fn);
}

/** `genReqId` 实现：把 request_id 直接做成 Fastify 的 `request.id`。 */
export function genReqId(request: Pick<FastifyRequest, "headers">): string {
  return resolveRequestId(request.headers[REQUEST_ID_HEADER]);
}

/**
 * 装配 request_id 上下文：`genReqId` + `onRequest` 钩子。
 *
 * 两件事缺一不可：
 *  1. `genReqId` 让 `request.id` 就是 request_id（Fastify 内部日志 / 错误对象也带上它）；
 *  2. `onRequest` 里 `runInRequestContext(...)` 包住 `done()` —— 后续 hook 与 handler
 *     的异步续体是在该 store 内创建的，因此任意深度的 `await` 都能 `currentRequestId()`。
 *
 * 响应头在这里就写好（`X-Request-Id`），响应壳中间件再从这个头 + 上下文取同一个值，
 * 「体 == 头」由此结构性成立，而不是靠两处各自生成再祈祷相等。
 *
 * @param app Fastify 实例（需在注册路由前调用）。
 */
export function attachRequestContext(app: FastifyInstance): void {
  app.decorateRequest("requestId", "");

  app.addHook("onRequest", (request, reply, done) => {
    const requestId =
      typeof request.id === "string" && request.id !== ""
        ? request.id
        : resolveRequestId(request.headers[REQUEST_ID_HEADER]);

    request.requestId = requestId;
    reply.header(REQUEST_ID_HEADER, requestId);

    // `done()` 在 store 内同步触发，后续生命周期（含 handler 的异步续体）都在该
    // store 内派生，因此深层 await 后仍能取到同一个 request_id。
    runInRequestContext(requestId, () => {
      done();
    });
  });
}
