// ---------------------------------------------------------------------------
// 应用入口（M2 · WS3 · T-02）
//
// 单实例锁 → whenReady 启动 DesktopApp → 生命周期（activate / window-all-closed /
// before-quit）。退出时回收后端子进程与渲染服务。
// ---------------------------------------------------------------------------
import { app } from "electron";
import { DesktopApp } from "./app";

let desktopApp: DesktopApp | null = null;
let shuttingDown = false;

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
