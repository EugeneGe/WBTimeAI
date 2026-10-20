// @wbtime/event · 通道门面。
//
// 通道本体在 `./generated/channels.generated.ts`，由脚本从
// contracts/sse/channels.json 生成。本文件只提供「判别 + 按契约键序装配 payload」
// 两个能力，不在此处新增任何通道。

import { ERROR_CODES, httpStatusFor } from "@wbtime/core";

import {
  NUMERIC_FIXED_DECIMALS,
  NUMERIC_FORMAT_POLICY,
  NUMERIC_FORMAT_RULE_VERSION,
  SSE_CHANNEL_LIST,
  SSE_CHANNEL_SPECS,
  SSE_CHANNELS,
} from "./generated/channels.generated.js";
import type { SseChannel, SseChannelSpec } from "./generated/channels.generated.js";
import { normalizePayload } from "./numeric.js";

export {
  NUMERIC_FIXED_DECIMALS,
  NUMERIC_FORMAT_POLICY,
  NUMERIC_FORMAT_RULE_VERSION,
  SSE_CHANNEL_LIST,
  SSE_CHANNEL_SPECS,
  SSE_CHANNELS,
};
export type { SseChannel, SseChannelSpec } from "./generated/channels.generated.js";

/** 未知通道。错误码走 core（与 contracts/errors.json 同源）。 */
export class UnknownChannelError extends Error {
  readonly name = "UnknownChannelError";
  readonly code = ERROR_CODES.VALIDATION_ERROR;
  readonly channel: string;

  constructor(channel: string) {
    super(`未知 SSE 通道: ${JSON.stringify(channel)}`);
    this.channel = channel;
  }

  get httpStatus(): number {
    return httpStatusFor(this.code);
  }
}

export function isSseChannel(value: string): value is SseChannel {
  return (SSE_CHANNEL_LIST as readonly string[]).includes(value);
}

/** 取通道规格；未知通道抛错（不静默降级）。 */
export function channelSpec(channel: SseChannel): SseChannelSpec {
  const spec = SSE_CHANNEL_SPECS[channel];
  if (spec === undefined) throw new UnknownChannelError(channel);
  return spec;
}

/**
 * 按契约键序装配事件 payload。
 *
 * 两件事在这里定死：
 *   1. 键序 = `payload_keys_in_order`（契约 `sort_keys: false`，字节可比的前提）；
 *   2. 每个值先过 `normalizePayload`（数值上线格式定死）。
 *
 * 未出现在键序里的多余键一律拒绝 —— 多一个键，golden 帧就对不上。
 */
export function buildEventPayload(
  channel: SseChannel,
  values: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const spec = channelSpec(channel);
  const extra = Object.keys(values).filter((k) => !spec.payloadKeysInOrder.includes(k));
  if (extra.length > 0) {
    throw new UnknownChannelError(`${channel}: payload 含非契约键 ${extra.join(", ")}`);
  }
  const ordered: Record<string, unknown> = {};
  for (const key of spec.payloadKeysInOrder) {
    if (Object.prototype.hasOwnProperty.call(values, key)) {
      ordered[key] = normalizePayload(values[key]);
    }
  }
  return ordered;
}
