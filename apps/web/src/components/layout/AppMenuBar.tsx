import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { DiagnosticsDialog } from "@/components/diagnostics/DiagnosticsDialog";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import type { SettingsSection } from "@/components/settings/SettingsDialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import { hasShellAction, invokeShellAction } from "@/lib/shellAction";

/**
 * 顶栏 HTML 菜单（V0.4.5 B5 · F-25）。
 *
 * 横排菜单按钮（文件 / 编辑 / 视图 / 帮助），radix DropdownMenu 下拉：
 * - **文件**：新聊天（`navigate("/chat")`，Ctrl+N 提示标签）；新临时聊天（禁用占位）；
 * - **编辑**：撤销 / 重做 / 剪切 / 复制 / 粘贴 / 全选（`document.execCommand`）；
 * - **视图**：重启后端（壳）/ 重新加载 / 强制重新加载（`location.reload()`）/
 *   放大 / 缩小 / 重置缩放（壳 zoom）；
 * - **帮助**：设置（壳 open-settings / 纯 Web 回落页内设置弹窗）/ 初始化（壳 show-guide）/
 *   诊断工具（本地 {@link DiagnosticsDialog}）/ 关于（壳 about / 纯 Web 回落设置·关于分区）。
 *
 * 壳内检测：`window.wbtimeAiDesktop.shellAction` 存在才启用壳动作项；
 * 纯 Web 环境下**有页内等价入口的项回落**（设置 / 关于），无等价物的项禁用
 * （初始化 / 重启后端 / 缩放），title 提示「仅桌面端可用」。
 *
 * 菜单切换（B-04）：四个根一律 `modal={false}`——默认模态会把「点同级触发器」的
 * pointerdown 当作外部交互吞掉（第一次只关闭当前菜单、不打开目标菜单，需点两次）；
 * 非模态下同一次点击即可完成「关旧 + 开新」。
 */
