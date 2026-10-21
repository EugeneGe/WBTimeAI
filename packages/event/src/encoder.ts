// @wbtime/event · SSE 帧编码器（data frame + 心跳）。
//
// 字节口径（`contracts/sse/channels.json` → `frame_format`，冻结件）：
//
//   data frame   template = "id: {seq}\nevent: {channel}\ndata: {json}\n\n"
//   heartbeat    template = ": hb {now_ms}\n\n"     · carries_id = false
//   line_endings LF only —— 帧内不得出现 CR
//   json         ensure_ascii=False / separators=(",", ":") / sort_keys=False
//
// 三个 JSON 约束在 JS 侧的落法（不是「差不多」）：
//   * `ensure_ascii=False`：`JSON.stringify` **从不**把非 ASCII 转成 `\uXXXX`
//     （`"你好"` 原样），与 Python `ensure_ascii=False` 同义；
//   * `separators=(",", ":")`：`JSON.stringify` 默认就是紧凑无空格（无 `indent` 参数时）；
//   * `sort_keys=False`：键序 == payload 插入序 == 契约 `payload_keys_in_order`。
//     前提是 payload 由 `buildEventPayload()` 装配（它按契约键序重建对象）。
//     ⚠️ JS 会把「整数形态的键」提到最前（`{"2":..,"a":..}` 序为 2,a），契约键全是
//     snake_case 名，不触发该规则；这里记一笔，免得将来有人加个数字键名后帧悄悄变序。
//
// **编码器本体不做任何数值处理**（契约 `numeric_format.applied_where` 原话：归一化
// 发生在「把 payload 交给 encode_data_frame **之前**」）。整数值浮点 `1.0 → 1` 这类
// 陷阱由 `buildEventPayload() → normalizePayload()` 处理；若在编码器里再做一次，
// 就会出现「两个归一化点各改一半」的经典漂移。
//
// 编码器唯一的**形状**变换是契约登记的通道投影（`message.delta` 的 `content -> delta`，
// 契约把它归在 `encoder.py::_project_payload`，所以落在这里而不在 `buildEventPayload`），
// 见 {@link projectPayload}。
//
// 本版**只落编解码 + 语义常量**：4 个 `text/event-stream` 端点均不在 V0.2.0 的 4 路由族
// 内（`sse_endpoints`），运行面（`disconnect → cancel(run_id)`、`agent_event.seq` 分配）
// 归 V0.3.0。不得把本文件的字节等价说成「SSE 端点已验证」。

import { EventPayloadError, UnknownChannelError, isSseChannel } from "./channels.js";
import type { SseChannel } from "./generated/channels.generated.js";

/**
 * data frame 模板。
 *
 * 契约 `frame_format.data_frame.template` 以**转义形态**存放（`\n` 是两个字符：反斜杠 + n），
 * 本常量是还原后的**真实字符串**（行尾是真 LF）—— 因为真判据是 golden 字节与 sha256，
 * 不是「模板字面量长得一样」。两者的等价关系由 `tests/golden.test.mjs` 的
 * `K-7 格式不变量` 断言（`template.replaceAll("\\n", "\n") === DATA_FRAME_TEMPLATE`）。
 */
export const DATA_FRAME_TEMPLATE = "id: {seq}\nevent: {channel}\ndata: {json}\n\n";

/**
 * 心跳帧模板（同上：契约给转义形态，这里是真 LF）。
 * 契约 `frame_format.heartbeat.carries_id = false` —— 心跳**不带** `id:`。
 */
export const HEARTBEAT_TEMPLATE = ": hb {now_ms}\n\n";

/** 帧内分隔符：**只准** LF（契约 `line_endings`）。 */
export const LINE_SEPARATOR = "\n";

/** SSE payload（已由 `buildEventPayload()` 按契约键序装配）。 */
export type SsePayload = Readonly<Record<string, unknown>>;

