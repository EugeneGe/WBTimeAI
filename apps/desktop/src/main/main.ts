// ---------------------------------------------------------------------------
// 应用入口（M2 · WS3 · T-02）
//
// 单实例锁 → whenReady 启动 DesktopApp → 生命周期（activate / window-all-closed /
// before-quit）。退出时回收后端子进程与渲染服务。
//
// 打包冒烟（T-04）：置 ASTRA_DESKTOP_SMOKE=1 时，窗口就绪后写标记文件并自动退出，
// 供 scripts/smoke-packaged.mjs 对打包产物做**无交互**启动验证。
// ---------------------------------------------------------------------------
import { app, type BrowserWindow } from "electron";
import { writeFileSync } from "node:fs";
import { DesktopApp } from "./app";

let desktopApp: DesktopApp | null = null;
let shuttingDown = false;

/**
 * 打包冒烟钩子：窗口首帧 / 页面加载完成后写标记并退出（仅 `ASTRA_DESKTOP_SMOKE=1`）。
 *
 * @param window 主窗口（可能为 null）。
 */
function installSmokeExit(window: BrowserWindow | null): void {
  let finished = false;
  const finish = (): void => {
    if (finished) {
      return;
    }
    finished = true;
    const marker = process.env.ASTRA_DESKTOP_SMOKE_MARKER;
    if (marker) {
      try {
        writeFileSync(marker, "ready\n", "utf-8");
      } catch (error) {
        console.error("[smoke] 写入标记失败：", error);
      }
    }
    setTimeout(() => app.quit(), 200);
  };

  if (window) {
    window.webContents.once("did-finish-load", finish);
    window.once("ready-to-show", finish);
  }
  // 兜底：即使 headless 未触发上述事件，也不无限挂起。
  setTimeout(finish, 20_000);
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    desktopApp?.focus();
  });

  app
    .whenReady()
    .then(async () => {
      desktopApp = new DesktopApp();
      await desktopApp.start();
      if (process.env.ASTRA_DESKTOP_SMOKE === "1") {
        installSmokeExit(desktopApp.windows.getMainWindow());
      }
      app.on("activate", () => {
        desktopApp?.focus();
      });
    })
    .catch((error: unknown) => {
      console.error("[main] 启动失败：", error);
      app.quit();
    });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  app.on("before-quit", (event) => {
    if (shuttingDown || desktopApp === null) {
      return;
    }
    event.preventDefault();
    shuttingDown = true;
    void desktopApp
      .shutdown()
      .catch((error: unknown) => {
        console.error("[main] 关闭回收失败：", error);
      })
      .finally(() => {
        app.exit(0);
      });
  });
}
