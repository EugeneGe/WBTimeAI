/**
 * T3-06 · `skill.yaml` 清单解析（py oracle：`wbtime_ai_skill/manifest.py` 逐条对齐）。
 *
 * 冻结的包结构（py R3 §3.1 原文）
 * ------------------------------
 *
 *     <skill_pkg>/
 *     ├── skill.yaml          # 元数据（必填）
 *     ├── instructions.md     # 指令正文（默认入口；可被 skill.yaml.instructions 覆盖路径）
 *     ├── examples/           # 示例（可选目录，kind=example）
 *     ├── resources/          # 资源（可选目录，kind=file/template）
 *     └── scripts/            # 脚本资源（可选目录，kind=script；仅供 Tool/MCP 执行）
 *
 * 与 py oracle 的语义对齐（**差异逐条登记于 T3-06 施工记录 §6**）：
 *   - 必填键：`name`（`^[a-z0-9][a-z0-9._-]{1,63}$`）+ `version`（`MAJOR.MINOR.PATCH`）；
 *     缺失 / 非法 ⇒ 422 `VALIDATION_ERROR`（py `_validation_error` 同码）；
 *   - 其余键全部有缺省（`display_name` 缺省 = `name`，与 py `or name` 同口径）；
 *   - **TS 侧加固（py 没有的）**：路径形字段（`instructions` / `entry` / `resources` /
 *     `examples` / `scripts`）一律过 {@link validateRelPath} 边界校验 —— `..` 段 /
 *     绝对路径 / 反斜杠 / 盘符 ⇒ 422（R3-21 反例：「清单解析放行 `../` 资源路径 ⇒ 必红」）。
 *     py 侧资源来自磁盘扫描（`rglob`）没有清单级路径字段可注入，TS 把同样的边界
 *     前移到解析期，越界在 422 处死掉而不是等到装载期。
 *   - **确定性**（验收 ③）：{@link manifestFingerprint} 对解析结果做**键排序的规范
 *     JSON** 再 sha256 —— 同一清单两次解析（含 YAML 键序不同）sha 全等；这是纯函数
 *     保证，不是"祈祷 yaml 包稳定"。
 *
 * 错误载体：与 agent 模块同型（`authError` → `HttpException`，状态由契约错误表派生），
 * 校验失败恒 422 `VALIDATION_ERROR`，**不新增契约错误码**。本文件**零 fs / 零 Web 路由**
 * （错误载体是 apps/api 的既有公共件，与 py「manifest 零 ORM/Web」的分层意图一致）。
 */

import { createHash } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import { parse as yamlParse } from "yaml";

import { authError } from "../auth/errors.js";

// ---------------------------------------------------------------------------
// 常量（py `SKILL_NAME_PATTERN` / `DEFAULT_*` 逐条对齐）
// ---------------------------------------------------------------------------

/** Skill 名合法模式（py `SKILL_NAME_PATTERN` 同源：小型标识符，R3 §3.2）。 */
export const SKILL_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{1,63}$/;

/** 语义化版本模式（py `_VERSION_PATTERN` 同源：严格 `MAJOR.MINOR.PATCH`，无前缀无后缀）。 */
export const SKILL_VERSION_PATTERN = /^(\d+)\.(\d+)\.(\d+)$/;

/** 默认指令入口（py `DEFAULT_INSTRUCTIONS_FILE`）。 */
export const DEFAULT_INSTRUCTIONS_FILE = "instructions.md";
/** 默认资源目录（py `DEFAULT_RESOURCES_DIR`）。 */
export const DEFAULT_RESOURCES_DIR = "resources";
/** 默认示例目录（py `DEFAULT_EXAMPLES_DIR`）。 */
export const DEFAULT_EXAMPLES_DIR = "examples";
/** 默认脚本目录（py `DEFAULT_SCRIPTS_DIR`）。 */
export const DEFAULT_SCRIPTS_DIR = "scripts";

/** 资源种类全集（py `SkillResourceSpec.kind` 词汇）。 */
export const SKILL_RESOURCE_KINDS = ["file", "example", "script", "template"] as const;

// ---------------------------------------------------------------------------
// 清单模型（py `SkillManifest` 的冻结字段，逐字段同名）
// ---------------------------------------------------------------------------

