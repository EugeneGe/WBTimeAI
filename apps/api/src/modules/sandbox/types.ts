/**
 * T3-10 · 沙箱端口（**唯一执行出口**）。
 *
 * 为什么要有这一层而不是直接 `child_process`
 * --------------------------------------
 *   1. **可替换**：本版是 `LocalProcessSandbox`（本机子进程），V0.7.0 要换成容器。
 *      没有端口，"换实现"就要改五个工具；
 *   2. **可测**：测试可以注入 fake 沙箱，断言"命中本地规则时 exec 计数 == 0"
 *      （卡面验收 ⑥）—— 若工具里直接 `spawn`，这条断言根本无法表达；
 *   3. **单一出口**：核心原则 ⑪「沙箱是唯一执行出口」。任何工具想跑进程，只能经它。
 *
 * `MAX_OUTPUT_CHARS` 是**锁死项**
 * ---------------------------
 *   `200000` 是 DoD#5 的等价判据之一（与 py 同值）。改它 = 放弃 `code_exec` 跨线等价，
 *   所以它在这里是**常量而不是配置**（没有构造参数、没有环境变量覆盖）。
 */

/** 输出上限（字符）。**锁死**，见文件头注。 */
export const MAX_OUTPUT_CHARS = 200_000;

/** 沙箱会话（一次 run 一个；`destroy` 后不可复用）。 */
export interface SandboxSession {
  readonly id: string;
  /** 该会话的工作目录（工具的相对路径基准）。 */
  readonly workdir: string;
}

/** 执行选项。 */
export interface ExecOptions {
  /** 超时（毫秒）。超时 ⇒ `timedOut=true` 且 `exitCode` 为 `null`。 */
  readonly timeoutMs?: number;
  /** 工作目录（缺省会话 workdir）。 */
  readonly cwd?: string;
  /**
   * 追加环境变量。
   *
   * ⚠️ 实现**必须**在最小环境上追加（只带 `PATH` / `HOME` 之类的必要项），
   * 不能直接继承 `process.env` —— 否则 `WBTIME_AI_SECRET_KEY` 会随环境漏进沙箱。
   */
  readonly env?: Readonly<Record<string, string>>;
  /** 标准输入（可选）。 */
  readonly stdin?: string;
}

/** 执行结果。 */
export interface ExecResult {
  readonly stdout: string;
  readonly stderr: string;
  /** 退出码；超时 / 被信号杀死时为 `null`。 */
  readonly exitCode: number | null;
  readonly timedOut: boolean;
  readonly durationMs: number;
  /** 输出是否被截断到 {@link MAX_OUTPUT_CHARS}。 */
  readonly truncated: boolean;
}

/** 沙箱端口。 */
export interface SandboxProvider {
  /** 建会话（幂等：同一 workdir 可建多个会话，各自独立 id）。 */
  createSession(workdir: string): Promise<SandboxSession>;
  /** 执行（**唯一出口**）。 */
  exec(session: SandboxSession, argv: readonly string[], options?: ExecOptions): Promise<ExecResult>;
  /**
   * 销毁会话（**幂等**：重复调用不抛，第二次是 no-op）。
   *
   * 落库口径（`sandbox_session` 表）：`destroy` 写 `ended_at`，重复调用不改写已有值。
   */
  destroy(session: SandboxSession): Promise<void>;
}

/** 截断到上限（保留尾部 —— 报错通常在最后几行）。 */
export function truncateOutput(text: string): { text: string; truncated: boolean } {
  if (text.length <= MAX_OUTPUT_CHARS) return { text, truncated: false };
  // 保留尾部：`code_exec` 的失败信息几乎总在最后（traceback 在末尾）。
  return { text: text.slice(text.length - MAX_OUTPUT_CHARS), truncated: true };
}
