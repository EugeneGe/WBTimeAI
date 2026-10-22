/**
 * T3-10 · 工具注册表（5 个内置工具的唯一入口）。
 *
 * 与 `packages/db` 的 `BUILTIN_TOOLS` 是什么关系
 * ------------------------------------------
 *   `packages/db` 那份是 **`input_schema` 的唯一真源**（R3-23 ①），它决定"工具表里
 *   写什么"与"`GET /tools` 返回什么"。本文件是**可执行实现**的注册表：工具名 → 实现。
 *   两者的 `name` 集合必须**逐字相同**，由 `builtin-tools.test.mjs` 的 A-1 断言
 *   （从 `BUILTIN_TOOLS` 取名单，与本文件的 keys 比对）—— 单边加一个工具会立刻红。
 *
 * `ToolContext` 里为什么有 `sandbox` 与 `session`
 * -------------------------------------------
 *   需要沙箱的工具（`git` / `shell` / `code_exec`）拿到的是**端口**而不是具体实现，
 *   所以测试可以注入 fake 沙箱并断言"命中本地规则时 `exec` 计数 == 0"（验收 ⑥）。
 *   若工具里直接 `spawn`，这条断言在类型层就写不出来。
 */

import { codeExecTool } from "./builtin/code-exec.js";
import { filesystemTool } from "./builtin/filesystem.js";
import { gitTool } from "./builtin/git.js";
import { httpTool } from "./builtin/http.js";
import { shellTool } from "./builtin/shell.js";

import type { SandboxProvider, SandboxSession } from "../sandbox/types.js";
import type { HostResolver } from "./guards/ssrf.js";

/** 一次工具执行的上下文（由 `ToolExecutor` 从 `RunCallContext` 派生）。 */
export interface ToolContext {
  /** Workspace 根（`filesystem` 的相对路径基准；越界一律拒）。 */
  readonly workspaceRoot: string;
  /** scope 白名单（空 / 缺省 = 不限）。 */
  readonly allowedPaths?: readonly string[];
  /** 沙箱端口（需沙箱的工具必填）。 */
  readonly sandbox?: SandboxProvider;
  /** 沙箱会话（需沙箱的工具必填）。 */
  readonly session?: SandboxSession;
  /** 出网白名单（`http` 用；空 = 拒绝全部）。 */
  readonly egressAllowlist?: readonly string[];
  /** 域名解析器（测试注入，用于 DNS rebinding 用例）。 */
  readonly resolver?: HostResolver;
  /** 单次执行超时（缺省由沙箱决定）。 */
  readonly timeoutMs?: number;
}

/** 工具执行结果（比 `ToolExecutionResult` 更细：带 output / exitCode）。 */
export interface ToolOutcome {
  readonly ok: boolean;
  readonly output?: unknown;
  readonly error?: string;
  /** `PERMISSION_DENIED` / `VALIDATION_ERROR` / `INTERNAL_ERROR` / `TOOL_TIMEOUT`。 */
  readonly errorCode?: string;
  readonly exitCode?: number;
  readonly durationMs: number;
  readonly sandboxSessionId?: string;
  readonly timedOut?: boolean;
}

/** 一个内置工具的实现。 */
export interface BuiltinTool {
  readonly name: string;
  readonly requiresSandbox: boolean;
  execute(args: Readonly<Record<string, unknown>>, context: ToolContext): Promise<ToolOutcome>;
}

/**
 * 5 个内置工具（**顺序 == `BUILTIN_TOOLS` 的顺序**，便于人眼比对）。
 *
 * `Map` 而不是对象：工具名是外部输入，`Map` 不会因为 `__proto__` 之类的键名产生
 * 原型链查询（对象字面量会）。
 */
export const BUILTIN_REGISTRY: ReadonlyMap<string, BuiltinTool> = new Map(
  [filesystemTool, gitTool, httpTool, shellTool, codeExecTool].map((tool) => [tool.name, tool])
);

/** 取工具实现；未注册 ⇒ `undefined`（由 executor 折成 `FAILED`）。 */
export function resolveTool(name: string): BuiltinTool | undefined {
  return BUILTIN_REGISTRY.get(name);
}

/** 已注册的工具名（升序；测试用）。 */
export function registeredToolNames(): string[] {
  return [...BUILTIN_REGISTRY.keys()].sort();
}

/** 需要沙箱的工具名（供装配期校验"该给沙箱的给了没有"）。 */
export function sandboxedToolNames(): string[] {
  return [...BUILTIN_REGISTRY.values()].filter((tool) => tool.requiresSandbox).map((tool) => tool.name).sort();
}
