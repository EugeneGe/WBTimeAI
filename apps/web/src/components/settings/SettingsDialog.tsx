import { Boxes, Cpu, HelpCircle, Info, Keyboard, Palette, Settings2, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { useTranslation } from "@/i18n";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/cn";

import { AboutSection } from "./sections/AboutSection";
import { AppearanceSection } from "./sections/AppearanceSection";
import { GeneralSection } from "./sections/GeneralSection";
import { HelpSection } from "./sections/HelpSection";
import { ModelsSection } from "./sections/ModelsSection";
import { ProfileSection } from "./sections/ProfileSection";
import { ShortcutsSection } from "./sections/ShortcutsSection";
import { SystemSection } from "./sections/SystemSection";

/**
 * 设置弹窗（V0.4.5 B3 · F-11，改版自 B1·F-05c；V0.4.5 B5 · F-26 增「快捷键」分区）。
 *
 * 形态：**左侧分组导航（8 区 · 固定顺序）+ 右侧内容区**。
 * 分区顺序（F-26，B5 增补）：**个人 → 通用 → 外观 → 快捷键 → 模型 → 系统 → 关于 → 帮助**。
 *
 * - 个人（F-11.5）：个人信息卡（就地编辑）+ 用量占位 + 退出登录；
 * - 通用（F-11.3）：语言 + 字体大小滑杆 + 网络代理 / 存储位置 / 任务完成后的设置（占位）；
 * - 外观（F-11.4）：当前主题大预览卡 + 卡片式多主题；
 * - 快捷键（F-26 新增第 8 区）：只读快捷键表（UI 先行）；
 * - 模型（F-11.6）：**只读概览跳转卡**（当前默认模型 / 已配供应商数 / 凭证数 +
 *   「前往模型与凭证」主按钮）；写入口唯一收敛到 `/models`（D-UI5，M07-01:147-148）；
 * - 系统：运行模式 / 应用名 / 版本 + 沙箱强度明示；
 * - 关于（F-11.7）：应用名 / 版本 / 版权；
 * - 帮助：最小落地。
 *
 * 开合状态由调用方（`UserMenu`）本地 `useState` 持有，**不写入 `uiStore`**。
 * `data-testid`：`settings-dialog` / `settings-dialog-nav-<section>` / `settings-dialog-content`。
 */

/** 设置分区键（顺序即导航序；缺省 `profile`）。 */
export type SettingsSection =
  "profile" | "general" | "appearance" | "shortcuts" | "models" | "system" | "about" | "help";

/** 设置弹窗属性（§4.3 冻结接口）。 */
export interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 打开时的初始分区；缺省 `profile`（F-11.5 个人置首）。 */
  initialSection?: SettingsSection;
  /**
   * 打开即弹出「添加模型配置」表单（B-08：输入台「配置自定义模型」直达表单）。
   * 仅在 `initialSection === "models"` 时有意义。
   */
  autoOpenModelsAdd?: boolean;
}

/** 左侧导航项（SettingsWindow 复用同款分组导航）。 */
export interface SettingsNavItem {
  key: SettingsSection;
  icon: LucideIcon;
}

/** 分区导航表（顺序冻结；文案走 i18n `settings.nav.<key>`；SettingsWindow 复用）。 */
// 本文件共导出组件与常量表（`SettingsWindow` 复用该表），fast-refresh 规则不适用。
// eslint-disable-next-line react-refresh/only-export-components
export const SETTINGS_SECTIONS: readonly SettingsNavItem[] = [
  { key: "profile", icon: User },
  { key: "general", icon: Settings2 },
  { key: "appearance", icon: Palette },
  { key: "shortcuts", icon: Keyboard },
  { key: "models", icon: Boxes },
  { key: "system", icon: Cpu },
  { key: "about", icon: Info },
  { key: "help", icon: HelpCircle },
];

/** 缺省分区（F-11.5：个人置首）。 */
const DEFAULT_SECTION: SettingsSection = "profile";