/** `skill.yaml` 解析产物（py `SkillManifest` 冻结字段；键名蛇形 = py dataclass 同名）。 */
export interface SkillManifestData {
  readonly name: string;
  readonly version: string;
  readonly display_name: string;
  readonly description: string;
  readonly category: string;
  /** `module:attr` 或相对路径；`null` = 纯指令包，无代码入口（py 同口径）。 */
  readonly entry: string | null;
  readonly instructions: string;
  /** 依赖声明（**字符串**，如 `tool:filesystem`；只声明不 import —— py 头注原文）。 */
  readonly dependencies: readonly string[];
  /** 需要的 capability（py `requires`）。 */
  readonly requires: readonly string[];
  readonly license: string;
  readonly resources: string;
  readonly examples: string;
  readonly scripts: string;
  readonly min_wbtime_ai_version: string;
}

/** 造 422 `VALIDATION_ERROR`（py `_validation_error` 同码同形；不新增契约错误码）。 */
function manifestError(message: string, data: Record<string, unknown> = {}): Error {
  return authError(ERROR_CODES.VALIDATION_ERROR, message, data);
}

// ---------------------------------------------------------------------------
// 路径边界（TS 侧加固，R3-21）
// ---------------------------------------------------------------------------

/**
 * 校验一个「包内相对路径」形字段，返回原值。
 *
 * 规则（全部显式拒绝，不做静默改写 —— 改写等于替攻击者洗路径）：
 *   1. 必须是非空字符串；
 *   2. 不得含反斜杠 `\`（Windows 分隔符在这里一律视为路径注入企图，统一 `/`）；
 *   3. 不得含 NUL 字节；
 *   4. 不得以 `/` 开头（绝对路径）；
 *   5. 不得是盘符形（`X:` / `X:/...`）；
 *   6. 任何一段不得是 `..`（**父目录穿越 —— R3-21 反例的直接判据**）。
 *
 * 注意 `.` 段与尾随 `/` 是无害的，**不**在此拒绝（拒绝它们属于过度校验，会把
 * `resources/./x` 这类合法书写挡在门外）。
 *
 * @param field 字段名（写进错误 `data`，便于定位）。
 * @param value 原始值。
 * @returns 原值（通过校验）。
 * @throws {HttpException} 任一规则命中 ⇒ 422 `VALIDATION_ERROR`。
 */
export function validateRelPath(field: string, value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw manifestError(`skill.yaml: ${field} 必须是非空字符串`, { field, value: value ?? null });
  }
  if (value.includes("\\")) {
    throw manifestError(`skill.yaml: ${field} 不得含反斜杠（路径分隔符一律用 /）`, {
      field,
      value,
    });
  }
  if (value.includes("\0")) {
    throw manifestError(`skill.yaml: ${field} 含 NUL 字节`, { field });
  }
  if (value.startsWith("/")) {
    throw manifestError(`skill.yaml: ${field} 必须是包内相对路径（不得以 / 开头）`, { field, value });
  }
  if (/^[a-zA-Z]:/.test(value)) {
    throw manifestError(`skill.yaml: ${field} 不得是盘符绝对路径`, { field, value });
  }
  for (const segment of value.split("/")) {
    if (segment === "..") {
      throw manifestError(`skill.yaml: ${field} 越界（含 .. 段，父目录穿越）`, { field, value });
    }
  }
  return value;
}

// ---------------------------------------------------------------------------
// 字段归一化（py `_as_str_tuple` / `manifest_from_dict` 逐条对齐）
// ---------------------------------------------------------------------------

/** 把 YAML 列表字段归一化为字符串数组（py `_as_str_tuple`：falsy ⇒ 空；单串 ⇒ 单元素）。 */
function asStrTuple(value: unknown): readonly string[] {
  if (value === undefined || value === null || value === false || value === "") return [];
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.map((item) => String(item));
  return [String(value)];
}

/** 可空字符串字段的 py 口径：`data.get(k) or 默认`（falsy 一律落默认）。 */
function strOr(value: unknown, fallback: string): string {
  return typeof value === "string" && value !== "" ? value : fallback;
}

/**
 * 由解析出的字典构造并校验清单（py `manifest_from_dict` 同名同语义）。
 *
 * @param data `skill.yaml` 解析产物（非映射 ⇒ 422，py「顶层须为映射」同文案）。
 * @returns 冻结的清单数据。
 * @throws {HttpException} 缺 `name` / `version` 或取值非法 / 路径越界 ⇒ 422。
 */
