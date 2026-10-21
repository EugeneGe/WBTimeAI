// apps/api · 响应壳中间件（成功 JSON 套壳 + 「已是壳」幂等）。
//
// 契约口径（`contracts/envelope.schema.json` → `x-wbtimeai.enforcement.success_wrap.trigger`）：
//
//     status < 400 且 content-type 含 application/json 且 path ∉ ['/openapi.json']
//     且 body 非空 且 非「已是成功壳」
//
// 六类**不套壳**必须显式排除（`not_wrapped.cases`，一条不落）：
//   failure(>=400) / sse(text/event-stream) / non_json / framework_path(/openapi.json)
//   / already_shell(值判定) / empty_body(body == b"")
//
// 分工：**失败壳的唯一出口是 `./error-handler.ts`**。本中间件对 `status >= 400`
// 提前 return（契约 `error_shell.bypasses_middleware`），因此「失败响应被二次包裹」
// 在结构上不可能发生 —— 不是靠判断「看起来像壳」来兜。
//
// 为什么挂在 `onSend` 而不是 `preSerialization`：契约的 `empty_body` 条件是
// `body == b""`，这是**已序列化响应体**层面的表述；`preSerialization` 对 string /
// Buffer / 空体根本不会被调用，用它等于把 3 类排除条件实现成「反正进不来」，
// 测不出「进来后被排除」。`onSend` 能看到全部形态，六条排除逐条可断言。

import { isSuccessShell, okResponse } from "@wbtime/core";
import type { OkResponse } from "@wbtime/core";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { REQUEST_ID_HEADER, currentRequestId } from "./request-context.js";

/** 成功壳的 `code`（契约 `successEnvelope.properties.code.const`）。 */
export const SUCCESS_CODE = 0;

/** 成功壳的 `message`（契约 `successEnvelope.properties.message.const`）。 */
export const SUCCESS_MESSAGE = "ok";

/** 框架文档路径：供 Swagger / Redoc 消费，不得套壳（契约 `not_wrapped.framework_path`）。 */
export const FRAMEWORK_PATHS: readonly string[] = Object.freeze(["/openapi.json"]);

/** JSON 响应的 content-type 判定子串。 */
export const JSON_CONTENT_TYPE = "application/json";

/** SSE 响应的 content-type 判定子串。 */
export const SSE_CONTENT_TYPE = "text/event-stream";

/**
 * 不套壳的六类原因（与契约 `not_wrapped.cases` 的 `case` 字段逐项同名）。
 *
 * 共 6 项，禁止合并成「其它」：合并会让「某条排除规则失效」在测试里不可见。
 */
export type WrapSkipReason =
  | "failure"
  | "sse"
  | "non_json"
  | "framework_path"
  | "already_shell"
  | "empty_body";

/** 套壳决策：要么套，要么给出**唯一**排除原因。 */
export type WrapDecision =
  | { readonly wrap: true }
  | { readonly wrap: false; readonly reason: WrapSkipReason };

/** `decideWrap` 的输入（全部为纯值，便于单测逐条构造，不需要起 HTTP 服务）。 */
export interface WrapInput {
  /** 响应状态码（`reply.statusCode`）。 */
  readonly status: number;
  /** 响应头 `content-type` 的字符串形态（缺失传 `null`）。 */
  readonly contentType: string | null;
  /** 请求路径（已去掉 query / hash）。 */
  readonly path: string;
  /** 响应体是否为空（`null` / `undefined` / `""` / 零长 Buffer）。 */
  readonly bodyIsEmpty: boolean;
  /** `JSON.parse` 后的响应体（`bodyIsEmpty` 为真时传 `undefined`）。 */
  readonly body: unknown;
}

/**
 * 纯函数判定：这次响应要不要套壳。
 *
 * 判定顺序与「语义优先级」一致，理由逐条写在下面（顺序本身是判据的一部分：
 * `empty_body` 必须早于 `non_json`，因为 204 根本没有 content-type，否则 204 会
 * 被误报成 `non_json`，测试就无法证明「空体规则真的生效」）。
 *
 * @param input 见 {@link WrapInput}。
 * @returns `{wrap:true}` 或 `{wrap:false, reason}`。
 */
export function decideWrap(input: WrapInput): WrapDecision {
  // ① failure：失败壳已由 error-handler 直出，二次包裹会把四键壳塞进 data。
  if (input.status >= 400) return { wrap: false, reason: "failure" };

  // ② sse：text/event-stream 帧契约归 contracts/sse/channels.json，套壳即毁帧。
  if (isSseContentType(input.contentType)) return { wrap: false, reason: "sse" };

  // ③ empty_body：204 等空体只保留状态码与响应头（契约条件原文 body == b""）。
  if (input.bodyIsEmpty) return { wrap: false, reason: "empty_body" };

  // ④ non_json：例如 /metrics 的 text/plain。
  if (!isJsonContentType(input.contentType)) return { wrap: false, reason: "non_json" };

  // ⑤ framework_path：/openapi.json 供 Swagger / Redoc 消费。
  if (FRAMEWORK_PATHS.includes(input.path)) return { wrap: false, reason: "framework_path" };

  // ⑥ already_shell：**值判定**（code===0 && message==="ok" && hasOwn data/request_id）。
  //    键判定会把 {code:"NOT_FOUND",…} 误当成功壳并二次包裹 —— 这正是要避免的。
  if (isSuccessShell(input.body)) return { wrap: false, reason: "already_shell" };

  return { wrap: true };
}

