/**
 * T3-14 · 运行时 e2e 的**脚本化假 Provider**（R3-19：按脚本化 chunk 序列输出）。
 *
 * 为什么 e2e 侧自己装配而不是复用 `apps/api` 的 `createFakeProvider`
 * ---------------------------------------------------------------
 *   产品那个 fake 每次 `stream()` 重放**同一脚本**，于是"第一轮请求工具、第二轮给答复"
 *   这种跨轮序列表达不出来（工具回路会永远停在第一轮，直到预算耗尽）。
 *   运行时 e2e 要验的正是"主链能跑通一次工具回路"，所以需要**按调用次数推进**的脚本。
 *
 * 与产品 fake 的三条一致性要求（照抄，不放松）
 * --------------------------------------
 *   ① `usage` 只有三键（`prompt_tokens` / `completion_tokens` / `total_tokens`），
 *      **不得出现** `cache_read_tokens` / `cache_hit`（未提供 ≠ 0；伪造指标是本项目
 *      头号事故类型）—— 构造期就断言；
 *   ② 分片类型只允许 `text_delta` / `tool_call` / `usage` / `finish`（与
 *      `ProviderChunk` 同域），未知类型 ⇒ 抛错（不静默跳过，T3-02 首版的教训）；
 *   ③ 假 Provider 的装配**必须过闸**：`assertFakeProviderAllowed(process.env)`，
 *      没有 `NODE_ENV=test` 或 `WBTIME_AI_ALLOW_FAKE_PROVIDER=1` ⇒ 直接抛。
 */

import { ModelGateway } from "../../../apps/api/dist/modules/model/gateway.js";
import { assertFakeProviderAllowed } from "../../../apps/api/dist/modules/model/providers/factory.js";

/** 三键 usage（固定常量；无缓存键）。 */
export const FIXED_USAGE = Object.freeze({
  prompt_tokens: 10,
  completion_tokens: 5,
  total_tokens: 15,
});

const ALLOWED_CHUNK_TYPES = new Set(["text_delta", "tool_call", "usage", "finish"]);

/**
 * 校验一条分片（构造期，不放运行期）。
 *
 * @param {object} chunk 分片。
 * @throws {Error} 未知类型 / usage 含缓存键。
 */
function assertChunk(chunk) {
  if (!ALLOWED_CHUNK_TYPES.has(chunk.type)) {
    throw new Error(`脚本里出现未知分片类型 ${JSON.stringify(chunk.type)}`);
  }
  if (chunk.type === "usage") {
    for (const key of Object.keys(chunk.usage ?? {})) {
      if (key.includes("cache")) {
        throw new Error(`usage 不得含缓存键 ${JSON.stringify(key)}（未提供 ≠ 0）`);
      }
    }
  }
}

/**
 * 一轮"模型请求工具"的脚本。
 *
 * @param {string} callId 工具调用 id。
 * @param {string} name 工具名（内置名或 `mcp:<server>/<tool>`）。
 * @param {unknown} input 工具入参。
 * @param {string} [text] 附带文本。
 * @returns {Array<object>} chunk 序列。
 */
export function toolTurn(callId, name, input, text = "我需要调用一个工具。") {
  return [
    { type: "text_delta", text },
    { type: "tool_call", id: callId, name, input },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "tool_calls" },
  ];
}

/**
 * 一轮"模型给出最终答复"的脚本。
 *
 * @param {string} [text] 答复正文。
 * @returns {Array<object>} chunk 序列。
 */
export function finalTurn(text = "任务完成。") {
  return [
    { type: "text_delta", text },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "model_finish" },
  ];
}

/**
 * 建脚本化网关（**每调用一次消耗一个脚本**；最后一个脚本重复）。
 *
 * @param {Array<Array<object>>} turns 每轮的 chunk 序列。
 * @returns {ModelGateway} 可注入 `buildApp({modelGateway})`。
 * @throws {Error} 假 Provider 未放行 / 脚本非法。
 */
export function createScriptedGateway(turns) {
  assertFakeProviderAllowed(process.env);
  const scripts = turns.length === 0 ? [finalTurn()] : turns;
  for (const script of scripts) {
    for (const chunk of script) assertChunk(chunk);
  }

  let index = 0;
  const provider = {
    kind: "fake",
    providerName: "fake",
    async *stream() {
      const script = scripts[Math.min(index, scripts.length - 1)];
      index += 1;
      for (const chunk of script) {
        // `delayMs` 是 e2e 专用装饰（慢速 run 用），不进分片契约。
        if (chunk.delayMs !== undefined) {
          await new Promise((resolve) => setTimeout(resolve, chunk.delayMs));
        }
        const clean = { ...chunk };
        delete clean.delayMs;
        yield clean;
      }
    },
  };
  return new ModelGateway({ provider });
}