export function manifestFromDict(data: unknown): SkillManifestData {
  if (data === null || data === undefined) {
    // py `manifest_from_dict(raw or {})`：空文档 ⇒ 落到 name 缺失的同一条错误。
    throw manifestError("skill.yaml: name 缺失或非法", { field: "name", value: null });
  }
  if (typeof data !== "object" || Array.isArray(data)) {
    throw manifestError("skill.yaml 顶层须为映射", { field: "skill" });
  }
  const dict = data as Record<string, unknown>;

  const rawName = dict.name;
  if (typeof rawName !== "string" || !SKILL_NAME_PATTERN.test(rawName)) {
    throw manifestError("skill.yaml: name 缺失或非法", { field: "name", value: rawName ?? null });
  }
  const rawVersion = dict.version;
  if (typeof rawVersion !== "string" || !SKILL_VERSION_PATTERN.test(rawVersion)) {
    throw manifestError("skill.yaml: version 缺失或非语义化版本", {
      field: "version",
      value: rawVersion ?? null,
    });
  }

  return {
    name: rawName,
    version: rawVersion,
    // py `display_name=str(data.get("display_name") or name)`：空串/缺失 ⇒ 回落 name。
    display_name: strOr(dict.display_name, rawName),
    description: strOr(dict.description, ""),
    category: strOr(dict.category, ""),
    entry: dict.entry ? validateRelPath("entry", String(dict.entry)) : null,
    instructions: validateRelPath("instructions", strOr(dict.instructions, DEFAULT_INSTRUCTIONS_FILE)),
    dependencies: asStrTuple(dict.dependencies),
    requires: asStrTuple(dict.requires),
    license: strOr(dict.license, ""),
    resources: validateRelPath("resources", strOr(dict.resources, DEFAULT_RESOURCES_DIR)),
    examples: validateRelPath("examples", strOr(dict.examples, DEFAULT_EXAMPLES_DIR)),
    scripts: validateRelPath("scripts", strOr(dict.scripts, DEFAULT_SCRIPTS_DIR)),
    min_wbtime_ai_version: strOr(dict.min_wbtime_ai_version, ""),
  };
}

/**
 * 解析 `skill.yaml` 文本（py `parse_manifest` 的文本入参变体：读文件归 {@link ../loader}）。
 *
 * @param raw YAML 文本。
 * @returns 校验过的清单数据。
 * @throws {HttpException} YAML 非法（⇒「skill.yaml 解析失败」）或字段校验失败 ⇒ 422。
 */
export function parseManifestYaml(raw: string): SkillManifestData {
  // yaml@2 的 `parse` 即 safe_load（v2 不再有 `yaml.load`）；解析失败抛 YAML 异常。
  let parsed: unknown;
  try {
    parsed = yamlParse(raw);
  } catch {
    throw manifestError("skill.yaml 解析失败");
  }
  return manifestFromDict(parsed);
}

// ---------------------------------------------------------------------------
// 确定性（验收 ③）
// ---------------------------------------------------------------------------

/**
 * 递归键排序的规范 JSON（确定性指纹的基座）。
 *
 * 为什么不直接 `JSON.stringify`：对象键序 = 插入序，YAML 键序不同就会得到不同
 * sha —— 那是「解析确定性」反例的直接命中点。排序后同输入（甚至键序不同的同内容
 * 输入）必得同一串。
 */
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    return Object.fromEntries(entries.map(([key, item]) => [key, canonicalize(item)]));
  }
  return value;
}

/**
 * 清单指纹（sha256 hex；验收 ③「同输入两次 sha 全等」的判据载体）。
 *
 * @param manifest 清单数据（或任意可规范化的 JSON 值）。
 * @returns 64 位十六进制指纹。
 */
export function manifestFingerprint(manifest: SkillManifestData | Record<string, unknown>): string {
  return createHash("sha256").update(JSON.stringify(canonicalize(manifest))).digest("hex");
}

/**
 * 语义化版本 → 可比较三元组（py `version_key` 同语义；非法回退 `(0,0,0)`）。
 *
 * @param version 版本串。
 * @returns `[major, minor, patch]`。
 */
export function versionKey(version: string): readonly [number, number, number] {
  const match = SKILL_VERSION_PATTERN.exec(String(version));
  if (match === null) return [0, 0, 0];
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}
