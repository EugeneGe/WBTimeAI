// @wbtime/api · Provider 工厂（T3-02）—— 真实厂商矩阵 + 假 Provider 的装配闸门。
//
// 只用 `@ai-sdk/*` 的**Provider 矩阵**，不碰 `ai` 包的 `streamText` / `generateText`
// （R3-10：执行语义由我们自己的 Harness 拥有，SDK 只在最底层出 token）。
// 底层调用面（实测 `@ai-sdk/provider@4.0.31`）：
//   `LanguageModelV4.doStream(opts) → { stream: ReadableStream<LanguageModelV4StreamPart> }`
//   分片：`{type:'text-delta', id, delta}` · `{type:'finish', usage, finishReason}` · `{type:'error', error}`
//
// 为什么不直接 import `@ai-sdk/provider` 的类型：它**不是** `apps/api` 的直接依赖
// （只有 4 个 `@ai-sdk/*` 厂商包 + `ai`），pnpm 的严格 node_modules 下会解析失败。
// 故这里用**结构化最小接口**（`RawLanguageModel`），既能编译，又不假装拥有别人的类型。

import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { ConfigError } from "@wbtime/config";
import type { ModelChunk, ModelMessage, ModelRequest, RunCallContext } from "@wbtime/domain";

import { ProviderError, toProviderError } from "../errors.js";
import { normalizeUsage, type NormalizedUsage } from "../usage.js";

/** 支持的 Provider 类型。 */
export const PROVIDER_KINDS = [
  "openai",
  "anthropic",
  "google",
  "openai-compatible",
  "fake",
] as const;

export type ProviderKind = (typeof PROVIDER_KINDS)[number];

/** Provider 适配器产出的分片（比端口 `ModelChunk` 多带归一后的 usage）。 */
export type ProviderChunk =
  | { readonly type: "text_delta"; readonly text: string }
  | { readonly type: "usage"; readonly usage: NormalizedUsage }
  | { readonly type: "finish"; readonly reason: string };

/** 适配器：一个具体厂商（或 fake）的流式出口。 */
export interface ProviderAdapter {
  readonly kind: ProviderKind;
  /** 落审计 / 观测用的 provider 名（fake 恒为 `"fake"`）。 */
  readonly providerName: string;
  stream(request: ModelRequest, context: RunCallContext): AsyncIterable<ProviderChunk>;
}

/** `doStream` 的最小结构化类型（刻意不 import 厂商包的类型）。 */
interface RawLanguageModel {
  doStream(options: Record<string, unknown>): PromiseLike<{ stream: ReadableStream<unknown> }>;
}

/** 厂商工厂的最小结构化类型：模型 id 在 SDK 里是**品牌联合类型**，运行期接受任意字符串。 */
interface RawProvider {
  languageModel(modelId: string): RawLanguageModel;
}

export interface ProviderFactoryOptions {
  readonly kind: ProviderKind;
  /** 显式 key；缺省读 `env` 里对应变量。 */
  readonly apiKey?: string;
  /** 兼容端点 baseURL（`openai-compatible` 必填）。 */
  readonly baseURL?: string;
  /** 环境变量源（便于测试注入，不动 `process.env`）。 */
  readonly env?: NodeJS.ProcessEnv;
  /** 是否允许 fake（缺省 false；工厂内部还会看 `env`）。 */
  readonly allowFakeProvider?: boolean;
  /** fake 的脚本化分片（仅 `kind==="fake"` 有效）。 */
  readonly fakeScript?: readonly ProviderChunk[];
}

/** 每个 kind 对应的 API key 环境变量。 */
export const PROVIDER_KEY_ENV: Readonly<
  Record<Exclude<ProviderKind, "fake" | "openai-compatible">, string>
> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_GENERATIVE_AI_API_KEY",
};

/** openai-compatible 的 key 约定（自建端点常留空，故单独处理）。 */
export const COMPATIBLE_KEY_ENV = "OPENAI_COMPATIBLE_API_KEY";

/** fake 的放行环境变量。 */
export const FAKE_PROVIDER_ENV = "WBTIME_AI_ALLOW_FAKE_PROVIDER";

/**
 * 断言当前允许装配 fake provider。
 *
 * @throws {ConfigError} 生产环境且未显式放行（`CONFIGURATION_ERROR`）。
 */
export function assertFakeProviderAllowed(
  env: NodeJS.ProcessEnv = process.env,
  allowFakeProvider = false,
): void {
  const byEnv = env.NODE_ENV === "test" || env[FAKE_PROVIDER_ENV] === "1";
  if (!byEnv && !allowFakeProvider) {
    throw new ConfigError(
      "fake provider 只允许在 NODE_ENV=test 或 WBTIME_AI_ALLOW_FAKE_PROVIDER=1 时装配（生产用假模型 = 伪造能力）",
      ["NODE_ENV", FAKE_PROVIDER_ENV],
    );
  }
}

/**
 * 把域层 `ModelMessage` 转成 AI SDK v4 的 prompt 结构。
 *
 * D-T302-1 已修复：`ModelMessage` 现在有可选 `toolName`（tool 结果）与 `toolCalls`
 * （assistant 请求），因此工具回路可以完整表达。占位 `"tool"` **只在调用方漏填时**
 * 作为兼容退路，真实回路必须填 —— 漏填会让上游认不出结果属于哪个工具。
 */
