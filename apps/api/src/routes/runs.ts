/**
 * T3-08 · runs **3 op**（契约 path / 成功码逐字）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 1 | GET `/api/v1/runs/{run_id}` | 200 `RunResponse` |
 * | 2 | POST `/api/v1/runs/{run_id}/cancel` | 200 `RunResponse`（**幂等**） |
 * | 3 | GET `/api/v1/runs/{run_id}/events` | 200 `text/event-stream`（14 帧） |
 *
 * SSE 端点的三个口径
 * ----------------
 *   ① **`Last-Event-ID` 与 `after_seq` 等价**（验收 ②）：header 优先按字符串解析，
 *      查询参数优先于 header（显式参数覆盖隐式续传）。两者都缺省 ⇒ `0`（从头回放）。
 *   ② **gap-aware**：只补"连续的那一段"，遇洞即停（`continualFrom`）。洞不是"跳过"，
 *      因为缺帧的因果链在前端无法渲染。
 *   ③ **长连接订阅**（V0.3.1 · R-4/U5，对 V0.3.0"40 轮 ≈2s 有限订阅"的修正）：
 *      订阅随 run 生命周期收尾 —— 终态（含终态前后脚的尾帧）后正常结束；取消 /
 *      客户端断开经 `AbortSignal.any` 立即收尾（AUD-11 保持：断开后一个轮询周期内
 *      停止轮询）。不再有"轮数用尽"的收尾形态。
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
        // **客户端断开**也要能收尾（AUD-11）。
        //
        // 原先只把 `service.signalOf(runId)` 传给流：那个 signal 只在**取消**时置位，
        // 浏览器关标签页 / 断网时它永远不动 ⇒ handler 继续空轮询到 2s 上限，
        // 期间占着一个 worker 与一条死连接的句柄（轮询一直读库）。
        //
        // 这里另建一个**本地** controller，监听 `request.raw` 的 `close`（客户端断开 /
        // 响应被销毁），用 `AbortSignal.any` 把两个来源合一：任一置位即收尾。
        // 监听器在 `finally` 里移除 —— 否则长连接反复进入会把 emitter 撑大（MaxListeners）。
        const clientAbort = new AbortController();
        const onClientClose = (): void => {
          clientAbort.abort();
        };
        request.raw.on("close", onClientClose);

        try {
          await streamRunFrames({
            runId,
            readAfter: (seq, limit) => service.listEventRows(runId, seq, limit),
            isTerminal: () => service.isTerminal(runId),
            afterSeq,
            pollIntervalMs: RUN_EVENTS_POLL_MS,
            // 长连接（V0.3.1 · R-4/U5）：不传 `maxPolls` ⇒ 无限订阅，
            // 由终态 / 取消信号 / 客户端断开三个出口收尾。
            signal: AbortSignal.any([service.signalOf(runId), clientAbort.signal]),
            write: (frame) => {
              // 客户端已断开 ⇒ 不再往死 socket 上写（写了也不会有人收）。
              if (clientAbort.signal.aborted) return;
              try {
                reply.raw.write(frame);
              } catch {
                // 写失败（EPIPE / 已 destroy）**不得让 handler 崩**：客户端断开是正常
                // 事件，不是服务端故障。按断开处理，让循环走 `aborted` 收尾。
                clientAbort.abort();
              }
            },
          });
        } finally {
          request.raw.off("close", onClientClose);
        }
      } finally {
        try {
          reply.raw.end();
        } catch {
          // 同上：socket 已被对端关掉，`end()` 抛错不影响任何业务事实。
        }
        // 收尾后清掉进程内取消信号 —— **只在 run 已终态时**（AUD-02）：
        // 在飞 run 的 controller 必须留着，否则 `cancel` 会作用在新 controller 上，
        // 而 driver 持有的旧 signal 永不置位 ⇒ 取消失效。
        await service.forgetIfTerminal(runId);
      }

      return reply;
    }
  );
}
