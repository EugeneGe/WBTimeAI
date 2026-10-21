/**
 * M-04 · `scanSensitive` —— 市场包「明文凭据」静态启发式扫描。
 *
 * 迁移来源（**唯一语义来源**）
 * --------------------------
 * `WBTimeAI_old/packages/plugin/src/wbtime_ai_plugin/marketplace/import_.py`
 * 第 108–200 行（`SENSITIVE_KEY_PATTERN` / `TOKEN_VALUE_PATTERNS` / 高熵判定 /
 * 占位符 / 引用前缀 / `_value_finding` / `scan_sensitive`）。
 *
 * 本文件是**逐行对照移植**，不是重新设计：
 * 常量数值、判定顺序、递归口径、错误码与 `data` 键名全部原样继承（依据：
 * `docs/V1.0/V0.2.0-身份与HTTP垂直切片/01-计划/01-身份与授权.md` §6
 * 「常量原样继承」+「浮点陷阱规避」）。任何一处「顺手优化」都会让 M-04 的
 * 等价性不可证，因此改动此处必须先改计划文档。
 *
 * 签名（冻结）
 * ----------
 * ``scanSensitive(data: unknown, opts?: { path?: string }): void``
 *
 * * **成功返回 `void`**（无命中），**不返回任何东西**；
 * * 命中 ⇒ 抛 `DomainError`，`code = VALIDATION_ERROR`，
 *   `data = { findings: Finding[≤20], count: number }`；
 * * **不回显原文明文**：`findings` 只带 `path` + `reason`，`message` 是固定文案。
 *   把命中值回显进错误体等于二次泄漏 —— 错误体会进日志、进响应、进监控。
 * * `entropy` **刻意不进 `data`**：Python `4.2` 与 JS `4.2` 的浮点序列化
 *   差异（`repr` vs `Number.prototype.toString`）会让 findings 无法逐字节比对，
 *   而 M-04 的判据是「两侧 `{path, reason, count}` 全等」（计划 §6 浮点陷阱规避）。
 *
 * 分层
 * ----
 * 纯函数模块，依赖面**刻意收窄**到两样东西 + 正则：
 *
 * * `DomainError` ← `@wbtime/domain`（错误类在这里，core 里从来没有；见下方 R-11）；
 * * `ERROR_CODES` ← `@wbtime/core`（码字面量只认**契约生成物**这一份）。
 *
 * **不得** import `@wbtime/db` / Fastify / 任何运行时；`@wbtime/domain` **仅允许**
 * `DomainError` 这一个错误载体，**不得** import 任何域业务实体（Task / 成员 / 仓储等）。
 * 设计原意是「不依赖域模型」，不是「不能用域错误类型」—— 两者判然有别。
 * 这样它才能同时在「发布侧静态校验」「导入侧校验」「evaluation 侧」三处零成本复用。
 *
 * R-11 · 错误载体与码来源（主理人裁定，已在 T2-01 施工记录登记）
 * -------------------------------------------------------------
 * 计划 §6 原文「依赖仅 `@wbtime/core`（`DomainError`/`ErrorCode`）」是**设计文档的
 * 事实错误**：实测 V0.1.0 的 `@wbtime/core` **从未导出过** `DomainError`
 * （`packages/core/src/errors.ts` 里只有注释提到它），`DomainError` 的真实家在
 * `packages/domain/src/errors.ts`（`code` + `data` + `message` 三段形态）。
 *
 * 裁定内容（三条路里选第一条，另两条被否）：
 *
 * * ✅ **`DomainError` ← `@wbtime/domain`**：domain 的 `dependencies` 为 `{}`（零运行时
 *   依赖）⇒ security → domain **不成环**；
 * * ❌ 在 `@wbtime/core` 新增 `DomainError` —— core 头注明令「不得依赖任何
 *   `@wbtime/*` 包」，只能另写一份 ⇒ 同名类两处实现、`instanceof` 断链；
 * * ❌ `packages/security` 自带错误载体 —— 同一个破口，还多一处要维护的形态。
 *
 * **码值的来源另算**：`code` 一律取 `@wbtime/core` 的 `ERROR_CODES`（**契约生成物**），
 * **不**用 domain 自己那份 `DOMAIN_ERROR_CODES` —— 后者是域层手抄的副本，用它就等于
 * 承认「码有两份真相」。类型上无需任何断言：`ERROR_CODES` 是 `as const`，
 * `ERROR_CODES.VALIDATION_ERROR` 的字面量类型正好落在 domain 的 `DomainErrorCode`
 * （`VALIDATION_ERROR | CONFIGURATION_ERROR`）之内。
 *
 * 语义与判据不变：抛出的仍是 `DomainError`，`code === "VALIDATION_ERROR"`，
 * `data = { findings, count }`。
 *
 * 范围（本版只做这一件事）
 * ----------------------
 * V0.2.0 只落 `scanSensitive`。`redactSensitive` / `SafetyGate` / 七挂点 /
 * 语义审核 **不在本版**（归 V0.3.0，依据 `docs/V1.0/00-安全拦截链-设计补充.md`
 * §15 / R16）。看到「顺手把脱敏也写了」的冲动时请先读那句话。
 */

