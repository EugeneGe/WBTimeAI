// apps/api · 失败壳的**唯一**出口。
//
// 契约依据（`contracts/envelope.schema.json` → `x-wbtimeai.enforcement.error_shell`）：
// 失败壳由异常处理器**直接产出**，`status >= 400` 时响应壳中间件提前 return
// （`bypasses_middleware`）—— 因此「失败响应被包两层」在结构上不可能。
//
// 四条 `produced_by` 逐条落地（顺序与契约一致）：
//   ① DomainError 及其子类        → status = 显式 status（若有）否则 `ERROR_HTTP_STATUS` 查表
//   ② 校验错误                    → 恒 422，`data = {errors: [...]}`
//   ③ HTTPException（框架层 404/405 等）→ 原样保留实际状态码
//   ④ 未捕获的 Exception          → 恒 500
//
// 唯一一处「顺序偏离」：`HttpException`（③）的实现类检查被提到 ① 之前。原因很具体 —
// 本项目 ③ 的实现类**带 `code` 属性**，若不先认它，duck-typing 的 ① 会把它当成域错误
// 并改走状态表，`405` 就会被状态表里的 `METHOD_NOT_ALLOWED` 覆盖成同值（表面无差别）
// 但 `HttpException(404, NOT_FOUND)` 一旦带上别的码就会错。先认类、再认形状，行为可预测。

import { ERROR_CODES, ERROR_DESCRIPTIONS, errorResponse } from "@wbtime/core";
import type { ErrorCode, ErrorResponse } from "@wbtime/core";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { headerToString, pathOf } from "./envelope.js";
import { REQUEST_ID_HEADER, currentRequestId } from "./request-context.js";
import { frameworkCodeForHttpStatus, httpStatusOf, isErrorCode } from "./status-map.js";

/** 失败壳的四条产出源（与契约 `error_shell.produced_by` 的四项一一对应）。 */
export type ErrorOrigin = "domain_error" | "validation" | "http_exception" | "unhandled";

/** 一次失败的完整判定结果：状态 + 四键壳 + 产出源（产出源用于日志与测试归因）。 */
export interface ErrorOutcome {
  readonly status: number;
  readonly body: ErrorResponse;
  readonly origin: ErrorOrigin;
}

/**
 * 契约 ③ 的实现类：框架层 / 应用层显式 HTTP 错误。
 *
 * 带上 `code` 而不是只带状态码，是为了让 405、415 这类出口也能落到契约的 30 个码之内
 * （契约里没有「415」对应的码，那种情况请用 `frameworkCodeForHttpStatus()` 的回落规则，
 * 或显式传 `ERROR_CODES.UNKNOWN`）。
 */
export class HttpException extends Error {
  /** 实际 HTTP 状态码（原样保留，不被状态表改写）。 */
  readonly statusCode: number;
  /** 契约错误码。 */
  readonly code: ErrorCode;
  /** 附加上下文（缺省 `{}`）。 */
  readonly data: Readonly<Record<string, unknown>>;

  constructor(
    statusCode: number,
    code: ErrorCode,
    message: string,
    data: Record<string, unknown> = {},
  ) {
    super(message);
    // 状态码必须落在 400..599：`HttpException` 是**错误**载体，若允许 2xx，它会被
    // 响应壳中间件当成成功响应套壳，等于把「失败」渲染成 `{code:0, message:"ok"}`
    // —— 这类错误一旦上线，前端只会看到「成功但没有数据」。故在构造期就挡住。
    if (!Number.isInteger(statusCode) || statusCode < 400 || statusCode > 599) {
      throw new RangeError(
        `HttpException: statusCode 必须是 400..599 的整数，收到 ${String(statusCode)}`,
      );
    }
    this.name = "HttpException";
    this.statusCode = statusCode;
    this.code = code;
    this.data = Object.freeze({ ...data });
  }
}

/**
 * 契约 ① 的鸭子类型判定结果。
 *
 * 为什么不用 `instanceof DomainError`：域错误的**契约约束对象是「码值」**，不是某个
 * 类。`@wbtime/domain` 的 `DomainError` 目前只收 2 个码（VALIDATION / CONFIGURATION），
 * 而身份 4 族需要 NOT_FOUND / PERMISSION_DENIED / UNAUTHORIZED 等；用 `instanceof`
 * 会把这类错误一律甩进 ④（恒 500），把 404 变成 500 —— 那是最难在联调时发现的错误。
 */
