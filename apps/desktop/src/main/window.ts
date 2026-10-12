// ---------------------------------------------------------------------------
// 窗口管理（M2 · WS3 · T-02）
//
// 安全基线（设计 §10）：contextIsolation:true / nodeIntegration:false / sandbox:true；
// 外链一律走系统浏览器（`shell.openExternal`）；限制应用内导航到同源。
// ---------------------------------------------------------------------------
import { BrowserWindow, shell } from "electron";
import { join } from "node:path";

/** 主窗口默认尺寸。 */
const WINDOW_WIDTH = 1280;
const WINDOW_HEIGHT = 840;
const MIN_WIDTH = 940;
const MIN_HEIGHT = 640;

/** 判断两个 URL 是否同源（协议 + 主机 + 端口）。 */
function isSameOrigin(candidate: string, reference: string): boolean {
  try {
    return new URL(candidate).origin === new URL(reference).origin;
  } catch {
    return false;
  }
}

/** 是否可作为外链在系统浏览器打开。 */
function isExternalHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * 主窗口管理器：创建窗口、加载渲染层 URL、外链与导航策略、聚焦。
 */
export class WindowManager {
  private mainWindow: BrowserWindow | null = null;

  /**
   * 创建主窗口并加载渲染层。
   *
   * @param loadUrl 渲染层入口（`bundled` = 壳内 server；`backend` = 后端地址）。
   * @returns 创建的 {@link BrowserWindow}。
   */
  createMainWindow(loadUrl: string): BrowserWindow {
    const window = new BrowserWindow({
      width: WINDOW_WIDTH,
      height: WINDOW_HEIGHT,
      minWidth: MIN_WIDTH,
      minHeight: MIN_HEIGHT,
      show: false,
      backgroundColor: "#0b0b0f",
      title: "Astra AI",
      webPreferences: {
        preload: join(__dirname, "..", "preload", "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });

    window.once("ready-to-show", () => window.show());

    // 外链：一律系统浏览器打开，禁止应用内开新窗口。
    window.webContents.setWindowOpenHandler(({ url }) => {
      if (isExternalHttpUrl(url)) {
        void shell.openExternal(url);
      }
      return { action: "deny" };
    });

    // 应用内导航：仅允许同源；外部地址转交系统浏览器。
    window.webContents.on("will-navigate", (event, url) => {
      if (!isSameOrigin(url, loadUrl)) {
        event.preventDefault();
        if (isExternalHttpUrl(url)) {
          void shell.openExternal(url);
        }
      }
    });

    void window.loadURL(loadUrl);

    this.mainWindow = window;
    window.on("closed", () => {
      if (this.mainWindow === window) {
        this.mainWindow = null;
      }
    });
    return window;
  }

  /** 当前主窗口（未创建 → null）。 */
  getMainWindow(): BrowserWindow | null {
    return this.mainWindow;
  }

  /** 聚焦主窗口（必要时从最小化恢复）。 */
  focus(): void {
    const window = this.mainWindow;
    if (!window) {
      return;
    }
    if (window.isMinimized()) {
      window.restore();
    }
    window.focus();
  }

  /** 通知渲染层打开设置页（菜单「打开设置」用；渲染层可选择性监听）。 */
  notifyOpenSettings(): void {
    this.mainWindow?.webContents.send("menu:openSettings");
  }
}