export function AppMenuBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const shellAvailable = hasShellAction();
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  // B-03（V0.4.6 BugFix）：设置/关于的纯 Web 回落弹窗（与 `UserMenu` 同一链路）。
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("profile");

  /** 打开设置：壳内走独立设置窗，纯 Web 回落页内 `SettingsDialog`（F-26.5 口径）。 */
  const openSettings = (section: SettingsSection): void => {
    if (shellAvailable) {
      invokeShellAction({ action: "open-settings", section });
      return;
    }
    setSettingsSection(section);
    setSettingsOpen(true);
  };

  /** 壳动作项公共类（禁用 = 降灰）。 */
  const shellOnlyTitle = t("appMenu.desktopOnly");

  /** 通用菜单项（壳动作可用性按需注入）。 */
  const renderItem = (
    children: ReactNode,
    options: {
      key: string;
      onSelect?: () => void;
      disabled?: boolean;
      title?: string;
      shortcut?: string;
    },
  ): ReactNode => (
    <DropdownMenuItem
      key={options.key}
      data-testid={`app-menu-item-${options.key}`}
      disabled={options.disabled}
      title={options.title}
      onSelect={() => options.onSelect?.()}
      className={cn(options.disabled && "opacity-50")}
    >
      {children}
      {options.shortcut ? (
        <span className="ml-auto pl-4 text-xs text-muted-foreground">{options.shortcut}</span>
      ) : null}
    </DropdownMenuItem>
  );

  return (
    <nav
      data-testid="app-menu-bar"
      aria-label={t("appMenu.label")}
      className="flex items-center gap-0.5"
    >
      {/* 文件 */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="app-menu-file"
            className="flex items-center gap-0.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent/15 hover:text-foreground"
          >
            {t("appMenu.file.title")}
            <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={6} data-testid="app-menu-file-content">
          {renderItem(t("appMenu.file.newChat"), {
            key: "file-new-chat",
            shortcut: "Ctrl+N",
            onSelect: () => navigate("/chat"),
          })}
          {renderItem(t("appMenu.file.newTempChat"), { key: "file-new-temp-chat", disabled: true })}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 编辑 */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="app-menu-edit"
            className="flex items-center gap-0.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent/15 hover:text-foreground"
          >
            {t("appMenu.edit.title")}
            <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={6} data-testid="app-menu-edit-content">
          {(
            [
              ["undo", "undo"],
              ["redo", "redo"],
              ["cut", "cut"],
              ["copy", "copy"],
              ["paste", "paste"],
              ["selectAll", "selectAll"],
            ] as const
          ).map(([key, command]) =>
            renderItem(t(`appMenu.edit.${key}`), {
              key: `edit-${key}`,
              onSelect: () => document.execCommand(command),
            }),
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 视图 */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="app-menu-view"
            className="flex items-center gap-0.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent/15 hover:text-foreground"
          >
            {t("appMenu.view.title")}
            <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={6} data-testid="app-menu-view-content">
          {renderItem(t("appMenu.view.restartBackend"), {
            key: "view-restart-backend",
            disabled: !shellAvailable,
            title: shellAvailable ? undefined : shellOnlyTitle,
            onSelect: () => invokeShellAction({ action: "restart-backend" }),
          })}
          <DropdownMenuSeparator />
          {renderItem(t("appMenu.view.reload"), {
            key: "view-reload",
            onSelect: () => window.location.reload(),
          })}
          {renderItem(t("appMenu.view.forceReload"), {
            key: "view-force-reload",
            onSelect: () => window.location.reload(),
          })}
          <DropdownMenuSeparator />
          {renderItem(t("appMenu.view.zoomIn"), {
            key: "view-zoom-in",
            disabled: !shellAvailable,
            title: shellAvailable ? undefined : shellOnlyTitle,
            onSelect: () => invokeShellAction({ action: "zoom", mode: "in" }),
          })}
          {renderItem(t("appMenu.view.zoomOut"), {
            key: "view-zoom-out",
            disabled: !shellAvailable,
            title: shellAvailable ? undefined : shellOnlyTitle,
            onSelect: () => invokeShellAction({ action: "zoom", mode: "out" }),
          })}
          {renderItem(t("appMenu.view.zoomReset"), {
            key: "view-zoom-reset",
            disabled: !shellAvailable,
            title: shellAvailable ? undefined : shellOnlyTitle,
            onSelect: () => invokeShellAction({ action: "zoom", mode: "reset" }),
          })}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 帮助 */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="app-menu-help"
            className="flex items-center gap-0.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent/15 hover:text-foreground"
          >
            {t("appMenu.help.title")}
            <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={6} data-testid="app-menu-help-content">
          {renderItem(t("appMenu.help.settings"), {
            key: "help-settings",
            // B-03：纯 Web 下不再禁用——回落页内设置弹窗（此前 `disabled: !shellAvailable`
            // 导致浏览器里「设置」永远点不动，而头像菜单同名入口可用）。
            onSelect: () => openSettings("profile"),
          })}
          {renderItem(t("appMenu.help.guide"), {
            key: "help-guide",
            disabled: !shellAvailable,
            title: shellAvailable ? undefined : shellOnlyTitle,
            onSelect: () => invokeShellAction({ action: "show-guide" }),
          })}
          {renderItem(t("appMenu.help.diagnostics"), {
            key: "help-diagnostics",
            onSelect: () => setDiagnosticsOpen(true),
          })}
          {renderItem(t("appMenu.help.about"), {
            key: "help-about",
            // B-03：壳内走原生 About 对话框；纯 Web 回落设置·关于分区（同一根因）。
            onSelect: () => {
              if (shellAvailable) {
                invokeShellAction({ action: "about" });
                return;
              }
              openSettings("about");
            },
          })}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 诊断工具弹窗（帮助菜单打开）。 */}
      <DiagnosticsDialog open={diagnosticsOpen} onOpenChange={setDiagnosticsOpen} />

      {/* 设置弹窗（B-03：纯 Web 下帮助→设置 / 关于的回落载体）。 */}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        initialSection={settingsSection}
      />
    </nav>
  );
}
