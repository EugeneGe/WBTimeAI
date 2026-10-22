/**
 * T3-10 · `LocalProcessSandbox` —— 本机子进程沙箱（V0.3.0 的唯一实现）。
 *
 * 它**不是**容器
 * ------------
 *   隔离只有三条：**workdir 限定**（cwd 指向会话目录）、**超时**（`exec` 的
 *   `timeoutMs`）、**环境最小化**（不继承 `process.env`，只给 `PATH` / `HOME` / `LANG`）。
 *   它挡不住"提权链"——那要靠容器 / 非 root / 只读挂载（部署面，已登记遗留）。
 *   它能挡的是：跑飞了的进程（超时杀掉）、把整机环境变量带进输出（环境最小化）、
 *   输出把内存打爆（截断到 200000 字符）。
 *
 * 为什么环境要**白名单**而不是"删几个敏感变量"
 * ----------------------------------------
 *   `process.env` 里有 `DATABASE_URL` / 各种 token / 云凭证。黑名单永远漏，
 *   所以只放行三个：`PATH`（找不到解释器就跑不了）、`HOME`（pip/npm 要用）、
 *   `LANG`（避免编码炸）。其余一律不带 —— `WBTIME_AI_SECRET_KEY` 因此天然进不去。
 *
 * 进程组与超时
 * ----------
 *   超时时 `child.kill()` 只杀主进程，**孙进程会活下来**（`sh -c "sleep 100"` 的
 *   `sleep` 就是孙进程）。本实现用 `detached: true` 建独立进程组，超时时
 *   `process.kill(-pid)` 杀整组 —— 否则一次超时会在机器上留一串僵尸。
 */

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";

import {
  truncateOutput,
  type ExecOptions,
  type ExecResult,
  type SandboxProvider,
  type SandboxSession,
} from "./types.js";

/** 缺省超时（毫秒）。py `DEFAULT_TOOL_TIMEOUT_MS` 同量级。 */
export const DEFAULT_SANDBOX_TIMEOUT_MS = 30_000;

/** 环境变量**白名单**（见文件头注：黑名单永远漏）。 */
const ENV_ALLOWLIST = ["PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP"] as const;

/** `LocalProcessSandbox` 选项。 */
export interface LocalProcessSandboxOptions {
  /** 缺省超时（缺省 {@link DEFAULT_SANDBOX_TIMEOUT_MS}）。 */
  readonly defaultTimeoutMs?: number;
  /** 额外放行的环境变量名（**显式**列举；缺省空）。 */
  readonly extraEnvKeys?: readonly string[];
  /** 会话登记回调（落 `sandbox_session` 行；测试可注入记录器）。 */
  readonly onSessionCreated?: (session: SandboxSession) => void | Promise<void>;
  /** 会话销毁回调（写 `ended_at`）。 */
  readonly onSessionDestroyed?: (session: SandboxSession, endedAt: Date) => void | Promise<void>;
  /** 时钟（测试注入）。 */
  readonly now?: () => Date;
}

/**
 * 本机子进程沙箱。
 *
 * 会话只有 `{id, workdir}` 两个字段 —— 本实现里没有"长期进程"，每次 `exec` 都是
 * 一次新的 spawn。所以 `destroy` 的语义是"标记结束"（落 `ended_at`），不改进程状态。
 */
export class LocalProcessSandbox implements SandboxProvider {
  readonly #defaultTimeoutMs: number;
  readonly #extraEnvKeys: readonly string[];
  readonly #onCreated?: (session: SandboxSession) => void | Promise<void>;
  readonly #onDestroyed?: (session: SandboxSession, endedAt: Date) => void | Promise<void>;
  readonly #now: () => Date;
  /** 已销毁的会话（幂等判据）。 */
  readonly #destroyed = new Set<string>();