// 码字面量只认契约生成物（core）；错误载体只认 domain（R-11：各取一处真源，不复制第二份）。
import { ERROR_CODES } from "@wbtime/core";
import { DomainError } from "@wbtime/domain";

// ---------------------------------------------------------------------------
// 常量（原样继承 —— 数值与顺序都不可改，改了就不是同一个扫描器）
// ---------------------------------------------------------------------------

/**
 * 敏感键名模式（命中且给**明文标量** ⇒ 拒绝；R12 原语）。
 *
 * Python: `re.compile(r"(SECRET|TOKEN|...|CREDENTIAL)", re.IGNORECASE)`
 */
export const SENSITIVE_KEY_PATTERN =
  /(SECRET|TOKEN|PASSWORD|PASSWD|PWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL)/i;

/**
 * 常见凭证明文前缀特征（保守；命中即拒）。**恰好 5 条**，顺序原样继承。
 */
export const TOKEN_VALUE_PATTERNS: readonly RegExp[] = Object.freeze([
  /sk-[A-Za-z0-9]{20,}/,
  /gh[pousr]_[A-Za-z0-9]{20,}/,
  /AKIA[0-9A-Z]{16}/,
  /xox[baprs]-[A-Za-z0-9-]{10,}/,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
]);

/**
 * 高熵 token 的字符集白名单（无空白、无 CJK ⇒ 天然排除自然语言描述）。
 *
 * Python: `re.compile(r"^[A-Za-z0-9+/=_\-]+$")`。
 * 注意 JS 的 `$` **不**匹配「末尾换行前」的位置（Python 的 `$` 会），
 * 于是带尾随换行的串在 JS 侧判为非 token —— 这一侧更严格，不会漏报真凭据。
 */
const TOKEN_CHARSET = /^[A-Za-z0-9+/=_-]+$/;

/** 高熵判定的最小长度（原值 20）。 */
export const HIGH_ENTROPY_MIN_LENGTH = 20;

/** 高熵判定的 Shannon 熵阈值（原值 4.2 bit/char）。 */
export const HIGH_ENTROPY_THRESHOLD = 4.2;

/**
 * 占位符标记（命中 ⇒ 视为**非真实凭据**，不报错）。**恰好 12 个**，原样继承。
 *
 * 判定是「小写后子串包含」（不是整串相等）—— `your-`、`<`、`>` 这几个
 * 单字符/短标记就是靠子串匹配起作用的（如 `your-api-key-here`）。
 */
export const PLACEHOLDER_MARKERS: readonly string[] = Object.freeze([
  "change-me",
  "changeme",
  "replace",
  "example",
  "placeholder",
  "your-",
  "dummy",
  "todo",
  "<",
  ">",
  "xxx",
  "****",
]);

/**
 * 引用形值前缀（`credential:` / `secret:` / `$ref:`）—— 指向别处的引用，
 * **不是明文**，故不报错。比较对象是 `trim()` 之后的前缀。
 */
export const REFERENCE_PREFIXES: readonly string[] = Object.freeze([
  "credential:",
  "secret:",
  "$ref:",
]);

/**
 * 递归深度上限（原值 200）。超深 ⇒ `VALIDATION_ERROR` + `reason="too_deep"`。
 *
 * 存在的意义不是「限制功能」，而是把裸 `RecursionError`/`RangeError: Maximum
 * call stack size exceeded` 换成可判定的领域错误 —— 后者在 API 层会变成 500。
 */
export const MAX_SCAN_DEPTH = 200;

/** 错误体里 `findings` 的截断条数上限（原值 20；`count` 仍是**真实总数**）。 */
export const MAX_FINDINGS = 20;

const MSG_CREDENTIAL = "包内容含疑似明文凭据（禁止明文，需改用引用）";
const MSG_TOO_DEEP = "包内容嵌套过深（超出扫描上限）";

// ---------------------------------------------------------------------------
// 类型（与计划 §6 的冻结签名逐字对齐）
// ---------------------------------------------------------------------------

/** 单条命中原因。三个字面值就是契约，**不得扩**。 */
export type FindingReason = "token-prefix" | "high-entropy" | "sensitive-key";

/**
 * 单条命中：只有路径与原因。
 *
 * **刻意不含命中值** —— 错误体常常被原样写进日志/响应/监控，带明文即泄漏。
 */
