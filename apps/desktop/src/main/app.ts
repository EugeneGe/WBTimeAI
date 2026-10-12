// ---------------------------------------------------------------------------
// 组合根（M2 · WS3 · T-02/T-03）
//
// 装配 设置 / 后端 / 渲染服务 / 窗口 / 菜单 / IPC，并管理生命周期 start()/shutdown()。
// 渲染层加载策略（设计 §3）：
//   - rendererMode=backend 且解析到后端 → 加载后端托管页；
//   - 否则（默认 bundled）→ 启动壳内 RendererServer 并加载其 URL。
// ---------------------------------------------------------------------------
import { app } from "electron";
import { join } from "node:path";
import type { BackendStatus } from "../shared/protocol";
import { BackendManager } from "./backend-manager";
import { IpcBridge } from "./ipc";
import { AppMenu } from "./menu";
import { RendererServer } from "./renderer-server";
import { SettingsStore } from "./settings-store";
import { WindowManager } from "./window";

/**
 * 桌面应用组合根。
 */
export class DesktopApp {
  readonly settings: SettingsStore;
  readonly backend: BackendManager;
  readonly renderer: RendererServer;
  readonly windows: WindowManager;
  readonly menu: AppMenu;

  private readonly ipc: IpcBridge;
  private started = false;

  constructor() {
    this.settings = new SettingsStore(app.getPath("userData"));
    this.backend = new BackendManager(this.settings);
    // 编译产物：out/main/app.js → 内置前端产物在 <app>/renderer。
    this.renderer = new RendererServer(join(__dirname, "..", "..", "renderer"));
    this.windows = new WindowManager();

    this.ipc = new IpcBridge({
      settings: this.settings,
      backend: this.backend,
      getMainWindow: () => this.windows.getMainWindow(),
    });

    this.menu = new AppMenu({
      restartBackend: () => {
        void this.restartBackend();
      },
      openSettings: () => {
        this.windows.focus();
        this.windows.notifyOpenSettings();
      },
    });
  }

  /** 启动：解析后端 → 起渲染服务 / 加载后端页 → 建窗口 → 注册菜单与 IPC。 */
  async start(): Promise<void> {
    if (this.started) {
      return;
    }
    this.started = true;

    const settings = this.settings.load();
    this.backend.applySettings(settings);

    const target = await this.backend.resolve();
    this.ipc.register();
    this.ipc.pushStatus(target);

    let loadUrl: string;
    if (settings.rendererMode === "backend" && target.kind !== "none") {
      loadUrl = target.baseUrl;
    } else {
      this.renderer.setBackendBaseUrl(target.baseUrl);
      loadUrl = await this.renderer.start();
    }

    this.menu.build();
    this.windows.createMainWindow(loadUrl);
    this.ipc.pushStatus(target);
  }

  /** 聚焦主窗口（二次启动 / macOS activate）。 */
  focus(): void {
    this.windows.focus();
  }

  /** 重启后端解析，并把新目标同步给渲染服务与渲染层。 */
  async restartBackend(): Promise<BackendStatus> {
    const target = await this.backend.restart();
    this.renderer.setBackendBaseUrl(target.baseUrl);
    this.ipc.pushStatus(target);
    return target;
  }

  /** 关闭：回收后端子进程与渲染服务。 */
  async shutdown(): Promise<void> {
    await this.backend.stop();
    await this.renderer.stop();
  }
}
