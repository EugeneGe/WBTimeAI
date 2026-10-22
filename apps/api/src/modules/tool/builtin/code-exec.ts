/**
 * T3-10 · `code_exec` 工具（**`runtime` 泛化 py 的 `python`**，DoD#5 / R3-18）。
 *
 * 与 py `python` 工具的关系（DoD#3 的判据）
 * ------------------------------------
 *   `input_schema` = py 的 `{code, timeout_ms}` **加一个 `runtime` 三值枚举**
 *   （`python | node | bash`，缺省 `python`）。其余逐字相同：`required: ["code"]`、
 *   `additionalProperties: false`。schema 由 `packages/db` 的 `BUILTIN_TOOLS` 持有，
 *   本文件只管执行。
 *
 * 三档 runtime 怎么落地
 * -------------------
 *   | runtime | argv |
 *   |---|---|
 *   | `python`（缺省） | `[pythonExe, "-c", code]` |
 *   | `node` | `[nodeExe, "-e", code]` |
 *   | `bash` | `[bashExe, "-c", code]` |
 *
 *   **不是空壳**：三档都能真跑（反例「`runtime=node/bash` 完全空壳 ⇒ happy-path 必红」
 *   由 `code-exec-equivalence` 的三条 happy-path 钉住）。
 *   解释器路径在构造时可注入（测试用 `process.execPath` / 系统 `python3`）。
 *
 * 为什么 Python 档要过 `checkPythonCode`
 * -----------------------------------
 *   py 的 `python` 工具在 exec 之前调 `check_python_code`。`node` / `bash` 档不过这张表
 *   （表里是 Python 语法，对 JS / Shell 无意义），**但它们过 `checkCommand`**
 *   —— 因为 bash 档本身就是一条 shell 命令。
 *
 * 超时与输出
 * --------
 *   超时 ⇒ `TOOL_TIMEOUT`（与 py 同码）；输出截断到 `MAX_OUTPUT_CHARS = 200000`
 *   （**锁死项**，见 `sandbox/types.ts`）。截断标记随结果返回（`truncated`）。
 */

import { CommandDeniedError, checkCommand } from "../guards/command.js";
import { checkPythonCode } from "../guards/python.js";
import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";

/** 三档 runtime 的契约值。 */
export const CODE_EXEC_RUNTIMES = ["python", "node", "bash"] as const;
export type CodeExecRuntime = (typeof CODE_EXEC_RUNTIMES)[number];

/** 缺省超时（毫秒；`code_exec` 比 shell 更可能跑得久）。 */
export const DEFAULT_CODE_EXEC_TIMEOUT_MS = 30_000;

/** 解释器解析（构造时注入，测试可换）。 */
export interface CodeExecInterpreters {
  readonly python: string;
  readonly node: string;
  readonly bash: string;
}

/**
 * 缺省解释器。
 *
 * `python` 取 `PYTHON` / `WBTIME_CODEEXEC_PYTHON` 环境变量，否则 `python3`（POSIX）
 * / `python`（Windows）。**不从 PATH 猜**：`python` 在多数 Linux 上是 Python 2，
 * 猜错会让"语法正确但行为不同"的代码静默跑偏。
 */
export function defaultInterpreters(): CodeExecInterpreters {
  const isWin = process.platform === "win32";
  return {
    python: process.env.WBTIME_CODEEXEC_PYTHON ?? process.env.PYTHON ?? (isWin ? "python" : "python3"),
    node: process.execPath,
    bash: isWin ? "bash.exe" : "/bin/bash",
  };
}