/** 设置内容体（左侧导航 + 右侧分区渲染；SettingsDialog 与 SettingsWindow 共用）。 */
export function SettingsBody({
  section,
  onSectionChange,
  testIdPrefix = "settings-dialog",
  fullHeight = false,
  autoOpenModelsAdd = false,
}: {
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  testIdPrefix?: string;
  /** 挂载即打开模型分区「添加模型配置」弹窗（B-08）。 */
  autoOpenModelsAdd?: boolean;
  /**
   * `true` = 撑满父容器高度（SettingsWindow 固定高度场景）；
   * 缺省（弹窗形态）= 固定 `70vh`（B-06：切换分区高度不抖动，内容超高仅右列滚动）。
   */
  fullHeight?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-testid={`${testIdPrefix}-body`}
      className={cn("flex", fullHeight ? "h-full" : "h-[70vh]")}
    >
      {/* 左侧分组导航（8 区；最小宽度下可滚动，§8.6）。
          F-29：`fullHeight`（独立设置窗口）场景下导航列**撑满窗口高度**（去掉 70vh 上限），
          避免导航列底部残留大片空白。
          B-06：弹窗形态改为**固定高度**（`h-[70vh]`，见外层），切换分区不再抖动；
          导航与内容列各自 `h-full`，内容超高时仅右列滚动。 */}
      <nav
        aria-label={t("settings.title")}
        data-testid={`${testIdPrefix}-nav`}
        className={cn(
          "flex shrink-0 flex-col gap-1 overflow-y-auto border-r bg-muted/30 p-3",
          fullHeight ? "h-full w-[200px] max-h-none" : "h-full w-44",
        )}
      >
        {SETTINGS_SECTIONS.map((item) => {
          const active = section === item.key;
          return (
            <button
              key={item.key}
              type="button"
              data-testid={`${testIdPrefix}-nav-${item.key}`}
              aria-current={active ? "page" : undefined}
              onClick={() => onSectionChange(item.key)}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent/15 font-medium text-primary dark:text-accent"
                  : "text-muted-foreground hover:bg-accent/10 hover:text-foreground",
              )}
            >
              <item.icon className="h-4 w-4" />
              {t(`settings.nav.${item.key}`)}
            </button>
          );
        })}
      </nav>

      {/* 右侧内容区。F-29：`min-w-0` 保证长文本/表格在窄容器内不撑破两栏布局。
          B-06：`h-full + overflow-y-auto`——弹窗高度固定，内容超出时右侧出现滚动条。 */}
      <div
        data-testid={`${testIdPrefix}-content`}
        className="min-h-0 min-w-0 flex-1 overflow-y-auto p-6"
      >
        {section === "profile" ? <ProfileSection /> : null}
        {section === "general" ? <GeneralSection /> : null}
        {section === "appearance" ? <AppearanceSection /> : null}
        {section === "shortcuts" ? <ShortcutsSection /> : null}
        {section === "models" ? <ModelsSection autoOpenAdd={autoOpenModelsAdd} /> : null}
        {section === "system" ? <SystemSection /> : null}
        {section === "about" ? <AboutSection /> : null}
        {section === "help" ? <HelpSection /> : null}
      </div>
    </div>
  );
}

/**
 * 设置弹窗组件。
 *
 * 弹窗内所有交互均为**纯前端**（外观写 `uiStore`；语言写 `i18nStore`；
 * 个人显示名 / 凭证走既有 hooks；系统信息为只读展示）。
 */
export function SettingsDialog({
  open,
  onOpenChange,
  initialSection,
  autoOpenModelsAdd = false,
}: SettingsDialogProps) {
  const { t } = useTranslation();
  const [section, setSection] = useState<SettingsSection>(initialSection ?? DEFAULT_SECTION);
  // B-08：一次性「打开即弹添加模型表单」意图（离开模型分区后即失效，避免返回时反复弹）。
  const [autoAddPending, setAutoAddPending] = useState(autoOpenModelsAdd);

  // 每次弹窗「打开」时，重置到初始分区（关闭期间的分区选择不残留到下次）。
  useEffect(() => {
    if (open) {
      setSection(initialSection ?? DEFAULT_SECTION);
      setAutoAddPending(autoOpenModelsAdd);
    } else {
      setAutoAddPending(false);
    }
  }, [open, initialSection, autoOpenModelsAdd]);

  useEffect(() => {
    if (autoAddPending && section !== "models") {
      setAutoAddPending(false);
    }
  }, [autoAddPending, section]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="settings-dialog" className="max-w-3xl gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{t("settings.title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("app.tagline")}</DialogDescription>
        </DialogHeader>

        <SettingsBody
          section={section}
          onSectionChange={setSection}
          autoOpenModelsAdd={autoAddPending}
        />
      </DialogContent>
    </Dialog>
  );
}