export interface DomainErrorShape {
  readonly code: ErrorCode;
  readonly message: string;
  readonly data: Readonly<Record<string, unknown>>;
  /** call-site 显式状态（`dependencyMissing()` 带它；普通域错误没有）。 */
  readonly status?: number;
}

/**
 * 把「形状像域错误」的值收窄成 {@link DomainErrorShape}。
 *
 * 判定条件（三条同时成立）：
 *  1. 是对象且非 `null`；
 *  2. `code` 是契约 30 个码之一（Fastify 的 `FST_ERR_*` 与 Node 的 `ENOENT` 因此天然落选）；
 *  3. `message` 是字符串。
 *
 * @param value 被抛出的值。
 * @returns 收窄后的域错误形状，或 `null`。
 */
export function asDomainError(value: unknown): DomainErrorShape | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as {
    code?: unknown;
    message?: unknown;
    data?: unknown;
    status?: unknown;
  };
  if (!isErrorCode(candidate.code)) return null;
  if (typeof candidate.message !== "string") return null;

  const data =
    typeof candidate.data === "object" && candidate.data !== null && !Array.isArray(candidate.data)
      ? (candidate.data as Record<string, unknown>)
      : {};
  const status = typeof candidate.status === "number" ? candidate.status : undefined;

  return { code: candidate.code, message: candidate.message, data, status };
}

/**
 * 取 Fastify **框架层**错误的实际状态码（只认 `FST_*` 码，见 ④ 不会被误判的原因）。
 *
 * @param error 被抛出的值。
 * @returns 400..599 的整数状态，或 `null`（不是框架层 HTTP 错误）。
 */
export function asFrameworkHttpStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const candidate = error as { statusCode?: unknown; code?: unknown };
  const status = candidate.statusCode;
  if (typeof status !== "number" || !Number.isInteger(status) || status < 400 || status > 599) {
    return null;
  }
  if (typeof candidate.code !== "string" || !candidate.code.startsWith("FST_")) return null;
  return status;
}

/**
 * 取域错误的最终 HTTP 状态。
 *
 * **显式优先**：错误对象自带合法 `status` 时直接采纳；否则查生成表。
 * 这条优先级是 `DEPENDENCY_MISSING` 参数化能成立的前提 —— 若反过来（表优先），
 * `dependencyMissing(capability, 500)` 会被表里的 503 覆盖，「按 call-site 取值」
 * 就退化成「全局兜底」，K-6 的核心断言随即失效。
 *
 * @param error 域错误形状。
 * @returns 400..599 的状态码。
 */
export function resolveDomainErrorStatus(error: DomainErrorShape): number {
  const declared = error.status;
  if (
    typeof declared === "number" &&
    Number.isInteger(declared) &&
    declared >= 400 &&
    declared <= 599
  ) {
    return declared;
  }
  return httpStatusOf(error.code);
}

/** 未捕获错误的对外文案：不泄露内部细节（堆栈 / SQL / 路径一律不进响应体）。 */
export const UNHANDLED_MESSAGE = "内部服务器错误";

/**
 * 把任意被抛出的值翻译成四键失败壳（纯函数，便于单测逐条构造）。
 *
 * @param error 被抛出的值（任意）。
 * @param requestId 与响应头同源的 request_id；允许 `null`（键恒在）。
 * @returns 状态 + 四键壳 + 产出源。
 */