/**
 * 通道专属 payload 投影（契约 `channels[].projection`）。
 *
 * 为什么需要这一层：契约对 `message.delta` 明写
 * `projection.rule = "content -> delta"`、`note = "该投影是通道专属逻辑，TS 侧必须逐字复刻"`、
 * `source = encoder.py::_project_payload` —— 也就是说**域事件的字段名与线上帧的字段名不同**：
 *
 *   `payload_keys_in_order`（域事件字段）= `[run_id, message_id, role, content]`
 *   `projected_fields`（线上帧字段）     = `[run_id, message_id, role, delta]`
 *
 * **已知生成物缺口（本版实测，非猜测）**：`scripts/gen_platform_contracts.mjs` 没有输出
 * `projection` / `projected_fields`（`grep -n "projection" scripts/gen_platform_contracts.mjs`
 * → 0 行），因此 `SseChannelSpec` 里拿不到这项，`buildEventPayload()` 只能产出**投影响应前**
 * 的 payload。若不补这一层，`message.delta` 的帧必然与 golden 差一个键名（实测 18/19）。
 *
 * 本版的落法：把契约里**唯一一条**投影写成下面这张表，并由
 * `tests/golden.test.mjs` **运行时读契约逐项比对**（rule / added / dropped 全等，且
 * 「契约里没投影的通道这里也必须没有」）。改成对照表而不是运行时读 `contracts/`，
 * 是因为生产包不该在运行期依赖仓库目录；让门禁盯住字面量，漂移立刻红。
 *
 * 根治方案（归 T2-11 / 生成器维护者）：让生成器把 `projected_fields` + `projection`
 * 输出到 `channels.generated.ts`，本表随之退化为生成物。已登记为遗留项。
 */
export interface PayloadProjection {
  /** `dropped` 键 → `added` 键的改名（契约 `projection.rule` 的箭头两侧）。 */
  readonly renames: Readonly<Record<string, string>>;
  /** 契约 `projection.added`。 */
  readonly added: readonly string[];
  /** 契约 `projection.dropped`。 */
  readonly dropped: readonly string[];
}

/** 通道 → 投影。只登记契约里真有投影的通道（当前仅 `message.delta`）。 */
export const PAYLOAD_PROJECTIONS: Readonly<Record<string, PayloadProjection>> = Object.freeze({
  "message.delta": Object.freeze({
    renames: Object.freeze({ content: "delta" }),
    added: Object.freeze(["delta"]),
    dropped: Object.freeze(["content"]),
  }),
});

/**
 * 对 payload 施加通道投影（无投影的通道原样返回**同一个**对象，不做无谓拷贝）。
 *
 * 关键细节：改名在**原位**完成（`out[renamed] = value` 发生在被丢弃键所在的位置），
 * 因此投影响应后的键序仍然等于契约 `projected_fields` —— 这是 `sort_keys=false`
 * 下字节可比的前提。若把 `delta` 追加到末尾，`message.delta` 的帧就会以
 * `…,"delta":"你好，世界"}` 之外的另一顺序输出，逐字节必红。
 *
 * 幂等：重复施加无害（`content` 已不在 payload 时，`delta` 原样保留）。
 *
 * @param channel 通道名。
 * @param payload 投影响应前的 payload。
 * @returns 投影响应后的 payload（新对象；无投影时为入参本身）。
 */
export function projectPayload(channel: SseChannel, payload: SsePayload): SsePayload {
  const projection = PAYLOAD_PROJECTIONS[channel];
  if (projection === undefined) return payload;

  const projected: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (projection.dropped.includes(key)) {
      const renamed = projection.renames[key];
      if (renamed !== undefined) projected[renamed] = value;
      continue;
    }
    projected[key] = value;
  }
  return projected;
}