/** 建 `code_exec` 工具（解释器可注入）。 */
export function createCodeExecTool(interpreters: CodeExecInterpreters = defaultInterpreters()): BuiltinTool {
  return {
    name: "code_exec",
    requiresSandbox: true,

    async execute(
      args: Readonly<Record<string, unknown>>,
      context: ToolContext
    ): Promise<ToolOutcome> {
      const startedAt = Date.now();
      const code = args.code;

      if (typeof code !== "string" || code.length === 0) {
        return {
          ok: false,
          error: "code 必须是非空字符串",
          errorCode: "VALIDATION_ERROR",
          durationMs: Date.now() - startedAt,
        };
      }

      const runtime = (args.runtime === undefined ? "python" : String(args.runtime)) as CodeExecRuntime;
      if (!(CODE_EXEC_RUNTIMES as readonly string[]).includes(runtime)) {
        return {
          ok: false,
          error: `未知 runtime ${JSON.stringify(args.runtime)}（允许：${CODE_EXEC_RUNTIMES.join(" / ")}）`,
          errorCode: "VALIDATION_ERROR",
          durationMs: Date.now() - startedAt,
        };
      }

      // 闸 1：本地规则（Python 档过代码表；bash 档过命令表；三档都过命令表兜底）
      try {
        if (runtime === "python") {
          checkPythonCode(code);
        }
        if (runtime === "bash") {
          checkCommand(code);
        }
      } catch (error) {
        if (error instanceof CommandDeniedError) {
          return {
            ok: false,
            error: error.message,
            errorCode: "PERMISSION_DENIED",
            durationMs: Date.now() - startedAt,
          };
        }
        throw error;
      }

      // 闸 2：没有沙箱就不执行
      if (context.sandbox === undefined || context.session === undefined) {
        return {
          ok: false,
          error: "code_exec 需要沙箱会话（未注入则拒绝执行）",
          errorCode: "INTERNAL_ERROR",
          durationMs: Date.now() - startedAt,
        };
      }

      const argv = buildArgv(runtime, code, interpreters);

      // 超时（AUD-04）：**模型只能收紧，不能放宽**。
      //   ① `timeout_ms` 非有限数或 `<= 0` ⇒ `VALIDATION_ERROR`（**不静默回落默认值**：
      //      静默回落会让"我传了 0 想立刻超时"与"我没传"变成同一个行为，且掩盖调用方 bug）；
      //   ② 有效值 = `min(请求值, context.timeoutMs)`；请求值缺省即 `context.timeoutMs`
      //      （执行器算好的「run 剩余时间 ∩ 执行器默认值」）。
      const requestedTimeout = readTimeoutMs(args.timeout_ms);
      if (requestedTimeout === "invalid") {
        return {
          ok: false,
          error: `timeout_ms 必须是正的有限数（实测 ${JSON.stringify(args.timeout_ms)}）`,
          errorCode: "VALIDATION_ERROR",
          durationMs: Date.now() - startedAt,
        };
      }
      const timeoutMs = capTimeoutMs(requestedTimeout, context.timeoutMs, DEFAULT_CODE_EXEC_TIMEOUT_MS);

      // 闸 3：唯一执行出口
      const result = await context.sandbox.exec(context.session, argv, { timeoutMs, cwd: context.session.workdir });

      if (result.timedOut) {
        return {
          ok: false,
          error: "代码执行超时",
          errorCode: "TOOL_TIMEOUT",
          durationMs: result.durationMs,
          sandboxSessionId: context.session.id,
          timedOut: true,
        };
      }
      if (result.exitCode !== 0) {
        return {
          ok: false,
          error: result.stderr === "" ? `代码退出码 ${String(result.exitCode)}` : result.stderr,
          errorCode: "INTERNAL_ERROR",
          exitCode: result.exitCode ?? undefined,
          durationMs: result.durationMs,
          sandboxSessionId: context.session.id,
        };
      }

      return {
        ok: true,
        output: {
          runtime,
          stdout: result.stdout,
          stderr: result.stderr,
          truncated: result.truncated,
        },
        exitCode: result.exitCode ?? 0,
        durationMs: result.durationMs,
        sandboxSessionId: context.session.id,
      };
    },
  };
}

/** 按 runtime 组装 argv（`-c` / `-e` / `-c`）。 */
function buildArgv(
  runtime: CodeExecRuntime,
  code: string,
  interpreters: CodeExecInterpreters
): string[] {
  switch (runtime) {
    case "python":
      return [interpreters.python, "-c", code];
    case "node":
      return [interpreters.node, "-e", code];
    case "bash":
      return [interpreters.bash, "-c", code];
  }
}

/**
 * 读 `timeout_ms`（契约 `integer`，但模型可能给 `"abc"` / `0` / `-1` / `1e400`）。
 *
 * @returns `undefined`（未传 ⇒ 用上下文给的上限）/ 数字（已校验为正的有限数）/ `"invalid"`。
 */
function readTimeoutMs(value: unknown): number | undefined | "invalid" {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return "invalid";
  return value;
}

/**
 * 有效超时 = `min(请求值, 上下文上限)`（`shell` 同源，见 `builtin/shell.ts` 的同名函数）。
 *
 * 两个来源都可能缺省：请求值缺省 ⇒ 用上下文上限；上下文上限缺省（单测 / 非 run 侧调用）
 * ⇒ 回落工具默认值。**先取候选值，再用上限收紧** —— 顺序反了（先 min 再回落）会让
 * "上限缺省"退化成 `Infinity`，模型于是又能传一年的超时。
 */
export function capTimeoutMs(
  requested: number | undefined,
  ceiling: number | undefined,
  fallback: number
): number {
  const candidate = requested ?? ceiling ?? fallback;
  return ceiling === undefined ? candidate : Math.min(candidate, ceiling);
}

/** 缺省实例（装配期直接用；测试用 `createCodeExecTool` 注入解释器）。 */
export const codeExecTool: BuiltinTool = createCodeExecTool();
