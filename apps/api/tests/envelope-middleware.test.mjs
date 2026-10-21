// T2-02 · 响应壳中间件行为（6 类不套壳 + 已是壳幂等 + request_id「体 == 头」）
//
// 口径来源：`contracts/envelope.schema.json` → `x-wbtimeai.enforcement.not_wrapped.cases`
// （6 条，一条不落）与 `02-响应壳与SSE.md` §2.4。
//
// 做法：`buildApp()` **不 ready**，测试在此之后注册探针路由再 `ready()` —— 这样
// 「6 类不套壳」测的是真实 HTTP 响应，而不是把单元函数自己写一遍再自己断言一遍。
// 探针路由不进产品路由表（`apps/api/src/routes/` 只有 `/healthz`）。

import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { ENVELOPE_FIELD_NAMES, okResponse } from "@wbtime/core";

import { buildApp } from "../dist/app.js";
import {
  FRAMEWORK_PATHS,
  decideWrap,
  isEmptyPayload,
  pathOf,
  wrapSuccess,
} from "../dist/http/envelope.js";
import { HttpException, toErrorOutcome } from "../dist/http/error-handler.js";
import {
  REQUEST_ID_HEADER,
  currentRequestId,
  generateRequestId,
  readRequestIdHeader,
  resolveRequestId,
} from "../dist/http/request-context.js";

/** 探针：跨若干微任务 / 定时器后再取 request_id，验证 ALS 真的贯通。 */
async function deepRequestId() {
  await new Promise((resolve) => setTimeout(resolve, 1));
  await Promise.resolve();
  return currentRequestId() ?? null;
}

const app = buildApp({ enableLogging: false });

// ── 探针路由（不套壳的 6 类各一条 + 两条错误出口）──────────────────────────
app.get("/probe/bare", async () => ({ id: "a1", nested: { n: 2 } }));
app.get("/probe/already-shell", async () => okResponse({ id: "a1" }, currentRequestId() ?? null));
app.get("/probe/sse", async (_request, reply) =>
  reply.type("text/event-stream; charset=utf-8").send("event: ping\ndata: {}\n\n"),
);
app.get("/probe/text", async (_request, reply) =>
  reply.type("text/plain; charset=utf-8").send("pong"),
);
app.get("/openapi.json", async () => ({ openapi: "3.1.0", info: { title: "probe" } }));
app.get("/probe/empty", async (_request, reply) => reply.code(204).send());
app.get("/probe/failure", async () => {
  throw new HttpException(404, "NOT_FOUND", "资源不存在");
});
app.get("/probe/unhandled", async () => {
  throw new Error("boom（内部细节不得出现在响应体里）");
});
app.get("/probe/rid", async () => ({ request_id: currentRequestId() ?? null, deep: await deepRequestId() }));

before(async () => {
  await app.ready();
});

after(async () => {
  await app.close();
});

function assertFourKeys(body) {
  assert.deepEqual(
    Object.keys(body).sort(),
    [...ENVELOPE_FIELD_NAMES].sort(),
    "顶层键必须恰好是契约四键（壳只有一层，第 5 个键非法）",
  );
}

// ── ① 成功 JSON：套壳、四键齐备、体 == 头 ────────────────────────────────
test("成功 JSON 被套壳：code=0 / message=ok / data 为裸对象 / request_id 四键齐备", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/bare" });

  assert.equal(res.statusCode, 200);
  const body = res.json();
  assertFourKeys(body);
  assert.equal(body.code, 0);
  assert.equal(typeof body.code, "number");
  assert.equal(body.message, "ok");
  assert.deepEqual(body.data, { id: "a1", nested: { n: 2 } }, "data 必须是裸业务对象，不加二级壳");

  assert.equal(body.request_id, res.headers[REQUEST_ID_HEADER], "体 request_id 必须等于响应头");
  assert.equal(typeof body.request_id, "string");
});

test("request_id 优先取请求头；缺失时才生成（键恒在，值非 null）", async () => {
  const given = await app.inject({
    method: "GET",
    url: "/probe/bare",
    headers: { "x-request-id": "rid-from-client" },
  });
  assert.equal(given.json().request_id, "rid-from-client");
  assert.equal(given.headers[REQUEST_ID_HEADER], "rid-from-client");

  const generated = await app.inject({ method: "GET", url: "/probe/bare" });
  assert.equal(generated.json().request_id, generated.headers[REQUEST_ID_HEADER]);
  assert.match(
    generated.headers[REQUEST_ID_HEADER],
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    "生成的 request_id 必须是 UUID 形态",
  );
});