export function toPrompt(messages: readonly ModelMessage[]): unknown[] {
  return messages.map((message) => {
    if (message.role === "system") return { role: "system", content: message.content };

    if (message.role === "tool") {
      return {
        role: "tool",
        content: [
          {
            type: "tool-result",
            toolCallId: message.toolCallId ?? "unknown",
            toolName: message.toolName ?? "tool",
            result: message.content,
          },
        ],
      };
    }

    if (message.role === "assistant" && message.toolCalls !== undefined && message.toolCalls.length > 0) {
      // assistant 同时带文本与工具请求：文本是 reasoning/说明，工具请求是意图，
      // 两者必须同一条消息发出，否则上游会把工具调用当成无关上下文。
      const parts: unknown[] = [];
      if (message.content.length > 0) parts.push({ type: "text", text: message.content });
      for (const call of message.toolCalls) {
        parts.push({ type: "tool-call", toolCallId: call.id, toolName: call.name, input: call.input });
      }
      return { role: "assistant", content: parts };
    }

    return { role: message.role, content: [{ type: "text", text: message.content }] };
  });
}

/** 消费 V4 的 `ReadableStream`，转成我们的 `ProviderChunk`。 */
async function* consumeStream(
  stream: ReadableStream<unknown>,
  meta: { readonly provider: string; readonly model: string },
): AsyncGenerator<ProviderChunk> {
  const reader = stream.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const part = value as { type?: string; delta?: unknown; usage?: unknown; error?: unknown };
      switch (part.type) {
        case "text-delta":
          if (typeof part.delta === "string" && part.delta.length > 0) {
            yield { type: "text_delta", text: part.delta };
          }
          break;
        case "finish":
          yield { type: "usage", usage: normalizeUsage(part.usage) };
          yield { type: "finish", reason: "model_finish" };
          break;
        case "error":
          throw toProviderError(part.error, meta);
        default:
          // 其余分片（reasoning / tool-call / metadata）本版不消费，静默跳过。
          break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** 建真实 Provider 适配器。 */
function createSdkAdapter(
  kind: Exclude<ProviderKind, "fake">,
  options: ProviderFactoryOptions,
): ProviderAdapter {
  const env = options.env ?? process.env;
  const keyEnv = kind === "openai-compatible" ? COMPATIBLE_KEY_ENV : PROVIDER_KEY_ENV[kind];
  const apiKey = options.apiKey ?? env[keyEnv] ?? "";

  if (kind === "openai-compatible") {
    if (!options.baseURL) {
      throw new ConfigError("openai-compatible provider 必须给 baseURL", ["baseURL"]);
    }
  } else if (!apiKey) {
    throw new ConfigError(`未配置 ${keyEnv}（未配置 ≠ 降级：R3-19 要求 fail loud）`, [keyEnv]);
  }

  const provider: RawProvider =
    kind === "openai"
      ? (createOpenAI({ apiKey }) as unknown as RawProvider)
      : kind === "anthropic"
        ? (createAnthropic({ apiKey }) as unknown as RawProvider)
        : kind === "google"
          ? (createGoogleGenerativeAI({ apiKey }) as unknown as RawProvider)
          : (createOpenAICompatible({
              name: "openai-compatible",
              apiKey,
              baseURL: options.baseURL as string,
            }) as unknown as RawProvider);

  return {
    kind,
    providerName: kind,
    async *stream(request: ModelRequest, context: RunCallContext): AsyncIterable<ProviderChunk> {
      if (context.signal.aborted) {
        throw new ProviderError("请求已取消", {
          errorType: "timeout",
          provider: kind,
          model: request.model,
        });
      }
      try {
        const result = await provider.languageModel(request.model).doStream({
          prompt: toPrompt(request.messages),
          maxOutputTokens: request.maxOutputTokens,
          temperature: request.temperature,
          abortSignal: context.signal,
        });
        yield* consumeStream(result.stream, { provider: kind, model: request.model });
      } catch (error) {
        throw toProviderError(error, { provider: kind, model: request.model });
      }
    },
  };
}

/**
 * 建 Provider 适配器。
 *
 * `kind === "fake"` 时先过闸门，再交给 `createFakeProvider`（**动态 import**：
 * 避免 `fake-provider.ts` 与本文件形成运行时循环）。
 *
 * @throws {ConfigError} fake 被禁 / 缺 key / 兼容端点缺 baseURL。
 */
export async function createProviderAdapter(
  options: ProviderFactoryOptions,
): Promise<ProviderAdapter> {
  if (options.kind === "fake") {
    assertFakeProviderAllowed(options.env ?? process.env, options.allowFakeProvider ?? false);
    const { createFakeProvider } = await import("../fake-provider.js");
    return createFakeProvider({ script: options.fakeScript });
  }
  return createSdkAdapter(options.kind, options);
}

/** 端口分片转换：`ProviderChunk` → `ModelChunk`（usage 命名在这里对齐契约）。 */
export function toModelChunk(chunk: ProviderChunk): ModelChunk {
  if (chunk.type === "text_delta") return { type: "text_delta", text: chunk.text };
  if (chunk.type === "finish") return { type: "finish", reason: chunk.reason };
  const usage = chunk.usage;
  const tokensIn = usage.prompt_tokens ?? 0;
  const tokensOut = usage.completion_tokens ?? 0;
  return usage.cache_read_tokens === undefined
    ? { type: "usage", tokensIn, tokensOut }
    : { type: "usage", tokensIn, tokensOut, cacheReadTokens: usage.cache_read_tokens };
}