export function toErrorOutcome(error: unknown, requestId: string | null): ErrorOutcome {
  // ③ 先认实现类（理由见文件头注释）。
  if (error instanceof HttpException) {
    return {
      status: error.statusCode,
      origin: "http_exception",
      body: errorResponse(error.code, error.message, { ...error.data }, requestId),
    };
  }

  // ① DomainError 及其子类（鸭子类型：码值来自契约即可）。
  //
  // ⚠️ **不变量（改动前请读完这条）**：鸭子类型意味着「凡是带契约码的对象都会被当域错误」。
  // 因此 `@wbtime/db` 的 `ScopeError`（编程错误：裸 id / 跨 scope ref / 非法 limit /
  // 非白名单表 unscoped）**刻意没有 `code` 字段**，只带 `name` + `message` ——
  // 实测它的定义为 `constructor(message) { super(message); this.name = "ScopeError" }`，
  // 于是 `asDomainError` 在第 2 条判定（`code ∈ 契约 30 码`）就落选，落到 ④「未捕获 ⇒ 500」，
  // 与「编程错误不该伪装成用户错误」的分层一致。
  //
  // **谁给 `ScopeError` 加一个契约码（哪怕 `VALIDATION_ERROR`），它立刻变成 422 四键壳，
  // 「不该被 try/catch 吞掉」的语义当场消失**，而且不会有任何测试报错提醒你 ——
  // 这条不变量只靠这段注释与代码评审守住（已登记在 `T2-05.md` / 本条即登记点）。
  const domainError = asDomainError(error);
  if (domainError !== null) {
    const status = resolveDomainErrorStatus(domainError);
    return {
      status,
      origin: "domain_error",
      body: errorResponse(domainError.code, domainError.message, { ...domainError.data }, requestId),
    };
  }

  // ② 校验错误：恒 422，`data.errors` 为校验明细（契约实测形态 `{errors:[...]}`）。
  if (typeof error === "object" && error !== null) {
    const validation = (error as { validation?: unknown }).validation;
    if (Array.isArray(validation)) {
      return {
        status: 422,
        origin: "validation",
        body: errorResponse(
          ERROR_CODES.VALIDATION_ERROR,
          ERROR_DESCRIPTIONS[ERROR_CODES.VALIDATION_ERROR],
          { errors: validation },
          requestId,
        ),
      };
    }
  }

  // ③' 框架层 HTTPException（Fastify 自身产生的 404 / 405 / 415 等）：**原样保留**状态。
  const frameworkStatus = asFrameworkHttpStatus(error);
  if (frameworkStatus !== null) {
    const code = frameworkCodeForHttpStatus(frameworkStatus);
    const message =
      typeof (error as { message?: unknown }).message === "string"
        ? (error as { message: string }).message
        : ERROR_DESCRIPTIONS[code];
    return {
      status: frameworkStatus,
      origin: "http_exception",
      body: errorResponse(code, message, {}, requestId),
    };
  }

  // ④ 未捕获：恒 500。
  return {
    status: 500,
    origin: "unhandled",
    body: errorResponse(ERROR_CODES.INTERNAL_ERROR, UNHANDLED_MESSAGE, {}, requestId),
  };
}

/**
 * 取本次请求的 request_id（上下文优先，其次响应头，都没有则 `null`）。
 *
 * @param reply Fastify 响应对象。
 */
export function requestIdForReply(reply: FastifyReply): string | null {
  return currentRequestId() ?? headerToString(reply.getHeader(REQUEST_ID_HEADER)) ?? null;
}

/**
 * 统一出口：写状态码 + 四键壳，并在 5xx 落日志（4xx 属预期分支，不刷 error 日志）。
 *
 * @param request Fastify 请求。
 * @param reply Fastify 响应。
 * @param error 被抛出的值。
 */
function sendFailure(request: FastifyRequest, reply: FastifyReply, error: unknown): void {
  const outcome = toErrorOutcome(error, requestIdForReply(reply));

  if (outcome.status >= 500) {
    request.log.error(
      {
        err: error instanceof Error ? error : undefined,
        thrown: error instanceof Error ? undefined : String(error),
        error_origin: outcome.origin,
        error_code: outcome.body.code,
        error_http_status: outcome.status,
        path: pathOf(request.url),
        method: request.method,
      },
      "请求失败（5xx）",
    );
  }

  // `send(body)` 会走 Fastify 的 JSON 序列化器；响应壳中间件对 status >= 400 提前
  // return，因此这个壳是**唯一**一层。
  reply.code(outcome.status).type("application/json; charset=utf-8").send(outcome.body);
}

/**
 * 装配错误处理器 + 404 处理器。
 *
 * 404 必须显式接管：Fastify 默认的 not-found 响应是裸 `{statusCode,error,message}`，
 * 不接管就等于「框架路径上的失败壳缺失」，与契约 `runtime_probe.framework_404` 的
 * 实测（四键齐备、`request_id` 与头相等）不符。
 *
 * @param app Fastify 实例。
 */
export function registerErrorHandler(app: FastifyInstance): void {
  app.setErrorHandler((error, request, reply) => {
    sendFailure(request, reply, error);
  });

  app.setNotFoundHandler((request: FastifyRequest, reply: FastifyReply) => {
    sendFailure(
      request,
      reply,
      new HttpException(
        404,
        ERROR_CODES.NOT_FOUND,
        ERROR_DESCRIPTIONS[ERROR_CODES.NOT_FOUND],
      ),
    );
  });
}