test("AsyncLocalStorage 贯通：handler 内深 await 后仍取到同一个 request_id", async () => {
  const res = await app.inject({
    method: "GET",
    url: "/probe/rid",
    headers: { "x-request-id": "rid-als" },
  });

  const body = res.json();
  // 注意：`/probe/rid` 是普通 JSON 成功响应 ⇒ 业务对象在 `data` 里，不在顶层。
  assert.equal(body.data.request_id, "rid-als");
  assert.equal(body.data.deep, "rid-als", "深 await 后 context 丢失 = ALS 没贯通");
  assert.equal(body.request_id, "rid-als", "壳的 request_id 也必须同源");
});

test("/healthz 被套壳（健康检查不是 not_wrapped 的例外）", async () => {
  const res = await app.inject({ method: "GET", url: "/healthz" });

  assert.equal(res.statusCode, 200);
  const body = res.json();
  assertFourKeys(body);
  assert.equal(body.code, 0);
  assert.equal(body.message, "ok");
  assert.equal(body.data.status, "ok");
  assert.equal(typeof body.data.uptime_seconds, "number");
  assert.equal(body.request_id, res.headers[REQUEST_ID_HEADER]);
});

// ── ② 失败壳不进中间件（唯一出口是 error-handler）────────────────────────
test("failure：失败壳只有一层（status>=400 由 error-handler 直出，中间件提前 return）", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/failure" });

  assert.equal(res.statusCode, 404);
  const body = res.json();
  assertFourKeys(body);
  assert.equal(typeof body.code, "string");
  assert.equal(body.code, "NOT_FOUND");
  assert.deepEqual(body.data, {}, "data 不得变成 {code:…}（那就是二次包裹）");
  assert.equal(body.request_id, res.headers[REQUEST_ID_HEADER]);
});

test("未捕获异常：恒 500 + INTERNAL_ERROR，且不泄露内部细节", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/unhandled" });

  assert.equal(res.statusCode, 500);
  const body = res.json();
  assertFourKeys(body);
  assert.equal(body.code, "INTERNAL_ERROR");
  assert.equal(body.data && Object.keys(body.data).length, 0);
  assert.ok(
    !JSON.stringify(body).includes("boom（内部细节"),
    "未捕获错误的 message 不得回显原始异常文本",
  );
});

test("框架 404（未注册路径）也必须是四键壳，且 request_id 与头相等", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/does-not-exist" });

  assert.equal(res.statusCode, 404);
  const body = res.json();
  assertFourKeys(body);
  assert.equal(body.code, "NOT_FOUND");
  assert.equal(body.request_id, res.headers[REQUEST_ID_HEADER]);
});

// ── ③ 其余 4 类不套壳 ────────────────────────────────────────────────────
test("sse：text/event-stream 原样返回（帧契约不容包裹）", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/sse" });

  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"], /text\/event-stream/);
  assert.equal(res.body, "event: ping\ndata: {}\n\n", "SSE 帧不得被改一个字节");
});

test("non_json：text/plain 原样返回", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/text" });

  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"], /text\/plain/);
  assert.equal(res.body, "pong");
});

test("framework_path：/openapi.json 原样返回（供 Swagger / Redoc 消费）", async () => {
  const res = await app.inject({ method: "GET", url: "/openapi.json" });

  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.json(), { openapi: "3.1.0", info: { title: "probe" } });
});

test("empty_body：204 零字节体（只保留状态码与响应头）", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/empty" });

  assert.equal(res.statusCode, 204);
  assert.equal(res.body, "");
  assert.equal(res.payload, "");
});

test("already_shell：已是成功壳则原样透传（不二次包裹）", async () => {
  const res = await app.inject({ method: "GET", url: "/probe/already-shell" });

  assert.equal(res.statusCode, 200);
  const body = res.json();
  assertFourKeys(body);
  assert.deepEqual(body.data, { id: "a1" }, "data 必须还是裸对象");
  assert.equal(
    body.data.code,
    undefined,
    "data 里出现 code ⇒ 被套了两层（键判定而非值判定会踩这个坑）",
  );
});

// ── ④ 六类判定的纯函数逐条断言（与 HTTP 层双保险）────────────────────────
test("decideWrap：status>=400 ⇒ failure", () => {
  assert.deepEqual(
    decideWrap({ status: 404, contentType: "application/json", path: "/x", bodyIsEmpty: false, body: {} }),
    { wrap: false, reason: "failure" },
  );
});

test("decideWrap：text/event-stream ⇒ sse", () => {
  assert.deepEqual(
    decideWrap({
      status: 200,
      contentType: "text/event-stream; charset=utf-8",
      path: "/events",
      bodyIsEmpty: false,
      body: {},
    }),
    { wrap: false, reason: "sse" },
  );
});

test("decideWrap：非 JSON content-type ⇒ non_json", () => {
  assert.deepEqual(
    decideWrap({ status: 200, contentType: "text/plain", path: "/metrics", bodyIsEmpty: false, body: "x" }),
    { wrap: false, reason: "non_json" },
  );
  assert.deepEqual(
    decideWrap({ status: 200, contentType: null, path: "/x", bodyIsEmpty: false, body: "x" }),
    { wrap: false, reason: "non_json" },
  );
});

