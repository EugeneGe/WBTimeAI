// @wbtime/api · 请求规范化（T3-02）—— 缓存观测的"稳定前缀"。
//
// 为什么需要它：提示词缓存按**前缀字节**命中。若同一逻辑请求两次序列化出的字节不同
// （键序抖动、工具 schema 键序抖动、把 `run_id` / 时间戳塞进请求），缓存命中率会莫名其妙
// 掉到 0，而且**看不出原因**。这里把"同一请求 ⇒ 同一字节"变成可断言的属性。
//
// 三条纪律：
//   1. **工具按注册顺序**（不是字母序）：注册顺序是语义的一部分（模型看到的能力顺序），
//      字母序会把 `read_file` 排到 `write_file` 前，改变提示结构；
//   2. **schema 内部键排序**：JSON Schema 的键序无语义，排序才能稳定；
//   3. **动态字段一律剔除**：`run_id` / `request_id` / 时间戳进请求 = 每次都是新前缀。
//
// 纯函数，零 IO；`fingerprint` 用 `node:crypto` 的 sha256。

import { createHash } from "node:crypto";

import type { ModelMessage, ModelRequest, ModelToolSpec } from "@wbtime/domain";

/** 规范化时要剔除的动态字段（即便调用方误塞进请求，也不参与指纹）。 */
const DYNAMIC_FIELDS: ReadonlySet<string> = new Set([
  "run_id",
  "runId",
  "request_id",
  "requestId",
  "now",
  "timestamp",
  "created_at",
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * 递归规范化任意 JSON 值：
 *   * 对象 ⇒ 键**排序**后重建（剔除动态字段）；
 *   * 数组 ⇒ **保序**（数组顺序有语义）；
 *   * 其余（含 `null`）原样返回。
 */
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isPlainObject(value)) return value;

  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) {
    if (DYNAMIC_FIELDS.has(key)) continue;
    const item = value[key];
    if (item === undefined) continue;
    out[key] = canonicalize(item);
  }
  return out;
}

function normalizeMessage(message: ModelMessage): Record<string, unknown> {
  const out: Record<string, unknown> = {
    role: message.role,
    content: message.content,
  };
  if (message.toolCallId !== undefined) out.tool_call_id = message.toolCallId;
  return out;
}

function normalizeTool(tool: ModelToolSpec): Record<string, unknown> {
  const out: Record<string, unknown> = {
    name: tool.name,
    input_schema: canonicalize(tool.inputSchema),
  };
  if (tool.description !== undefined) out.description = tool.description;
  return out;
}

/**
 * 把请求序列化成**确定性字符串**（同输入 ⇒ 逐字节相同）。
 *
 * 结构固定为 `{model, messages[], tools[]?, max_output_tokens?, temperature?}`，
 * 键顺序写死；缺失字段**不出现**（不是 `null`）。
 */
export function stableSerialize(request: ModelRequest): string {
  const payload: Record<string, unknown> = {
    model: request.model,
    messages: request.messages.map(normalizeMessage),
  };
  if (request.tools !== undefined && request.tools.length > 0) {
    payload.tools = request.tools.map(normalizeTool);
  }
  if (request.maxOutputTokens !== undefined) payload.max_output_tokens = request.maxOutputTokens;
  if (request.temperature !== undefined) payload.temperature = request.temperature;
  return JSON.stringify(payload);
}

/** 请求指纹（小写 hex sha256）。同一请求两次调用必须相等 —— 这是反例门禁的断言点。 */
export function fingerprint(request: ModelRequest): string {
  return createHash("sha256").update(stableSerialize(request), "utf8").digest("hex");
}
