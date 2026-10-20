// ---------------------------------------------------------------------------
// `window.wbtimeAiDesktop` 全局类型声明（V0.4.2 · W2 · T4）
//
// 桌面壳经 preload `contextBridge.exposeInMainWorld("wbtimeAiDesktop", api)` 暴露受控 API
// （`apps/desktop/src/preload/preload.ts`）。壳内 bundled 渲染层即 `apps/web` 构建产物
// （`sync-renderer.mjs` 同步至 `apps/desktop/renderer/`），故此处**镜像**
// `apps/desktop/src/shared/protocol.ts` 的 `WBTimeAIDesktopApi` 形状。
//
// 🔴 两包独立：`apps/web` 不回引 `apps/desktop` 源码，故**就地声明**（保持字段一致）。
// 🔴 纯 Web 部署无此对象 → 属性为可选（`?`），消费侧须判空后再渲染。
// ---------------------------------------------------------------------------

/** 渲染层加载模式。 */
export type DesktopRendererMode = "bundled" | "backend";

/** 关闭按钮行为（镜像 `protocol.CloseAction`；V0.4.5 B4·F-17）。 */
export type DesktopCloseAction = "quit" | "tray";

/** 界面语言（镜像 `protocol.Language`；V0.4.5 B3·F-12）。 */
export type DesktopLanguage = "en" | "zh-CN";

/** 后端解析档位。 */
export type DesktopBackendKind = "remote" | "spawned" | "existing" | "none";

/** 当前后端目标状态（镜像 `protocol.BackendStatus`）。 */
export interface DesktopBackendStatus {
  /** 档位：远端 / 本地子进程 / 已存在本地后端 / 无。 */
  kind: DesktopBackendKind;
  /** 后端基址（`http://host:port`，无尾斜杠）；`kind=none` 时为空串。 */
  baseUrl: string;
  /** 由壳拉起的子进程 PID（仅 `kind=spawned` 非空）。 */
  pid: number | null;
  /** 人类可读说明。 */
  detail: string;
}

/** 桌面设置（**仅非敏感项**；镜像 `protocol.DesktopSettings`）。 */
export interface DesktopSettings {
  /** 渲染模式：`bundled`（壳内置 UI）| `backend`（加载后端托管页）。 */
  rendererMode: DesktopRendererMode;
  /** 用户显式配置的远端后端 URL（空串 = 未配置）。 */
  apiBaseUrl: string;
  /** 是否允许壳 spawn 本地 `wbtime-ai run`。 */
  autoSpawnBackend: boolean;
  /** 期望的本地后端端口（默认 21212；镜像 `protocol.DesktopSettings.port`）。 */
  port: number;
  /** 运行期数据目录（绝对路径）；空串 = 回退后端默认 `~/.wbtime-ai`。 */
  dataDir: string;
  /**
   * 界面语言（V0.4.5 B3·F-12；默认 `"en"`；镜像 `protocol.DesktopSettings.language`）。
   *
   * 🔴 **可选**：纯 Web / 旧版本壳可能**未**携带该字段（向前兼容），消费侧须判空后回落默认
   *    `"en"`（新壳始终下发）。
   */
  language?: DesktopLanguage;
  /**
   * 关闭按钮行为（V0.4.5 B4·F-17；默认 `"quit"`；镜像 `protocol.DesktopSettings.closeAction`）。
   *
   * 🔴 **可选**：纯 Web / 旧版本壳可能**未**携带该字段（向前兼容），消费侧须判空后回落默认
   *    `"quit"`（新壳始终下发）。
   */
  closeAction?: DesktopCloseAction;
}

/** 设置的部分更新补丁。 */
export type DesktopSettingsPatch = Partial<DesktopSettings>;

/**
 * 设置窗口区块（V0.4.5 B5 · F-26.5；镜像 `protocol.SettingsSection`）。
 *
 * 独立设置窗口 `?section=` 白名单；仅首次创建窗口时生效。
 */
export type SettingsSection =
  "profile" | "general" | "appearance" | "shortcuts" | "models" | "system" | "about" | "help";

