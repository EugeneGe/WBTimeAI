/**
 * 真实长连接 SSE 夹具（V0.2.0 审计 #11）—— **真建流、真读帧、真断开、零泄漏**。
 *
 * 背景：case-3 原先用 `/healthz` + 404 **替代** SSE 语义（TS 后端 V0.2.0 的 19 op
 * 里没有 SSE 端点）。该替代证明的是「端点不存在」，从未真正走过 SSE 链路。
 * 本夹具补上这一层：起一个**真 HTTP SSE 服务器**（`node:http`，零新依赖），客户端
 * 用 `fetch` + `AbortController` 建**真长连接**、按 chunk **真读帧**（帧解析复用
 * `lib/sse.mjs` 的 `SseStreamParser`，与生产 golden 同一实现），然后**真断开**，
 * 并断言服务端连接数**归零**（断开后无泄漏连接）。
 *
 * 与产品端点的关系（诚实边界，不是 skip、不是 mock）：V0.3.0 的 T3-08 落地
 * `GET /runs/{id}/events` 后，本夹具可原样改打到后端真端点；在端点落地前，它验证
 * 的是「SSE 夹具链路本身真实可用」，产品端点的缺失仍由 case-3 的 404 反向证明
 * **显式登记**，绝不声称「SSE 语义已验证」。
 *
 * 帧布局（与 `contracts/sse/channels.json` 的 frame_format 一致）：
 *   `id: <int>\nevent: <channel>\ndata: <json>\n\n`；心跳为注释帧 `: hb <ms>\n\n`。
 */

import http from "node:http";

import { SseStreamParser } from "./sse.mjs";

/** 一条要下发的 SSE 事件帧。 */
/**
 * @typedef {{id: number, event: string, data: unknown}} SseFrame
 */

/**
 * 把一帧序列化成契约线格式（逐字节确定：单 `data` 行 + 空行结尾）。
 *
 * @param {SseFrame} frame
 * @returns {string}
 */
export function serializeFrame(frame) {
  return `id: ${frame.id}\nevent: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`;
}

/**
 * 起一个真实 SSE 长连接服务器（127.0.0.1 随机空闲端口）。
 *
 * 行为：
 *   * `GET /sse` —— 200 + `text/event-stream`，注册进连接表，**保持打开**；
 *     先按序下发 `frames`（每帧间隔 `frameDelayMs`），随后只发心跳，永不主动结束
 *     —— 断开只能由客户端发起（真断开语义）；
 *   * 其他路径 —— 404（路由真实性自证）。
 *
 * @param {{frames?: SseFrame[], frameDelayMs?: number}} [options]
 * @returns {Promise<{baseUrl, url, port, connectionCount: () => number,
 *                     waitForConnections: (count: number, timeoutMs?: number) => Promise<void>,
 *                     stop: () => Promise<void>}>}
 */
export function startSseFixture(options = {}) {
  const {
    frames = [],
    frameDelayMs = 10,
  } = options;

  /** 活跃 SSE 连接（response 对象）；泄漏判定的唯一数据源。 */
  const connections = new Set();

  const server = http.createServer((request, response) => {
    const path = request.url ?? "";
    if (!path.startsWith("/sse")) {
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "not found" }));
      return;
    }

    response.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    connections.add(response);

    // 客户端真断开（abort）⇒ 'close' ⇒ 移出连接表。泄漏断言看的就是这个集合。
    response.on("close", () => connections.delete(response));

    let index = 0;
    const pump = setInterval(() => {
      if (index < frames.length) {
        response.write(serializeFrame(frames[index]));
        index += 1;
      } else {
        response.write(`: hb ${Date.now()}\n\n`); // 心跳注释帧（无 id，不污染 Last-Event-ID）
      }
    }, Math.max(frameDelayMs, 1));
    // 心跳与帧下发共用一个 interval；连接关闭时必须停掉，否则 interval 泄漏。
    response.on("close", () => clearInterval(pump));
  });

  // 帧间隔同时也是空转期的心跳频率（`frameDelayMs`）。
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      const baseUrl = `http://127.0.0.1:${port}`;
      resolve({
        baseUrl,
        url: `${baseUrl}/sse`,
        port,
        /** 当前活跃 SSE 连接数（0 = 无泄漏）。 */
        connectionCount: () => connections.size,
        /**
         * 等待连接数到达期望值（轮询）。
         * @param {number} count 期望连接数。
         * @param {number} [timeoutMs] 缺省 5000。
         */
        async waitForConnections(count, timeoutMs = 5000) {
          const deadline = Date.now() + timeoutMs;
          for (;;) {
            if (connections.size === count) return;
            if (Date.now() > deadline) {
              throw new Error(
                `SSE 夹具连接数未达 ${count}（实测 ${connections.size}，timeout=${timeoutMs}ms）`,
              );
            }
            await new Promise((settle) => setTimeout(settle, 25));
          }
        },
        /** 停服并强拆所有连接（幂等）。 */
        async stop() {
          server.closeAllConnections();
          await new Promise((settle) => server.close(() => settle()));
        },
      });
    });
  });
}

/**
 * 打开一条真实 SSE 长连接并**真读帧**：fetch（`Accept: text/event-stream`）+
 * `body.getReader()` 逐 chunk 喂 {@link SseStreamParser}（与 golden 同一解析实现）。
 *
 * @param {string} url SSE 端点。
 * @param {{controller: AbortController, maxFrames?: number, timeoutMs?: number}} options
 *   `controller` 由调用方持有 —— `abort()` 是「真断开」动作本身（AbortSignal 只有
 *   只读状态，真正能发起断开的是 AbortController，调用方必须持它）。
 * @returns {Promise<{response: Response, frames: Array<object>, abort: () => void}>}
 *   `frames` 收齐 `maxFrames` 帧（或超时）后返回；连接**仍保持打开**，由调用方 abort。
 */
export async function openSseStream(url, options) {
  const { controller, maxFrames = 3, timeoutMs = 10_000 } = options;
  const signal = controller.signal;
  const deadline = Date.now() + timeoutMs;

  const response = await fetch(url, {
    headers: { accept: "text/event-stream" },
    signal,
  });

  const parser = new SseStreamParser();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  for (;;) {
    if (Date.now() > deadline) {
      throw new Error(`SSE 读帧超时（已收 ${parser.frames.length} 帧，期望 ${maxFrames}，timeout=${timeoutMs}ms）`);
    }
    const chunk = await Promise.race([
      reader.read(),
      new Promise((_, rejectLater) =>
        setTimeout(() => rejectLater(new Error("SSE reader.read() 停滞（连接可能被服务端掐断）")), timeoutMs),
      ),
    ]);
    if (chunk.done) break;
    parser.push(decoder.decode(chunk.value, { stream: true }));
    if (parser.frames.length >= maxFrames) break;
  }

  return {
    response,
    frames: parser.frames,
    abort: () => controller.abort(),
  };
}
