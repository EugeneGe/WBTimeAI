import { HelpCircle, LogOut, Palette, Settings as SettingsIcon } from "lucide-react";
import { useState } from "react";

import { useTranslation } from "@/i18n";
import { LoginDialog } from "@/components/auth/LoginDialog";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import type { SettingsSection } from "@/components/settings/SettingsDialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/useAuth";
import { useAuthGateStore } from "@/stores/authGateStore";
import { useAuthStore } from "@/stores/authStore";
import { hasShellAction, invokeShellAction } from "@/lib/shellAction";

/** 头像首字（展示用）：显示名 → 用户名 → 兜底「观」。 */
function initialOf(name: string | null | undefined, username: string | null | undefined): string {
  const source = name?.trim() || username?.trim() || "";
  return source ? source.slice(0, 1).toUpperCase() : "观";
}

/**
 * 用户菜单（头像弹层，D-UI 体验优化波 · WS-L / DU-2/DU-3；V0.4.5 B3 · F-13 精简；
 * V0.4.5 B4 · F-19.2 未登录登录弹窗）。
 *
 * **F-13 精简决策（裁定 §1 F-13）**：
 * - **移除**「剩余用量」项与「外观」三选项（浅色 / 深色 / 跟随系统，ref22 红框处）；
 * - **保留**「外观」入口**单项** → 打开设置弹窗并**深链**到「外观」分区（F-11.4）；
 * - **保留**「帮助」入口 → 打开设置弹窗并**深链**到「帮助」分区（F-11.1）；
 * - 「设置」→ 打开设置弹窗（缺省「个人」分区，F-11.5）。
 *
 * **F-19.2（B4）**：
 * - **未登录**点头像 → 打开**登录弹窗**（`LoginDialog`，经 `authGateStore.requireAuth` 触发）；
 * - **已登录**点头像 → 保持既有下拉菜单（设置 / 外观 / 帮助 / 退出登录）**不变**。
 *
 * 主题入口迁移至**设置·外观分区**（本菜单不再直接切换主题）；
 * 设置弹窗开合为**本地 state**（不入 `uiStore`，避免与其他工作流争抢 store 文件）。
 * `Esc` 与点击外部关闭由 `DropdownMenu` / `Dialog` 原语内建。
 */
export function UserMenu() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const requireAuth = useAuthGateStore((state) => state.requireAuth);
  // 设置弹窗开合 + 初始分区（深链）均为**本地 state**（不入 `uiStore`）。
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("profile");

  const displayName = user?.display_name?.trim() || user?.username || "访客";
  const initial = initialOf(user?.display_name, user?.username);

  /**
   * 打开设置并跳到指定分区（F-13 深链；V0.4.5 B5 · F-26.5 入口收口）：
   * **壳内环境优先** `shellAction({ action: "open-settings", section })`（独立设置窗口）；
   * 纯 Web 环境（无 shellAction）回落现有页内 Dialog（逻辑不变）。
   */
  const openSettings = (section: SettingsSection): void => {
    if (hasShellAction()) {
      invokeShellAction({ action: "open-settings", section });
      return;
    }
    setSettingsSection(section);
    setSettingsOpen(true);
  };

  // F-19.2：未登录 → 点头像打开登录弹窗（`requireAuth` 开弹窗并登记空待办）。
  const triggerClass =
    "mt-1 flex h-8 w-8 items-center justify-center rounded-full border-[1.5px] border-accent bg-primary-foreground/10 text-xs font-medium text-accent transition-colors hover:bg-primary-foreground/20 dark:bg-muted dark:hover:bg-muted/80";

  return (
    <>
      {isAuthenticated ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-testid="user-menu-trigger"
              title="账号"
              aria-label={`账号：${displayName}`}
              className={triggerClass}
            >
              {initial}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            side="right"
            sideOffset={8}
            data-testid="user-menu-content"
            className="w-56"
          >
            {/* 头部：头像 + 用户名 + 版本（社区版）。 */}
            <DropdownMenuLabel className="flex items-center gap-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground dark:bg-accent dark:text-primary">
                {initial}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium leading-tight text-foreground">
                  {displayName}
                </span>
                <span className="truncate text-xs leading-tight text-muted-foreground">社区版</span>
              </span>
            </DropdownMenuLabel>

            <DropdownMenuSeparator />

            {/* 设置（缺省「个人」分区）。 */}
            <DropdownMenuItem
              data-testid="user-menu-settings"
              onSelect={() => openSettings("profile")}
            >
              <SettingsIcon className="h-4 w-4 text-muted-foreground" />
              {t("userMenu.settings")}
              <span className="ml-auto text-xs text-muted-foreground">Ctrl+,</span>
            </DropdownMenuItem>

            {/* 外观（F-13 精简为单项入口）：深链到设置·外观分区。 */}
            <DropdownMenuItem
              data-testid="user-menu-appearance"
              onSelect={() => openSettings("appearance")}
            >
              <Palette className="h-4 w-4 text-muted-foreground" />
              {t("userMenu.appearance")}
            </DropdownMenuItem>

            {/* 帮助（F-13 深链）：打开设置弹窗并跳到帮助分区。 */}
            <DropdownMenuItem data-testid="user-menu-help" onSelect={() => openSettings("help")}>
              <HelpCircle className="h-4 w-4 text-muted-foreground" />
              {t("userMenu.help")}
            </DropdownMenuItem>

            <DropdownMenuSeparator />

            <DropdownMenuItem
              data-testid="user-menu-logout"
              disabled={logout.isPending}
              className="text-destructive focus:text-destructive"
              onSelect={() => logout.mutate()}
            >
              <LogOut className="h-4 w-4" />
              {t("userMenu.logout")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        // F-19.2：未登录点头像 → 打开登录弹窗（非全屏页）。
        <button
          type="button"
          data-testid="user-menu-trigger"
          title="账号"
          aria-label={`账号：${displayName}`}
          onClick={() => requireAuth(() => undefined)}
          className={triggerClass}
        >
          {initial}
        </button>
      )}

      {/* 设置弹窗（F-11）：由头像菜单「设置 / 外观 / 帮助」打开并深链到对应分区。 */}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        initialSection={settingsSection}
      />

      {/* 登录弹窗（F-19.2 / F-19.3）：未登录点头像或受限操作触发。 */}
      <LoginDialog />
    </>
  );
}
