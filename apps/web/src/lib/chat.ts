/**
 * Chat / SSE 纯函数工具（W7 / T1-32）。
 *
 * 职责：SSE 帧切分与解析（与后端 `apps/api/src/wbtime_ai_api/sse/encoder.py` 对齐）、
 * 时间线条目文案、社区沙箱强度明示文案（A-5）。**无副作用、无 React 依赖**，便于单测。
 */

import { isSseChannel, isTerminalChannel } from "@/types";
import type { ChatStreamEvent, SseChannel, TimelineEntry } from "@/types";

/**
 * 社区形态沙箱强度明示文案（A-5，设计 §2.10）。
 *
 * Community Local / Server（单容器）**仅** `LocalProcessSandboxProvider`，
 * 必须社区明示「进程级隔离（非容器级）」，不得对外宣称容器级隔离。
 */
export const SANDBOX_STRENGTH_NOTE = "沙箱强度：进程级隔离（非容器级）";

/** SSE 数据帧中 `data:` 的多行合并分隔符（对齐 EventSource 规范）。 */
const DATA_JOIN = "\n";

/** 将 `\r\n` / `\r` 归一化为 `\n`（容忍不同代理 / 平台的换行风格）。 */
function normalizeNewlines(raw: string): string {
  return raw.replace(/\r\n?/g, "\n");
}

/**
 * 从缓冲区中切出**完整** SSE 帧（以空行 `\n\n` 分隔）。
 *
 * 返回切出的帧数组与**剩余不完整**缓冲区（供下次 `read()` 继续累积）。
 * 该函数无状态，调用方持有 `rest` 即可正确处理网络分片。
 */
export function splitSseFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = normalizeNewlines(buffer);
  const boundary = normalized.lastIndexOf("\n\n");
  if (boundary === -1) {
    return { frames: [], rest: normalized };
  }
  const head = normalized.slice(0, boundary);
  const rest = normalized.slice(boundary + 2);
  const frames = head.split("\n\n").filter((frame) => frame.trim().length > 0);
  return { frames, rest };
}

/**
 * 解析单个 SSE 帧为 {@link ChatStreamEvent}。
 *
 * - 注释帧（以 `:` 开头，如心跳 `: hb <ms>`）→ 返回 `null`（忽略）；
 * - 无 `event:` 或通道名未映射（9 通道之外）→ 返回 `null`（前端契约稳定）；
 * - `id:` 解析为整数 `seq`（非整数按 `null` 处理，不污染 `Last-Event-ID`）；
 * - `data:` 多行按 `\n` 合并后 `JSON.parse`，失败 → 空对象（不中断流）。
 */
export function parseSseFrame(frame: string): ChatStreamEvent | null {
  let seq: number | null = null;
  let channel: string | null = null;
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.length === 0 || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("id:")) {
      const raw = line.slice(3).trim();
      const parsed = Number(raw);
      seq = Number.isFinite(parsed) && raw.length > 0 ? parsed : null;
    } else if (line.startsWith("event:")) {
      channel = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (channel === null || !isSseChannel(channel)) {
    return null;
  }

  let payload: Record<string, unknown> = {};
  if (dataLines.length > 0) {
    const joined = dataLines.join(DATA_JOIN).trim();
    if (joined.length > 0) {
      try {
        const parsed: unknown = JSON.parse(joined);
        if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
          payload = parsed as Record<string, unknown>;
        }
      } catch {
        payload = {};
      }
    }
  }

  return { seq, channel, payload };
}

/**
 * 生成时间线条目文案（设计 §2.14：`tool.started/completed` → "正在调用 … / 已完成 …"）。
 */
export function describeTimelineEntry(entry: TimelineEntry): string {
  const prefix = entry.kind === "mcp" ? "MCP " : "";
  if (entry.kind === "thinking") {
    return entry.status === "running" ? "思考中…" : "思考完成";
  }
  switch (entry.status) {
    case "running":
      return `正在调用 ${prefix}${entry.name}…`;
    case "completed":
      return `已完成 ${prefix}${entry.name}`;
    case "error":
      return `${prefix}${entry.name} 调用失败`;
    default:
      return `${prefix}${entry.name}`;
  }
}

/** 从任意未知值中安全取字符串字段（缺省返回 `null`）。 */
export function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** 从任意未知值中安全取对象字段（缺省返回 `undefined`）。 */
export function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return undefined;
}

/** 从任意未知值中安全取数字字段（缺省返回 `undefined`）。 */
export function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** 透传判定：通道是否为终态（`agent.completed` / `agent.error`）。 */
export function isTerminalEvent(channel: SseChannel): boolean {
  return isTerminalChannel(channel);
}
