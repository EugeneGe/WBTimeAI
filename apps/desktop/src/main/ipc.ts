// ---------------------------------------------------------------------------
// IPC 桥（M2 · WS3 · T-03）
//
// 通道（均为 `ipcMain.handle` request/response；渲染层经 preload `invoke`）：
//   backend:status      → BackendStatus
//   backend:setRemote   → 设置远端 URL 并重新解析 → BackendStatus
//   backend:restart     → 重启后端解析            → BackendStatus
//   settings:get        → DesktopSettings
//   settings:set        → 更新设置（白名单）       → DesktopSettings
//
// 后端状态变更经 `backend:status-changed` 主动推送到渲染层（事件，非 invoke）。
// ---------------------------------------------------------------------------
import { BrowserWindow, ipcMain } from "electron";
import type { BackendManager } from "./backend-manager";
import type { SettingsStore } from "./settings-store";
import type { BackendStatus, DesktopSettingsPatch } from "../shared/protocol";

/** IPC 桥依赖。 */
export interface IpcDeps {
  settings: SettingsStore;
  backend: BackendManager;
  /** 取当前主窗口（用于推送状态变更；可能尚未创建 → 返回 null）。 */
  getMainWindow(): BrowserWindow | null;
  /** 后端目标变化回调（用于同步 RendererServer 的反代基址，如引导页连接后）。 */
  onBackendChanged?(status: BackendStatus): void;
}

/** IPC 通道名常量（与 preload 契约一致）。 */
export const IPC_CHANNELS = {
  status: "backend:status",
  setRemote: "backend:setRemote",
  restart: "backend:restart",
  getSettings: "settings:get",
  setSettings: "settings:set",
  statusChanged: "backend:status-changed",
} as const;

/**
 * IPC 桥：注册主进程 handler，并把后端状态变更推送给渲染层。
 */
export class IpcBridge {
  private registered = false;

  /**
   * @param deps 依赖（设置 / 后端 / 取窗口）。
   */
  constructor(private readonly deps: IpcDeps) {}

  /** 注册全部 IPC 通道（幂等）。 */
  register(): void {
    if (this.registered) {
      return;
    }
    this.registered = true;

    ipcMain.handle(IPC_CHANNELS.status, async () => this.broadcast(await this.resolve()));

    ipcMain.handle(IPC_CHANNELS.setRemote, async (_event, baseUrl: unknown) => {
      const next = this.deps.settings.save({
        ...this.deps.settings.load(),
        apiBaseUrl: typeof baseUrl === "string" ? baseUrl : "",
      });
      this.deps.backend.applySettings(next);
      return this.broadcast(await this.resolve());
    });

    ipcMain.handle(IPC_CHANNELS.restart, async () => this.broadcast(await this.deps.backend.restart()));

    ipcMain.handle(IPC_CHANNELS.getSettings, async () => this.deps.settings.load());

    ipcMain.handle(IPC_CHANNELS.setSettings, async (_event, patch: unknown) => {
      const safePatch = (typeof patch === "object" && patch !== null
        ? patch
        : {}) as DesktopSettingsPatch;
      const next = this.deps.settings.update(safePatch);
      this.deps.backend.applySettings(next);
      return next;
    });
  }

  /** 主动向渲染层推送后端状态（窗口未就绪则跳过）。 */
  pushStatus(status: BackendStatus): void {
    this.deps.getMainWindow()?.webContents.send(IPC_CHANNELS.statusChanged, status);
  }

  private async resolve(): Promise<BackendStatus> {
    return this.deps.backend.status();
  }

  private broadcast(status: BackendStatus): BackendStatus {
    this.deps.onBackendChanged?.(status);
    this.pushStatus(status);
    return status;
  }
}
