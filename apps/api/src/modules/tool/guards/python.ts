/**
 * T3-10 · 代码片段拦截（py `_DANGEROUS_PYTHON_PATTERNS` 复刻，**六条**）。
 *
 * 为什么 `python` 工具需要自己的表，而不复用 `shell` 的那张
 * ------------------------------------------------
 *   因为代码是以"字符串"形式送进解释器的，`shell` 表里的 `rm -rf /` 在 Python 里
 *   根本不会出现（要删根目录写的是 `shutil.rmtree("/")`）。两张表的**动作语义相同，
 *   语法形态不同** —— 复用一张表等于两边都漏。
 *
 * 六条与它们各自挡住的事
 * -------------------
 *   1. `shutil.rmtree("/")` —— 删根；
 *   2. `os.remove("/etc/...")` / `os.remove("/root/...")` —— 删系统文件；
 *   3. `drop database` —— 嵌入式 SQL 删库；
 *   4. `truncate table` —— 清表；
 *   5. `WBTIME_AI_SECRET_KEY` —— **读 / 落盘宿主密钥**（D-17）。这条最容易被忽略：
 *      沙箱进程与 API 进程同机，环境变量可能被继承 —— 一旦模型能写出这个变量名，
 *      它就能把主密钥打进 stdout 再经工具输出带回对话；
 *   6. `subprocess` / `os.system` / `os.popen` —— **在沙箱代码内直调宿主进程**。
 *      沙箱本身就是为了"把执行关进笼子"，允许代码自己 spawn 等于把笼子门打开。
 *
 * 局限（必须知道）
 * -------------
 *   这是正则黑名单，绕过方式存在（字符串拼接、`__import__("shutil")`、base64）。
 *   它挡的是"模型直接写出来的危险调用"（这恰恰是最常见的形态：模型不会刻意混淆），
 *   真正的隔离边界是**沙箱进程**（cwd 限定 + 超时 + 环境变量最小化）。
 *   已登记为遗留：容器级隔离归部署面。
 */

import { CommandDeniedError } from "./command.js";

/** 危险 Python 代码模式（6 条，与 py 逐字）。 */
export const DANGEROUS_PYTHON_PATTERNS: readonly (readonly [RegExp, string])[] = Object.freeze([
  [/shutil\.rmtree\(\s*['"]\/(?:\s|['"])/i, "禁止删除根目录"],
  [/os\.remove\(\s*['"]\/(?:etc|root)\//i, "禁止删除系统目录文件"],
  [/\bdrop\s+database\b/i, "禁止删除数据库"],
  [/\btruncate\s+table\b/i, "禁止清空数据表"],
  [/WBTIME_AI_SECRET_KEY/i, "禁止读取 / 落盘宿主密钥（D-17）"],
  [/subprocess|os\.system|os\.popen/i, "禁止在沙箱代码内直调宿主进程"],
] as const);

/**
 * 校验 Python 代码片段。
 *
 * @param code 代码文本。
 * @throws {CommandDeniedError} 命中任一模式（`subject="python"`）。
 */
export function checkPythonCode(code: string): void {
  for (const [pattern, reason] of DANGEROUS_PYTHON_PATTERNS) {
    if (pattern.test(code)) {
      throw new CommandDeniedError(reason, "python", { payload: code });
    }
  }
}