export interface Finding {
  /** 命中位置，形如 `providers[0].api_key`（根为 `path` 选项值 + `.` 前缀）。 */
  readonly path: string;
  readonly reason: FindingReason;
}

/** `scanSensitive` 的可选项。`path` 是路径前缀（递归内部同样复用）。 */
export interface ScanSensitiveOptions {
  /** 当前路径前缀，缺省 `""`。多段扫描时用于把外层位置带进 findings。 */
  readonly path?: string;
}

/** 命中时 `DomainError.data` 的形状（供调用方/测试做类型收窄）。 */
export interface ScanSensitiveData {
  readonly findings: readonly Finding[];
  readonly count: number;
}

/** `too_deep` 时 `DomainError.data` 的形状。 */
export interface TooDeepData {
  readonly reason: "too_deep";
  readonly limit: number;
}

// ---------------------------------------------------------------------------
// 标量化：对齐 Python 的 `str(value)`
// ---------------------------------------------------------------------------

/**
 * 把标量转成用于判定的文本，语义对齐 Python 的 `str(value)`。
 *
 * 为什么不是 `String(value)`：Python `str(True) == "True"`、`str(None) == "None"`，
 * 而 JS 给 `"true"` / `"null"`。当前判定逻辑对这两者结论相同（都命不中任何
 * 模式），但**等价性判据要靠逐条对齐来守**，所以这里按 py 的形状写，
 * 而不是按「反正结果一样」赌一把。
 */
function toScalarText(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return String(value);
  if (typeof value === "bigint") return value.toString();
  // 非标量走不到这里（映射 / 序列在 walk 里已被分支处理）；兜底保持可判定。
  return String(value);
}

/** 按 Unicode 码点计长 —— 对齐 Python `len(str)`（Python 计码点，JS `.length` 计 UTF-16 单元）。 */
function codePointLength(text: string): number {
  let length = 0;
  for (const _ of text) length += 1;
  return length;
}

/** 拆成码点数组（熵计算与长度都基于码点，避免 emoji 等增补平面字符被算成 2）。 */
function toCodePoints(text: string): string[] {
  return Array.from(text);
}

// ---------------------------------------------------------------------------
// 判定原语
// ---------------------------------------------------------------------------

/** 是否为「引用形」值（`credential:` / `secret:` / `$ref:` 前缀，比较前 trim）。 */
function isReference(text: string): boolean {
  const stripped = text.trim();
  return REFERENCE_PREFIXES.some((prefix) => stripped.startsWith(prefix));
}

/** 是否像占位符（小写后**子串**包含任一 marker）。 */
function looksLikePlaceholder(text: string): boolean {
  const lowered = text.toLowerCase();
  return PLACEHOLDER_MARKERS.some((marker) => lowered.includes(marker));
}

/** Shannon 熵（bit/char）。空串按 0 处理（与 py `_shannon_entropy` 一致）。 */
function shannonEntropy(codePoints: readonly string[]): number {
  if (codePoints.length === 0) return 0;
  const counts = new Map<string, number>();
  for (const char of codePoints) {
    counts.set(char, (counts.get(char) ?? 0) + 1);
  }
  const total = codePoints.length;
  let entropy = 0;
  for (const count of counts.values()) {
    const probability = count / total;
    entropy -= probability * Math.log2(probability);
  }
  return entropy;
}

/**
 * 是否为高熵 token（保守判定，避免误伤普通描述文本）。
 *
 * 四道闸门顺序与 py 完全一致：① 长度 ≥ 20；② 字符集命中；③ 含字母**且**
 * 含数字或 `+/=_-`；④ Shannon 熵 ≥ 4.2。任一不满足即 `false`。
 *
 * 第 ③ 闸门里「含字母」用 `/[A-Za-z]/`：字符集闸门已把可判定的串限定为
 * ASCII，故等价于 py 的 `char.isalpha()`（后者是 Unicode 感知的）。
 */
function isHighEntropyToken(text: string): boolean {
  const codePoints = toCodePoints(text);
  if (codePoints.length < HIGH_ENTROPY_MIN_LENGTH) return false;
  if (!TOKEN_CHARSET.test(text)) return false;
  let hasLetter = false;
  let hasOther = false;
  for (const char of codePoints) {
    if (/[A-Za-z]/.test(char)) hasLetter = true;
    else if (/[0-9]/.test(char) || "+/=_-".includes(char)) hasOther = true;
    if (hasLetter && hasOther) break;
  }
  if (!(hasLetter && hasOther)) return false;
  return shannonEntropy(codePoints) >= HIGH_ENTROPY_THRESHOLD;
}