/** 主窗口缩放动作（V0.4.5 B5 · F-25；镜像 `protocol.ZoomMode`）。 */
export type ZoomMode = "in" | "out" | "reset";

/**
 * `shell:action` 桥载荷（V0.4.5 B5 · F-25；镜像 `protocol.ShellActionPayload`；
 * 判别字段 `action` 为**冻结契约**，见开工前架构裁定 B5 §3）。
 *
 * 渲染层经 `api.shellAction(payload)` invoke 主进程，主进程按 `action` 分发：
 *   - `open-settings`   → 打开 / 聚焦独立设置窗口（`section` 仅首次创建时生效）；
 *   - `restart-backend` → 重启后端解析（含运行时自愈）；
 *   - `show-guide`      → 主窗口加载 `?view=guide` 引导页；
 *   - `about`           → 关于对话框；
 *   - `zoom`            → 主窗口缩放（±0.5 / 重置为 0）。
 */
export type ShellActionPayload =
  | { action: "open-settings"; section?: SettingsSection }
  | { action: "restart-backend" }
  | { action: "show-guide" }
  | { action: "about" }
  | { action: "zoom"; mode: ZoomMode };

/** 便携运行时解压阶段（镜像 `protocol.RuntimePhase`）。 */
export type DesktopRuntimePhase =
  "idle" | "checking" | "extracting" | "done" | "cancelled" | "error";

/** 便携运行时安装状态（镜像 `protocol.RuntimeStatus`）。 */
export interface DesktopRuntimeStatus {
  /** 阶段。 */
  phase: DesktopRuntimePhase;
  /** 运行时目录（绝对路径）。 */
  runtimeDir: string;
  /** 是否已就绪。 */
  ready: boolean;
  /** 已解压字节数。 */
  extractedBytes: number;
  /** 解压总字节数。 */
  totalBytes: number;
  /** 已完成条目数。 */
  entriesDone: number;
  /** 总条目数。 */
  entriesTotal: number;
  /** 人类可读说明 / 错误文案。 */
  detail: string;
}

/** 预加载暴露的最小受控 API（镜像 `protocol.WBTimeAIDesktopApi`）。 */
export interface WBTimeAIDesktopApi {
  /** 取当前后端状态。 */
  getStatus(): Promise<DesktopBackendStatus>;
  /** 设置远端后端 URL 并重新解析。 */
  setRemote(baseUrl: string): Promise<DesktopBackendStatus>;
  /** 重启后端解析（回收并重新拉起 / 重连）。 */
  restartBackend(): Promise<DesktopBackendStatus>;
  /** 读取桌面设置。 */
  getSettings(): Promise<DesktopSettings>;
  /** 更新桌面设置（白名单校验；非法值由主进程拒绝）。 */
  setSettings(patch: DesktopSettingsPatch): Promise<DesktopSettings>;
  /** 订阅后端状态变更；返回取消订阅函数。 */
  onStatus(listener: (status: DesktopBackendStatus) => void): () => void;
  /** 取便携运行时安装状态（T6）。 */
  getRuntimeStatus(): Promise<DesktopRuntimeStatus>;
  /** 触发（或重试）运行时解压。 */
  installRuntime(): Promise<DesktopRuntimeStatus>;
  /** 取消进行中的运行时解压。 */
  cancelRuntime(): Promise<DesktopRuntimeStatus>;
  /** 订阅运行时安装进度；返回取消订阅函数。 */
  onRuntimeProgress(listener: (status: DesktopRuntimeStatus) => void): () => void;
  /** 打开系统「选择目录」对话框；取消 / 未选 → `null`（V0.4.4 Bug7）。 */
  pickDirectory(): Promise<string | null>;
  /** 壳动作桥（V0.4.5 B5 · F-25）：打开设置窗口 / 重启后端 / 回看引导页 / 关于 / 缩放。 */
  shellAction(payload: ShellActionPayload): Promise<void>;
}

declare global {
  interface Window {
    /** 仅在桌面壳内注入；纯 Web 部署为 `undefined`。 */
    wbtimeAiDesktop?: WBTimeAIDesktopApi;
  }
}