  constructor(options: LocalProcessSandboxOptions = {}) {
    this.#defaultTimeoutMs = options.defaultTimeoutMs ?? DEFAULT_SANDBOX_TIMEOUT_MS;
    this.#extraEnvKeys = options.extraEnvKeys ?? [];
    if (options.onSessionCreated !== undefined) this.#onCreated = options.onSessionCreated;
    if (options.onSessionDestroyed !== undefined) this.#onDestroyed = options.onSessionDestroyed;
    this.#now = options.now ?? (() => new Date());
  }

  async createSession(workdir: string): Promise<SandboxSession> {
    const session: SandboxSession = Object.freeze({ id: randomUUID(), workdir });
    await this.#onCreated?.(session);
    return session;
  }

  /**
   * 执行一次命令。
   *
   * @param session 会话（`cwd` 的缺省值来自它的 `workdir`）。
   * @param argv `argv[0]` 是可执行文件，其余是参数 —— **不经过 shell**（避免注入）。
   * @param options 见 `ExecOptions`。
   */
  async exec(
    session: SandboxSession,
    argv: readonly string[],
    options: ExecOptions = {}
  ): Promise<ExecResult> {
    if (argv.length === 0) {
      return Object.freeze({
        stdout: "",
        stderr: "空命令（argv 长度为 0）",
        exitCode: null,
        timedOut: false,
        durationMs: 0,
        truncated: false,
      });
    }
    if (this.#destroyed.has(session.id)) {
      return Object.freeze({
        stdout: "",
        stderr: `沙箱会话 ${session.id} 已销毁，不可复用`,
        exitCode: null,
        timedOut: false,
        durationMs: 0,
        truncated: false,
      });
    }

    const timeoutMs = options.timeoutMs ?? this.#defaultTimeoutMs;
    const cwd = options.cwd ?? session.workdir;
    const startedAt = Date.now();

    const child = spawn(argv[0], argv.slice(1), {
      cwd,
      env: this.#buildEnv(options.env),
      // 独立进程组：超时时可以整组杀掉（见文件头注）。
      detached: process.platform !== "win32",
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });

    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin);
    }
    child.stdin.end();

    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child.pid);
    }, timeoutMs);

    const exitCode = await new Promise<number | null>((resolve) => {
      child.on("close", (code) => resolve(code));
      child.on("error", (error) => {
        stderr += error.message;
        resolve(null);
      });
    });
    clearTimeout(timer);

    const durationMs = Date.now() - startedAt;
    const out = truncateOutput(stdout);
    const err = truncateOutput(stderr);

    return Object.freeze({
      stdout: out.text,
      stderr: err.text,
      exitCode: timedOut ? null : exitCode,
      timedOut,
      durationMs,
      truncated: out.truncated || err.truncated,
    });
  }

  /** 销毁会话（**幂等**：第二次是 no-op，不改 `ended_at`）。 */
  async destroy(session: SandboxSession): Promise<void> {
    if (this.#destroyed.has(session.id)) return;
    this.#destroyed.add(session.id);
    await this.#onDestroyed?.(session, this.#now());
  }

  /** 已销毁的会话 id（测试断言用）。 */
  isDestroyed(session: SandboxSession): boolean {
    return this.#destroyed.has(session.id);
  }

  /** 构造最小环境（白名单 + 显式追加项）。 */
  #buildEnv(extra: Readonly<Record<string, string>> | undefined): Record<string, string> {
    const env: Record<string, string> = {};
    for (const key of [...ENV_ALLOWLIST, ...this.#extraEnvKeys]) {
      const value = process.env[key];
      if (value !== undefined) env[key] = value;
    }
    if (extra !== undefined) Object.assign(env, extra);
    return env;
  }
}

/**
 * 杀整个进程组（超时用）。
 *
 * `process.kill(-pid)` 在 POSIX 上杀整组；Windows 没有进程组语义，退回 `child.kill()`。
 * 失败一律吞掉 —— 清理失败不该把"超时已判定"这个事实盖掉。
 */
function killTree(pid: number | undefined): void {
  if (pid === undefined) return;
  try {
    if (process.platform === "win32") {
      process.kill(pid);
    } else {
      process.kill(-pid, "SIGKILL");
    }
  } catch {
    // 进程已退出 / 无权限：忽略。
  }
}