/**
 * 编码一帧 `data` 事件。
 *
 * @param seq 事件序号（契约 `seq_policy`：真实流中等于 `agent_event.seq`；golden 固定 1）。
 *   必须是非负整数 —— `id: 1.5` / `id: NaN` 会让客户端 `Last-Event-ID` 续传口径彻底失效。
 * @param channel 通道名（19 条契约通道之一；运行期再校验一次，不靠类型断言裸奔）。
 * @param payload 已装配好的 payload（键序即线上键序）。
 * @returns 帧字节（UTF-8），以空行结尾。
 * @throws {RangeError} `seq` 不是非负整数。
 * @throws {UnknownChannelError} `channel` 不在 19 条契约通道内。
 * @throws {EventPayloadError} `payload` 不是普通对象（含 `undefined` / `null` / 数组 / 函数）。
 */
export function encodeDataFrame(seq: number, channel: SseChannel, payload: SsePayload): Buffer {
  if (typeof seq !== "number" || !Number.isInteger(seq) || seq < 0) {
    throw new RangeError(`encodeDataFrame: seq 必须是非负整数，收到 ${String(seq)}`);
  }
  if (!isSseChannel(channel)) {
    // 复用 channels.ts 的 `UnknownChannelError`：同一个「未知通道」概念只有一处定义，
    // 否则上层按 `instanceof` 归因时会有两个互不认识的类（本项目反复踩过这个坑）。
    throw new UnknownChannelError(channel);
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new EventPayloadError(
      channel,
      `${channel}: payload 必须是普通对象（data 行要放一个 JSON object，不是 ${describe(payload)}）`,
    );
  }

  const json = JSON.stringify(projectPayload(channel, payload));
  if (typeof json !== "string") {
    // `JSON.stringify(undefined)` / 只含函数与 symbol 的对象会返回 undefined。
    throw new EventPayloadError(channel, `${channel}: payload 无法序列化为 JSON`);
  }

  const text = `id: ${seq}${LINE_SEPARATOR}event: ${channel}${LINE_SEPARATOR}data: ${json}${LINE_SEPARATOR}${LINE_SEPARATOR}`;
  return toLfOnlyBuffer(channel, text);
}

/**
 * 编码心跳注释帧（`: hb {now_ms}`）。
 *
 * **不带 `id:`**（契约 `heartbeat.carries_id = false`）：带 id 会污染客户端
 * `Last-Event-ID`，重连时把「心跳序号」当成「可续传事件序号」，直接丢事件。
 *
 * 发送条件与间隔**不在本函数**：契约 `only_when_idle` + `default_interval_seconds`
 * 属运行面（V0.3.0），本版不实现、也不在代码里复制一份间隔数值。
 *
 * @param nowMs 当前毫秒时间戳（非负整数）。
 * @returns 帧字节（UTF-8）。
 * @throws {RangeError} `nowMs` 不是非负整数。
 */
export function encodeHeartbeat(nowMs: number): Buffer {
  if (typeof nowMs !== "number" || !Number.isInteger(nowMs) || nowMs < 0) {
    throw new RangeError(`encodeHeartbeat: now_ms 必须是非负整数，收到 ${String(nowMs)}`);
  }
  return toLfOnlyBuffer("heartbeat", `: hb ${nowMs}${LINE_SEPARATOR}${LINE_SEPARATOR}`);
}

/**
 * 把帧文本转成 Buffer，并守住「LF only」这条字节红线。
 *
 * 为什么值得单独一个函数：`\r` 一旦进帧，`id:` / `data:` 行的行尾就变成 CRLF，
 * 19/19 逐字节立即失配，而且失败信息会指向「载荷不同」这种错误方向（实际是行尾）。
 * 把守卫放在唯一的出口上，比在每个调用点各写一次可靠。
 *
 * 说明：JSON 字符串里的 `\r` 已被 `JSON.stringify` 转义成两个字符 `\` + `r`，
 * 因此**正常路径永远不会命中**这条守卫 —— 它是给「将来改了模板 / 拼帧方式」兜底的。
 */
function toLfOnlyBuffer(label: string, text: string): Buffer {
  if (text.includes("\r")) {
    throw new RangeError(`${label}: 帧内出现 CR，SSE 帧必须 LF only（契约 line_endings）`);
  }
  return Buffer.from(text, "utf8");
}

/** 给错误信息用的类型描述（不泄露内容，只说形态）。 */
function describe(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}
