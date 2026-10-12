// ---------------------------------------------------------------------------
// 桌面壳 ↔ 渲染层 / 主进程 共享协议（**仅类型**，无运行期代码）
//
// 由主进程与（沙箱化）预加载共同 `import type` 引用；类型在编译期擦除，
// 故预加载**不会**因本模块引入任何 Node/运行期依赖（`sandbox:true` 安全）。
// ---------------------------------------------------------------------------

/** 后端解析结果的档位（见设计 §2.1 优先级链）。 */
export type BackendKind = "remote" | "spawned" | "existing" | "none";

/** 渲染层加载模式（见设计 §3）。 */
export type RendererMode = "bundled" | "backend";

/** 当前后端目标状态（可经 IPC 下发渲染层）。 */
export interface BackendStatus {
  /** 档位：远端 / 本地子进程 / 已存在本地后端 / 无。 */
  kind: BackendKind;
  /** 后端基址（`http://host:port`，无尾斜杠）；`kind=none` 时为空串。 */
  baseUrl: string;
  /** 由壳拉起的子进程 PID（仅 `kind=spawned` 非空）。 */
  pid: number | null;
  /** 人类可读说明（用于诊断 / 引导页展示）。 */
  detail: string;
}

/** 桌面设置（**仅非敏感项**；密钥一律走后端 credential 体系，绝不入此文件）。 */
export interface DesktopSettings {
  /** 渲染模式：`bundled`（壳内置 UI）| `backend`（加载后端托管页）。 */
  rendererMode: RendererMode;
  /** 用户显式配置的远端后端 URL（空串 = 未配置）。最高优先级。 */
  apiBaseUrl: string;
  /** 是否允许壳 spawn 本地 `astra run`。 */
  autoSpawnBackend: boolean;
  /** 期望的本地后端端口（默认 8080）。 */
  port: number;
}

/** 设置的部分更新补丁。 */
export type DesktopSettingsPatch = Partial<DesktopSettings>;

/** 预加载经 `contextBridge` 暴露给渲染层的最小只读/受控 API。 */
export interface AstraDesktopApi {
  /** 取当前后端状态。 */
  getStatus(): Promise<BackendStatus>;
  /** 设置远端后端 URL 并重新解析。 */
  setRemote(baseUrl: string): Promise<BackendStatus>;
  /** 重启后端解析（回收并重新拉起 / 重连）。 */
  restartBackend(): Promise<BackendStatus>;
  /** 读取桌面设置。 */
  getSettings(): Promise<DesktopSettings>;
  /** 更新桌面设置（白名单校验）。 */
  setSettings(patch: DesktopSettingsPatch): Promise<DesktopSettings>;
  /** 订阅后端状态变更；返回取消订阅函数。 */
  onStatus(listener: (status: BackendStatus) => void): () => void;
}
