/**
 * T3-10 · 危险命令拦截（py `_DANGEROUS_COMMAND_PATTERNS` / `_DANGEROUS_GIT_PATTERNS` 复刻）。
 *
 * 15 + 5 条模式，逐条带理由
 * ----------------------
 *   模式表**照抄 py**（顺序也是：先命中先报）。这不是"能想到的都加上"的问题 ——
 *   表里每一条都对应一次真实事故类型（删根、fork 炸弹、格盘、关机、裸写设备、
 *   删库、清表、提权、命名空间逃逸、特权容器、挂 docker.sock、命令替换注入）。
 *
 * 为什么是"黑名单正则"而不是"命令白名单"
 * ----------------------------------
 *   `shell` 工具的契约是"在沙箱内执行命令"，用户要跑的东西无法预先枚举
 *   （`ls` / `pytest` / `npm test` / 自定义脚本…）。白名单会让工具变成"只能跑三条命令"，
 *   等于没实现。所以本层是**兜底**：挡住"无论什么场景都不该在 AI 沙箱里发生"的动作，
 *   真正的隔离由沙箱（`LocalProcessSandbox`）的 cwd 限制与超时承担。
 *
 *   ⚠️ 因此**不要**把本文件当成"安全沙箱"。它能挡的是"一句话就能造成的灾难"，
 *   挡不住"精心构造的提权链"。后者靠容器 / 非 root / 只读挂载 —— 那是部署面的事
 *   （已登记为遗留）。
 */

/** 命中危险模式（`PERMISSION_DENIED`）。 */
export class CommandDeniedError extends Error {
  readonly name = "CommandDeniedError";
  readonly code = "PERMISSION_DENIED";
  readonly reason: string;
  readonly subject: string;
  readonly data: Readonly<Record<string, unknown>>;

  constructor(reason: string, subject: string, data: Record<string, unknown> = {}) {
    super(reason);
    this.reason = reason;
    this.subject = subject;
    this.data = data;
  }
}

/** 危险命令模式（15 条，与 py 逐字）。 */
export const DANGEROUS_COMMAND_PATTERNS: readonly (readonly [RegExp, string])[] = Object.freeze([
  [/\brm\s+-[a-z]*r[a-z]*f?\s+\/(?:\s|$)/i, "禁止递归删除根目录"],
  [/\brm\s+-[a-z]*f[a-z]*r?\s+\/(?:\s|$)/i, "禁止递归删除根目录"],
  [/\brm\s+-[a-z]*r[a-z]*f?\s+~(?:\s|$)/i, "禁止递归删除用户目录"],
  [/:\s*\(\s*\)\s*\{.*\};\s*:/i, "禁止 fork 炸弹"],
  [/\bmkfs(\.\w+)?\b/i, "禁止格式化文件系统"],
  [/\b(?:shutdown|reboot|halt|poweroff)\b/i, "禁止关机 / 重启"],
  [/\bdd\b[^\n]*\bof=\/dev\//i, "禁止裸写块设备"],
  [/\bdrop\s+database\b/i, "禁止删除数据库"],
  [/\btruncate\s+table\b/i, "禁止清空数据表"],
  [/\bsudo\b/i, "禁止提权"],
  [/\bnsenter\b/i, "禁止命名空间逃逸"],
  [/--privileged\b/i, "禁止特权容器"],
  [/docker\.sock/i, "禁止挂载宿主 docker.sock"],
  [/`[^`]*`/i, "禁止反引号命令替换注入"],
  [/\$\(/i, "禁止 $() 命令替换注入"],
] as const);

/** 危险 git 模式（5 条）。 */
export const DANGEROUS_GIT_PATTERNS: readonly (readonly [RegExp, string])[] = Object.freeze([
  [/\bpush\b.*(?:--force\b|-f\b)/i, "禁止强推（force push）"],
  [/\breset\b.*--hard\b/i, "禁止 git reset --hard"],
  [/\bremote\s+set-url\b.*@/i, "禁止在 remote 中内嵌凭证"],
  [/\bconfig\b.*credential\.helper\b/i, "禁止写入凭证 helper"],
  [/\bfilter-branch\b/i, "禁止重写历史"],
] as const);

/**
 * 校验 shell 命令（字符串或 argv 数组）。
 *
 * argv 数组会被 `join(" ")` 后再扫 —— 这条**故意**的宽松：把 argv 拆开写
 * （`["rm","-rf","/"]`）与写成一整串（`"rm -rf /"`）必须被同一张表挡住，
 * 否则攻击者只要换成数组形式就绕过了。
 *
 * @throws {CommandDeniedError}
 */
export function checkCommand(command: string | readonly string[]): void {
  const text = typeof command === "string" ? command : command.map(String).join(" ");
  scan(text, DANGEROUS_COMMAND_PATTERNS, "shell", text);
}

/**
 * 校验 git 子命令（只扫 args，不含 `"git"` 本身）。
 *
 * @throws {CommandDeniedError}
 */
export function checkGitCommand(args: readonly string[]): void {
  const text = args.map(String).join(" ");
  scan(text, DANGEROUS_GIT_PATTERNS, "git", text);
}

/** 共用扫描：命中即抛。 */
function scan(
  text: string,
  patterns: readonly (readonly [RegExp, string])[],
  subject: string,
  payload: string
): void {
  for (const [pattern, reason] of patterns) {
    if (pattern.test(text)) {
      throw new CommandDeniedError(reason, subject, { payload });
    }
  }
}
