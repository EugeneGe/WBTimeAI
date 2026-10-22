/**
 * T3-10 · `shell` 工具（**只在沙箱内执行**，禁 Host 直执行）。
 *
 * `command` 的两种形态（契约 `type: ["string","array"]`）
 * ---------------------------------------------------
 *   - 字符串 ⇒ 交给 `sh -c`（POSIX）/ `cmd /c`（Windows），**这是唯一经过 shell 的路径**，
 *     因此危险模式扫描必须在派发**之前**、对**整串**做；
 *   - 数组 ⇒ **直接 spawn**（不经 shell），`argv[0]` 是可执行文件。
 *     但扫描仍然对 `join(" ")` 后的整串做 —— 见 `command.ts` 的注释：
 *     拆成数组不该成为绕过黑名单的手段。
 *
 * 执行前必须命中三道闸（顺序不可换）
 * -------------------------------
 *   1. `checkCommand(...)` —— 黑名单（15 条）；
 *   2. `context.sandbox` / `context.session` 存在 —— 否则 `INTERNAL_ERROR`
 *      （**不回落**到本机直执行：那等于"没有沙箱就在宿主上跑"，是最危险的降级）；
 *   3. 沙箱 `exec` —— 唯一出口。
 *
 * 反例「命中本地规则 ⇒ 沙箱 exec 计数 == 0」（验收 ⑥）：第 1 道闸在 `exec` 之前，
 * 测试注入计数沙箱即可断死。
 */

import { checkCommand, CommandDeniedError } from "../guards/command.js";
import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";

/** Windows 下的 shell 包装（POSIX 用 `sh -c`）。 */
function shellOf(): { readonly file: string; readonly flag: string } {
  return process.platform === "win32"
    ? { file: "cmd.exe", flag: "/c" }
    : { file: "/bin/sh", flag: "-c" };
}

export const shellTool: BuiltinTool = {
  name: "shell",
  requiresSandbox: true,

  async execute(args: Readonly<Record<string, unknown>>, context: ToolContext): Promise<ToolOutcome> {
    const startedAt = Date.now();
    const command = args.command;

    if (typeof command !== "string" && !Array.isArray(command)) {
      return {
        ok: false,
        error: "command 必须是字符串或字符串数组",
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    // 闸 1：黑名单（对整串扫，数组形态也扫）
    try {
      checkCommand(command as string | readonly string[]);
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

    // 闸 2：没有沙箱就不执行（**不降级**到宿主）
    if (context.sandbox === undefined || context.session === undefined) {
      return {
        ok: false,
        error: "shell 需要沙箱会话（未注入则拒绝执行，绝不回落到宿主直执行）",
        errorCode: "INTERNAL_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    const argv =
      typeof command === "string"
        ? (() => {
            const shell = shellOf();
            return [shell.file, shell.flag, command];
          })()
        : command.map(String);

    // 闸 3：唯一执行出口
    const result = await context.sandbox.exec(context.session, argv, {
      ...(typeof args.timeout_ms === "number" ? { timeoutMs: args.timeout_ms } : {}),
      ...(context.timeoutMs === undefined ? {} : { timeoutMs: context.timeoutMs }),
    });

    if (result.timedOut) {
      return {
        ok: false,
        error: "命令执行超时",
        errorCode: "TOOL_TIMEOUT",
        durationMs: result.durationMs,
        sandboxSessionId: context.session.id,
        timedOut: true,
      };
    }
    if (result.exitCode !== 0) {
      return {
        ok: false,
        error: result.stderr === "" ? `命令退出码 ${String(result.exitCode)}` : result.stderr,
        errorCode: "INTERNAL_ERROR",
        exitCode: result.exitCode ?? undefined,
        durationMs: result.durationMs,
        sandboxSessionId: context.session.id,
      };
    }

    return {
      ok: true,
      output: { stdout: result.stdout, stderr: result.stderr, truncated: result.truncated },
      exitCode: result.exitCode ?? 0,
      durationMs: result.durationMs,
      sandboxSessionId: context.session.id,
    };
  },
};
