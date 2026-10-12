// ---------------------------------------------------------------------------
// 桌面设置持久化（M2 · WS3 · T-02）
//
// 🔴 只持久化**非敏感**项（渲染模式 / 后端 URL / 端口 / 是否自动拉起）；
//    API Key 等凭据一律走后端既有 credential 体系，绝不写入本文件或日志。
// ---------------------------------------------------------------------------
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { DesktopSettings, RendererMode } from "../shared/protocol";

/** 设置默认值（与设计 §3/§7 对齐：bundled + autoSpawn + 8080）。 */
export const DEFAULT_SETTINGS: DesktopSettings = {
  rendererMode: "bundled",
  apiBaseUrl: "",
  autoSpawnBackend: true,
  port: 8080,
};

const RENDERER_MODES: readonly RendererMode[] = ["bundled", "backend"];
const MIN_PORT = 1;
const MAX_PORT = 65535;

/** 只读设置来源（便于测试注入；`SettingsStore` 即实现此接口）。 */
export interface SettingsReader {
  load(): DesktopSettings;
}

/** 归一化端口：非整数 / 越界 → 回退默认端口。 */
function normalizePort(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(parsed) || parsed < MIN_PORT || parsed > MAX_PORT) {
    return DEFAULT_SETTINGS.port;
  }
  return parsed;
}

/**
 * 桌面设置读写器：读写 `userData/settings.json`（随平台归档）。损坏 / 缺失时回落默认。
 */
export class SettingsStore implements SettingsReader {
  /** 设置文件绝对路径。 */
  readonly filePath: string;

  /**
   * @param userDataDir Electron `app.getPath("userData")`。
   */
  constructor(userDataDir: string) {
    this.filePath = join(userDataDir, "settings.json");
  }

  /** 读取设置（损坏 / 缺失 → 默认值）。 */
  load(): DesktopSettings {
    try {
      const raw = readFileSync(this.filePath, "utf-8");
      return SettingsStore.sanitize(JSON.parse(raw) as unknown);
    } catch {
      return { ...DEFAULT_SETTINGS };
    }
  }

  /** 写入设置（先经白名单校验）；返回落盘的规范化设置。 */
  save(settings: DesktopSettings): DesktopSettings {
    const safe = SettingsStore.sanitize(settings);
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, `${JSON.stringify(safe, null, 2)}\n`, "utf-8");
    return safe;
  }

  /** 合并部分更新并落盘；返回规范化后的完整设置。 */
  update(patch: Partial<DesktopSettings>): DesktopSettings {
    return this.save({ ...this.load(), ...patch });
  }

  /**
   * 白名单 + 类型校验：屏蔽未知键与非法值（含潜在敏感注入）。
   *
   * @param input 任意来源对象（文件内容 / IPC 载荷）。
   * @returns 规范化的桌面设置。
   */
  static sanitize(input: unknown): DesktopSettings {
    const source: Record<string, unknown> =
      typeof input === "object" && input !== null ? (input as Record<string, unknown>) : {};

    const rendererMode = RENDERER_MODES.includes(source.rendererMode as RendererMode)
      ? (source.rendererMode as RendererMode)
      : DEFAULT_SETTINGS.rendererMode;

    const apiBaseUrl =
      typeof source.apiBaseUrl === "string"
        ? source.apiBaseUrl.trim()
        : DEFAULT_SETTINGS.apiBaseUrl;

    const autoSpawnBackend =
      typeof source.autoSpawnBackend === "boolean"
        ? source.autoSpawnBackend
        : DEFAULT_SETTINGS.autoSpawnBackend;

    return {
      rendererMode,
      apiBaseUrl,
      autoSpawnBackend,
      port: normalizePort(source.port),
    };
  }
}
