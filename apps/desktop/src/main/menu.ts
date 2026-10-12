// ---------------------------------------------------------------------------
// 应用菜单（M2 · WS3 · T-02）
//
// 项：关于 / 打开设置 / 重启后端 / 退出（+ 视图：重新加载 / 开发者工具）。
// 动作经注入回调触发，避免菜单模块反向依赖组合根。
// ---------------------------------------------------------------------------
import { app, dialog, Menu, type MenuItemConstructorOptions } from "electron";

/** 菜单动作依赖（由组合根注入）。 */
export interface AppMenuDeps {
  /** 重启后端解析（回收子进程并重新拉起 / 重连）。 */
  restartBackend(): void;
  /** 打开设置（聚焦窗口并通知渲染层）。 */
  openSettings(): void;
}

/**
 * 应用菜单构建器。
 */
export class AppMenu {
  /**
   * @param deps 菜单动作回调。
   */
  constructor(private readonly deps: AppMenuDeps) {}

  /**
   * 构建并设置为应用菜单。
   *
   * @returns 构建出的 {@link Menu}。
   */
  build(): Menu {
    const isMac = process.platform === "darwin";

    const template: MenuItemConstructorOptions[] = [];

    if (isMac) {
      template.push({
        label: app.name,
        submenu: [
          { role: "about", label: "关于 Astra AI" },
          { type: "separator" },
          {
            label: "打开设置",
            click: () => this.deps.openSettings(),
          },
          { type: "separator" },
          { role: "hide", label: "隐藏" },
          { role: "quit", label: "退出" },
        ],
      });
    } else {
      template.push({
        label: "文件",
        submenu: [
          {
            label: "打开设置",
            click: () => this.deps.openSettings(),
          },
          { type: "separator" },
          { role: "quit", label: "退出" },
        ],
      });
    }

    template.push({
      label: "后端",
      submenu: [
        {
          label: "重启后端",
          click: () => this.deps.restartBackend(),
        },
      ],
    });

    template.push({
      label: "视图",
      submenu: [
        { role: "reload", label: "重新加载" },
        { role: "forceReload", label: "强制重新加载" },
        { role: "toggleDevTools", label: "开发者工具" },
        { type: "separator" },
        { role: "resetZoom", label: "实际大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" },
        { type: "separator" },
        { role: "togglefullscreen", label: "全屏" },
      ],
    });

    if (!isMac) {
      template.push({
        label: "帮助",
        submenu: [
          {
            label: "关于 Astra AI",
            click: () => {
              void dialog.showMessageBox({
                type: "info",
                title: "关于 Astra AI",
                message: "Astra AI 桌面壳",
                detail: `版本 ${app.getVersion()}\nElectron ${process.versions.electron}\nNode ${process.versions.node}`,
                buttons: ["确定"],
              });
            },
          },
        ],
      });
    }

    const menu = Menu.buildFromTemplate(template);
    Menu.setApplicationMenu(menu);
    return menu;
  }
}
