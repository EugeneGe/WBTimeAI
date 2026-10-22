/**
 * T3-08 · runs **3 op**（契约 path / 成功码逐字）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 1 | GET `/api/v1/runs/{run_id}` | 200 `RunResponse` |
 * | 2 | POST `/api/v1/runs/{run_id}/cancel` | 200 `RunResponse`（**幂等**） |
 * | 3 | GET `/api/v1/runs/{run_id}/events` | 200 `text/event-stream`（12 帧） |
 *
 * SSE 端点的三个口径
 * ----------------
 *   ① **`Last-Event-ID` 与 `after_seq` 等价**（验收 ②）：header 优先按字符串解析，
 *      查询参数优先于 header（显式参数覆盖隐式续传）。两者都缺省 ⇒ `0`（从头回放）。
 *   ② **gap-aware**：只补"连续的那一段"，遇洞即停（`continualFrom`）。洞不是"跳过"，
 *      因为缺帧的因果链在前端无法渲染。
 *   ③ **本版是"有限订阅"**：轮询到 run 终态就收尾；未终态则最多轮询
 *      {@link RUN_EVENTS_MAX_POLLS} 轮后正常结束（客户端带 `Last-Event-ID` 重连续传）。
 *      **长连接订阅归 V0.3.1** —— 本卡不引入分布式取消总线，也不做帧级心跳线程。
 *
 * 端点**不注册**的路径（刻意）：`POST /runs`（契约无此 path —— run 由
 * `POST /agents/{id}/run` 的入口回执创建）、`DELETE /runs/{id}`（契约无）。
 * `routes-invariants` 的守恒断言会阻止"顺手加一条"。
 *
 * 续读**不得**触发执行（反例 ②）：本文件只读事件表，**不 import** 任何执行器；
 * 这条由 `sse-dispatch.test.mjs` 的静态面（导入路径断言）机械化。
 */

import { Type } from "@sinclair/typebox";
import type { FastifyInstance } from "fastify";

import { streamRunFrames } from "../modules/run/sse-stream.js";
import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 有限订阅的轮询上限（缺省 50ms × 40 = 2s）。
 *
 * 为什么必须有上限：没有上限的订阅会在"run 永不终态"时把 worker 与测试一起挂死。
 * 真正的长连接由 V0.3.1 的订阅总线承担；本版靠 `Last-Event-ID` 重连续传，
 * 语义上不丢帧（洞仍然按 `continualFrom` 处理）。
 */
export const RUN_EVENTS_MAX_POLLS = 40;

/** 轮询间隔（测试可注小；生产 50ms 足够跟上"一次 run 秒级"的事件密度）。 */
export const RUN_EVENTS_POLL_MS = 50;

/**
 * 契约 `GET /runs/{run_id}/events` 的 query。
 *
 * 契约只声明 `after_seq`（integer，无 minimum）⇒ 这里给 `minimum: 0`：
 * 负数 seq 不存在，放行只会得到空结果，把它挡成 422 更有诊断价值。
 */
const ListRunEventsQuerySchema = Type.Object(
  { after_seq: Type.Optional(Type.Integer({ minimum: 0 })) },
  { additionalProperties: false }
);

/** 解析 `Last-Event-ID`：只接受非负整数（SSE 规范里它是 last id，非数字视为无）。 */
function parseLastEventId(raw: unknown): number | undefined {
  if (typeof raw !== "string" || raw.trim() === "") return undefined;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : undefined;
}

/**
 * 注册 runs 路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `runs: RunService`，见 `app.ts` 装配）。
 */
export function runRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.runs;

  // 1. GET /runs/{run_id} —— 200（不可见 ⇒ 404）
  app.get(
    "/api/v1/runs/:run_id",
    { preValidation: authenticate(deps) },
    async (request) => service.getById(requiredParam(request.params, "run_id"))
  );

  // 2. POST /runs/{run_id}/cancel —— 200（**幂等**：已终态原样返回，不是 409）
  app.post(
    "/api/v1/runs/:run_id/cancel",
    { preValidation: authenticate(deps) },
    async (request) => service.cancel(requiredParam(request.params, "run_id"))
  );

  // 3. GET /runs/{run_id}/events —— 200 `text/event-stream`
  app.get(
    "/api/v1/runs/:run_id/events",
    {
      preValidation: authenticate(deps),
      schema: { querystring: ListRunEventsQuerySchema },
    },
    async (request, reply) => {
      const runId = requiredParam(request.params, "run_id");
      // 可见性先判：不存在 / 跨租户要回 **404 的 JSON 壳**，而不是一个空流。
      await service.assertVisible(runId);

      const query = request.query as { after_seq?: number };
      const afterSeq =
        query.after_seq ??
        parseLastEventId(request.headers["last-event-id"]) ??
        0;

      // 从这里起由本 handler 接管响应（Fastify 不再注入响应壳 / 不再序列化）。
      reply.hijack();
      reply.raw.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        // 关掉反代缓冲：否则帧会被攒成一坨再发，前端看到"卡住然后一次性刷出"。
        "x-accel-buffering": "no",
      });

      try {
        await streamRunFrames({
          readAfter: (seq, limit) => service.listEventRows(runId, seq, limit),
          isTerminal: () => service.isTerminal(runId),
          afterSeq,
          pollIntervalMs: RUN_EVENTS_POLL_MS,
          maxPolls: RUN_EVENTS_MAX_POLLS,
          signal: service.signalOf(runId),
          write: (frame) => {
            reply.raw.write(frame);
          },
        });
      } finally {
        reply.raw.end();
        // 收尾后清掉进程内取消信号，避免 Map 长期持有已完成的 run。
        service.forget(runId);
      }

      return reply;
    }
  );
}