/**
 * 构造成功壳（四顶层键，顺序与契约一致）。
 *
 * 刻意复用 `@wbtime/core` 的 `okResponse()` 而不是本文件手写对象字面量：壳的形状
 * 只有一处定义，字段一改两边一起改，不会出现「中间件拼的壳」与「测试断言的壳」
 * 各自演化。
 *
 * @param body 裸业务对象（原样放进 `data`，**不加**二级 `{data:…}` 外壳）。
 * @param requestId 与响应头 `X-Request-Id` 同源的值；允许 `null`（键恒在）。
 */
export function wrapSuccess(body: unknown, requestId: string | null): OkResponse<unknown> {
  return okResponse(body, requestId);
}

/**
 * 把 `content-type` 响应头归一化成字符串（缺失 → `null`）。
 *
 * @param raw `reply.getHeader("content-type")` 的原始值。
 */
export function headerToString(raw: string | number | string[] | undefined): string | null {
  if (typeof raw === "string") return raw;
  if (typeof raw === "number") return String(raw);
  if (Array.isArray(raw)) return raw.length > 0 ? raw.join(", ") : null;
  return null;
}

/** content-type 是否声明了 JSON（大小写不敏感，允许带 charset）。 */
export function isJsonContentType(contentType: string | null): boolean {
  return contentType !== null && contentType.toLowerCase().includes(JSON_CONTENT_TYPE);
}

/** content-type 是否声明了 SSE。 */
export function isSseContentType(contentType: string | null): boolean {
  return contentType !== null && contentType.toLowerCase().includes(SSE_CONTENT_TYPE);
}

/**
 * 去掉 query / hash，只留路径。
 *
 * @param url `request.url`（可能带 `?a=1#b`）。
 */
export function pathOf(url: string): string {
  const cut = url.search(/[?#]/);
  return cut === -1 ? url : url.slice(0, cut);
}

/** 响应体是否为空（`null` / `undefined` / `""` / 零长 Buffer）。 */
export function isEmptyPayload(payload: unknown): boolean {
  if (payload === null || payload === undefined) return true;
  if (typeof payload === "string") return payload.length === 0;
  if (Buffer.isBuffer(payload)) return payload.byteLength === 0;
  return false;
}

/**
 * 把 string / Buffer 响应体转成文本；其它形态（stream 等）返回 `null`。
 *
 * @param payload `onSend` 钩子拿到的响应体。
 */
export function payloadToText(payload: unknown): string | null {
  if (typeof payload === "string") return payload;
  if (Buffer.isBuffer(payload)) return payload.toString("utf8");
  return null;
}

/**
 * 单次响应的套壳执行体（从 hook 里拆出来，便于单独调用与复用测试）。
 *
 * @param request Fastify 请求（取 path / log）。
 * @param reply Fastify 响应（取 status / content-type / `X-Request-Id`）。
 * @param payload `onSend` 拿到的响应体。
 * @returns 新的响应体（未套壳时原样返回，**不做** JSON 往返以免字节漂移）。
 */
function applyEnvelope(request: FastifyRequest, reply: FastifyReply, payload: unknown): unknown {
  const status = reply.statusCode;
  const contentType = headerToString(reply.getHeader("content-type"));
  const path = pathOf(request.url);
  const bodyIsEmpty = isEmptyPayload(payload);

  let body: unknown;
  if (!bodyIsEmpty && isJsonContentType(contentType)) {
    const text = payloadToText(payload);
    if (text === null) {
      // 声称 JSON 但响应体不是 string/Buffer（如 stream）：无法安全判定，原样放行。
      return payload;
    }
    try {
      body = JSON.parse(text);
    } catch {
      // 声称 JSON 却解析不了 = 上游序列化出了问题。此时**绝不**猜内容再包一层
      // （那会把坏数据伪装成好数据），放行并留日志，让问题暴露在响应体里。
      request.log.warn(
        { path, status, raw_length: text.length },
        "响应声明 application/json 但无法解析，跳过套壳",
      );
      return payload;
    }
  }

  const decision = decideWrap({ status, contentType, path, bodyIsEmpty, body });
  if (!decision.wrap) return payload;

  const requestId =
    currentRequestId() ?? headerToString(reply.getHeader(REQUEST_ID_HEADER)) ?? null;
  return JSON.stringify(wrapSuccess(body, requestId));
}

/**
 * 装配响应壳中间件。
 *
 * 必须在**路由注册之前**调用（Fastify 的 hook 对之后注册的路由同样生效，但前置
 * 可避免「有的路由先注册了却没被包」这种一眼看不出的顺序坑）。
 *
 * @param app Fastify 实例。
 */
export function registerEnvelope(app: FastifyInstance): void {
  app.addHook("onSend", (request, reply, payload, done) => {
    // 失败壳的唯一出口是 error-handler：这里提前 return，语义与
    // `ResponseShellMiddleware.dispatch` 的 `status_code >= 400 → return response` 一致。
    if (reply.statusCode >= 400) {
      done(null, payload);
      return;
    }

    const wrapped = applyEnvelope(request, reply, payload);
    // Fastify 的 onSend 载荷类型按默认序列化器写成 string；运行期还可能是 Buffer /
    // stream（已被 applyEnvelope 原样放行），故此处按 unknown → 载荷类型收窄。
    done(null, wrapped as typeof payload);
  });
}