test("decideWrap：/openapi.json ⇒ framework_path", () => {
  assert.deepEqual(FRAMEWORK_PATHS, ["/openapi.json"]);
  assert.deepEqual(
    decideWrap({
      status: 200,
      contentType: "application/json",
      path: "/openapi.json",
      bodyIsEmpty: false,
      body: {},
    }),
    { wrap: false, reason: "framework_path" },
  );
});

test("decideWrap：已是成功壳 ⇒ already_shell；连打两次仍只有一层", () => {
  const first = wrapSuccess({ a: 1 }, "rid");
  assert.deepEqual(
    decideWrap({ status: 200, contentType: "application/json", path: "/x", bodyIsEmpty: false, body: first }),
    { wrap: false, reason: "already_shell" },
  );

  // 反例：失败壳（键都在但值不是成功壳）不得被判成 already_shell。
  const failureLike = { code: "NOT_FOUND", message: "资源不存在", data: {}, request_id: "rid" };
  assert.deepEqual(
    decideWrap({
      status: 200,
      contentType: "application/json",
      path: "/x",
      bodyIsEmpty: false,
      body: failureLike,
    }),
    { wrap: true },
    "键判定会把失败壳误当成功壳；值判定必须仍去套壳",
  );
});

test("decideWrap：空体 ⇒ empty_body（排在 non_json 之前，否则 204 会被误报）", () => {
  assert.deepEqual(
    decideWrap({ status: 204, contentType: null, path: "/x", bodyIsEmpty: true, body: undefined }),
    { wrap: false, reason: "empty_body" },
  );
});

test("decideWrap：普通成功 JSON ⇒ wrap=true（正例，防「六条排除全命中」的假成立）", () => {
  assert.deepEqual(
    decideWrap({ status: 200, contentType: "application/json; charset=utf-8", path: "/x", bodyIsEmpty: false, body: { a: 1 } }),
    { wrap: true },
  );
});

test("辅助函数：空体判定 / 路径归一化", () => {
  assert.equal(isEmptyPayload(null), true);
  assert.equal(isEmptyPayload(undefined), true);
  assert.equal(isEmptyPayload(""), true);
  assert.equal(isEmptyPayload(Buffer.alloc(0)), true);
  assert.equal(isEmptyPayload("{}"), false);
  assert.equal(isEmptyPayload(Buffer.from("{}")), false);

  assert.equal(pathOf("/openapi.json"), "/openapi.json");
  assert.equal(pathOf("/a?b=1"), "/a");
  assert.equal(pathOf("/a#frag"), "/a");
  assert.equal(pathOf("/a?b=1#c"), "/a");
});

test("HttpException 状态码必须落在 400..599（2xx 的「错误」会把失败渲染成成功）", () => {
  assert.throws(() => new HttpException(200, "INTERNAL_ERROR", "x"), RangeError);
  assert.throws(() => new HttpException(302, "INTERNAL_ERROR", "x"), RangeError);
  assert.throws(() => new HttpException(499.5, "INTERNAL_ERROR", "x"), RangeError);

  const ok = new HttpException(405, "METHOD_NOT_ALLOWED", "方法不被允许");
  assert.equal(ok.statusCode, 405);
  assert.equal(ok.code, "METHOD_NOT_ALLOWED");

  // 405 在本版只能由显式 HttpException 触发（Fastify 对方法不匹配默认返 404），
  // 出口必须原样保留状态码 —— 这条断言就是「原样」的证据。
  const outcome = toErrorOutcome(ok, "rid-405");
  assert.equal(outcome.status, 405);
  assert.equal(outcome.origin, "http_exception");
  assert.equal(outcome.body.code, "METHOD_NOT_ALLOWED");
  assert.equal(outcome.body.request_id, "rid-405");
});

test("request_id 头解析：数组 / 空白一律视为未提供", () => {
  assert.equal(readRequestIdHeader("  rid-1  "), "rid-1");
  assert.equal(readRequestIdHeader("   "), null);
  assert.equal(readRequestIdHeader(undefined), null);
  assert.equal(readRequestIdHeader(["a", "b"]), null);

  const generated = resolveRequestId(undefined);
  assert.match(generated, /^[0-9a-f]{8}-[0-9a-f]{4}-/);
  assert.equal(resolveRequestId("rid-2"), "rid-2");

  // 已知偏差登记（详见 施工记录/T2-02.md）：Node v22.22.2 无内置 UUIDv7，
  // 本版生成的是 v4；此处**不**断言版本号，以免将来换 v7 时被自己的测试挡住，
  // 但也绝不把它称作 v7。
  assert.match(generateRequestId(), /^[0-9a-f-]{36}$/);
});