/**
 * 单值命中原因（`null` 表示无命中）。判定顺序原样继承 py `_value_finding`：
 *
 * 1. 空值 / 引用形 ⇒ 无命中；
 * 2. 占位符 ⇒ 无命中（**先于 token 前缀**：`sk-example…` 这种文档串不该报错）；
 * 3. 5 条 token 前缀 ⇒ `token-prefix`；
 * 4. 高熵 ⇒ `high-entropy`（先于键名判定：同一串既是高熵又挂在 `api_key` 上，
 *    原因记为高熵 —— 两者都成立时 py 就是这个顺序）；
 * 5. 键名敏感 + 明文长度 ≥ 8 ⇒ `sensitive-key`。
 */
function valueFinding(key: string, value: string): FindingReason | null {
  if (value === "" || isReference(value)) return null;
  if (looksLikePlaceholder(value)) return null;
  for (const pattern of TOKEN_VALUE_PATTERNS) {
    if (pattern.test(value)) return "token-prefix";
  }
  if (isHighEntropyToken(value)) return "high-entropy";
  if (SENSITIVE_KEY_PATTERN.test(key) && codePointLength(value) >= 8) return "sensitive-key";
  return null;
}

// ---------------------------------------------------------------------------
// 遍历
// ---------------------------------------------------------------------------

/** 映射的键值对视图；`null` 表示「不是映射」。支持普通对象与 `Map`。 */
function mappingEntries(node: unknown): readonly (readonly [string, unknown])[] | null {
  if (node === null || typeof node !== "object") return null;
  if (Array.isArray(node)) return null;
  if (node instanceof Map) {
    const entries: [string, unknown][] = [];
    for (const [key, value] of node.entries()) entries.push([String(key), value]);
    return entries;
  }
  // 只把「普通对象 / 无原型对象」当映射；Date、RegExp、Uint8Array 之类的宿主对象
  // 一律按标量处理（它们本来也不该出现在清单里）。
  const proto = Object.getPrototypeOf(node) as object | null;
  if (proto !== Object.prototype && proto !== null) return null;
  const entries: [string, unknown][] = [];
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    entries.push([key, value]);
  }
  return entries;
}

/**
 * 递归遍历，把命中压进 `findings`。
 *
 * **继承口径（勿"修"）**：只有「映射的标量值」会被判定。数组元素只被
 * 继续下钻（元素是映射时其标量值会被判定），**数组里的标量本身不判定** ——
 * py 的 `_walk` 对 `list`/`tuple` 分支是纯下钻，从不调用 `_value_finding`。
 * 这是上游既有语义，等价性判据要求逐条相同，因此这里照搬而不"补全"。
 */
function walk(node: unknown, prefix: string, depth: number, findings: Finding[]): void {
  if (depth > MAX_SCAN_DEPTH) {
    throw new DomainError(MSG_TOO_DEEP, ERROR_CODES.VALIDATION_ERROR, {
      reason: "too_deep",
      limit: MAX_SCAN_DEPTH,
    } satisfies TooDeepData);
  }

  const entries = mappingEntries(node);
  if (entries !== null) {
    for (const [name, value] of entries) {
      const child = prefix ? `${prefix}.${name}` : name;
      if (mappingEntries(value) !== null) {
        walk(value, child, depth + 1, findings);
      } else if (Array.isArray(value)) {
        value.forEach((item, index) => {
          walk(item, `${child}[${index}]`, depth + 1, findings);
        });
      } else {
        const reason = valueFinding(name, toScalarText(value));
        if (reason !== null) findings.push({ path: child, reason });
      }
    }
    return;
  }

  if (Array.isArray(node)) {
    node.forEach((item, index) => {
      walk(item, `${prefix}[${index}]`, depth + 1, findings);
    });
  }
}

// ---------------------------------------------------------------------------
// 出口
// ---------------------------------------------------------------------------

/**
 * 对 YAML **值**做明文凭据启发式扫描（递归；R12）。
 *
 * @param data 任意 JSON-ish 结构（映射 / 序列 / 标量）。
 * @param opts.path 当前路径前缀（递归内部使用；对外用于多段扫描定位）。
 * @throws {DomainError} 命中明文凭据（`VALIDATION_ERROR`，
 *   `data = { findings, count }`）；**不含原文明文**，仅含命中路径与原因。
 * @throws {DomainError} 嵌套超过 {@link MAX_SCAN_DEPTH}（`VALIDATION_ERROR`，
 *   `data = { reason: "too_deep", limit }`）。
 */
export function scanSensitive(data: unknown, opts: ScanSensitiveOptions = {}): void {
  const findings: Finding[] = [];
  walk(data, opts.path ?? "", 0, findings);
  if (findings.length === 0) return;
  throw new DomainError(MSG_CREDENTIAL, ERROR_CODES.VALIDATION_ERROR, {
    findings: findings.slice(0, MAX_FINDINGS),
    count: findings.length,
  } satisfies ScanSensitiveData);
}
