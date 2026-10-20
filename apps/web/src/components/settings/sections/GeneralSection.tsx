import { FolderOpen, FolderSync } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";

import { useTranslation } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDesktopSettings } from "@/hooks/useDesktopSettings";
import {
  checkAudioFile,
  isNotifySoundChoice,
  loadCustomNotifySound,
  loadNotifySoundChoice,
  readAudioFile,
  saveCustomNotifySound,
  saveNotifySoundChoice,
  type CustomNotifySound,
  type NotifySoundChoice,
} from "@/lib/notifySound";
import { useI18nStore } from "@/stores/i18nStore";
import type { Language } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";
import type { DesktopCloseAction } from "@/types/desktop";
import { cn } from "@/lib/cn";

/** 代理模式选项（本地 UI 占位，不落盘）。 */
type ProxyMode = "direct" | "system" | "manual";

/** 字体大小三档（px；本波仅存档 `uiStore.fontSize`，不落盘）。 */
const FONT_SIZES: readonly { value: number; labelKey: string }[] = [
  { value: 14, labelKey: "settings.general.fontSize.small" },
  { value: 16, labelKey: "settings.general.fontSize.default" },
  { value: 18, labelKey: "settings.general.fontSize.large" },
];

/**
 * 设置 · 通用分区（V0.4.5 B3 · F-11.3；B4 · F-17.2 关闭行为；B5 · F-26 增补）。
 *
 * - **语言**：真实可切（`useI18nStore().setLanguage`，F-12）；
 * - **字体大小**（F-26）：原生 range 滑杆，三档 14/16/18 px，值存 `uiStore.fontSize`
 *   （**仅存档不落盘**；SettingsWindow 容器以 CSS `font-size` 体现）；
 * - **网络代理**（F-26 新增）：Select 三选项（本地 useState 占位不落盘）；手动配置时
 *   展开代理地址输入 +「开启网络代理」按钮（toast「后续接入」）；
 * - **存储位置**（F-26 新增）：`settings.dataDir`（空 → 默认 `~/.wbtime-ai`）+
 *   「打开目录」（占位禁用）+「更改」（`pickDirectory` → `save({ dataDir })`，纯 Web 禁用）+
 *   磁盘占用进度条占位；
 * - **任务完成后的设置**（F-26 新增）：桌面通知 / 通知提示音 / 定时任务产物通知；
 *   B-05：提示音新增「自定义」并可**导入本地音效**（≤1 MB，data URL 存 localStorage，
 *   支持试听；真实任务完成播放仍待通知能力接入）；
 * - **点击关闭按钮行为**（F-17.2）：仅桌面壳内渲染（纯 Web 优雅降级）。
 */
export function GeneralSection() {
  const { t, language } = useTranslation();
  const setLanguage = useI18nStore((state) => state.setLanguage);
  const fontSize = useUiStore((state) => state.fontSize);
  const setFontSize = useUiStore((state) => state.setFontSize);
  const showToast = useUiStore((state) => state.showToast);
  const { available, settings, error, save } = useDesktopSettings();

  // 缺省「直接退出」（与壳 `DEFAULT_SETTINGS.closeAction` 一致）。
  const closeAction: DesktopCloseAction = settings?.closeAction ?? "quit";

  // F-26：网络代理（本地占位，不落盘）。
  const [proxyMode, setProxyMode] = useState<ProxyMode>("direct");
  const [proxyUrl, setProxyUrl] = useState("");

  // F-26：任务完成后的设置（B-05：提示音选择与自定义音效经 localStorage 持久化）。
  const [notifySound, setNotifySound] = useState<NotifySoundChoice>(loadNotifySoundChoice);
  const [customSound, setCustomSound] = useState<CustomNotifySound | null>(loadCustomNotifySound);
  const [notifyTaskDone, setNotifyTaskDone] = useState(true);
  /** 隐藏的文件选择器（导入自定义音效）。 */
  const soundFileRef = useRef<HTMLInputElement>(null);

  const proxyManual = proxyMode === "manual";

  /** 切换提示音：选中「自定义」且尚无文件时，直接拉起文件选择（同一用户手势内）。 */
  const handleNotifySoundChange = (value: string): void => {
    if (!isNotifySoundChoice(value)) {
      return;
    }
    setNotifySound(value);
    saveNotifySoundChoice(value);
    if (value === "custom" && !customSound) {
      soundFileRef.current?.click();
    }
  };

  /** 导入 / 更换自定义音效：校验类型与体积 → 转 data URL → 落 localStorage。 */
  const handleSoundFileChange = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    // 清空 value：允许连续选择同一文件（否则 change 不触发）。
    event.target.value = "";
    if (!file) {
      return;
    }

    const check = checkAudioFile(file);
    if (!check.ok) {
      showToast({
        title: t("settings.general.notification.sound.custom.invalid"),
        description:
          check.reason === "size"
            ? t("settings.general.notification.sound.custom.tooLarge")
            : t("settings.general.notification.sound.custom.invalidType"),
        variant: "destructive",
      });
      return;
    }

    const dataUrl = await readAudioFile(file);
    if (!dataUrl) {
      showToast({
        title: t("settings.general.notification.sound.custom.readFailed"),
        variant: "destructive",
      });
      return;
    }

    const sound: CustomNotifySound = { name: file.name, dataUrl };
    setCustomSound(sound);
    if (!saveCustomNotifySound(sound)) {
      showToast({
        title: t("settings.general.notification.sound.custom.storageFailed"),
        variant: "destructive",
      });
    }
  };

  /** 试听当前自定义音效。 */
  const handlePreviewSound = (): void => {
    if (!customSound) {
      return;
    }
    void new Audio(customSound.dataUrl).play().catch(() => {
      showToast({
        title: t("settings.general.notification.sound.custom.playFailed"),
        variant: "destructive",
      });
    });
  };

  /** 「开启网络代理」占位：本轮不接真实代理，toast 提示后续接入。 */
  const handleEnableProxy = (): void => {
    showToast({ title: t("settings.general.proxy.pendingToast") });
  };

  /** 更改存储位置：选目录 → 保存 `{ dataDir }`（仅桌面壳内可用）。 */
  const handleChangeDataDir = async (): Promise<void> => {
    const picked = await window.wbtimeAiDesktop?.pickDirectory?.();
    if (picked) {
      const next = await save({ dataDir: picked });
      if (next) {
        showToast({ title: t("settings.general.storage.updatedToast") });
      }
    }
  };

  return (
    <section
      aria-label={t("settings.general.title")}
      data-testid="settings-general"
      className="space-y-5"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.general.title")}</h3>

      <div className="flex items-center justify-between gap-4">
        <Label htmlFor="settings-language">{t("settings.general.language")}</Label>
        <Select value={language} onValueChange={(value) => setLanguage(value as Language)}>
          <SelectTrigger id="settings-language" data-testid="settings-language" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="en">English</SelectItem>
            <SelectItem value="zh-CN">简体中文</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 字体大小（F-26）：原生 range 滑杆，三档 14/16/18，仅存档。 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="settings-font-size-range">{t("settings.general.fontSize")}</Label>
          <span data-testid="settings-font-size" className="text-xs text-muted-foreground">
            {fontSize}px · {t(`settings.general.fontSize.${fontIndexLabel(fontSize)}`)}
          </span>
        </div>
        <input
          id="settings-font-size-range"
          data-testid="settings-font-size-range"
          type="range"
          min={14}
          max={18}
          step={2}
          value={fontSize}
          onChange={(event) => setFontSize(Number(event.target.value))}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
        />
        <div className="flex justify-between text-[11px] text-muted-foreground">
          {FONT_SIZES.map((item) => (
            <span key={item.value}>{t(item.labelKey)}</span>
          ))}
        </div>
      </div>

      {/* 网络代理（F-26 新增；本地占位不落盘）。 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="settings-proxy-mode">{t("settings.general.proxy")}</Label>
          <Select value={proxyMode} onValueChange={(value) => setProxyMode(value as ProxyMode)}>
            <SelectTrigger
              id="settings-proxy-mode"
              data-testid="settings-proxy-mode"
              className="w-40"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="direct">{t("settings.general.proxy.direct")}</SelectItem>
              <SelectItem value="system">{t("settings.general.proxy.system")}</SelectItem>
              <SelectItem value="manual">{t("settings.general.proxy.manual")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {proxyManual ? (
          <div className="space-y-2 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <Input
              data-testid="settings-proxy-url"
              value={proxyUrl}
              onChange={(event) => setProxyUrl(event.target.value)}
              placeholder={t("settings.general.proxy.placeholder")}
            />
            <Button
              type="button"
              size="sm"
              data-testid="settings-proxy-enable"
              onClick={handleEnableProxy}
            >
              {t("settings.general.proxy.enable")}
            </Button>
          </div>
        ) : null}
      </div>

      {/* 存储位置（F-26 新增；读写经桌面壳，纯 Web 禁用）。 */}
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("settings.general.storage")}</p>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
          <span
            data-testid="settings-storage-dir"
            className="truncate font-mono text-xs text-foreground"
          >
            {settings?.dataDir ? settings.dataDir : "~/.wbtime-ai"}
          </span>
          <span className="flex flex-none items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="settings-storage-open"
              disabled
              title={t("settings.general.storage.pending")}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {t("settings.general.storage.open")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="settings-storage-change"
              disabled={!available}
              title={available ? undefined : t("appMenu.desktopOnly")}
              onClick={() => void handleChangeDataDir()}
            >
              <FolderSync className="h-3.5 w-3.5" />
              {t("settings.general.storage.change")}
            </Button>
          </span>
        </div>
        {/* 磁盘占用进度条（占位）。 */}
        <div className="space-y-1">
          <div
            data-testid="settings-storage-usage-bar"
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={0}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="h-full w-0 bg-primary" />
          </div>
          <p className="text-[11px] text-muted-foreground">
            {t("settings.general.storage.usageNote")}
          </p>
        </div>
      </div>

      {/* 任务完成后的设置（F-26 新增；全部 UI 占位不落盘）。 */}
      <div className="space-y-3 rounded-lg border border-border bg-muted/30 px-4 py-3">
        <p className="text-sm font-medium text-foreground">{t("settings.general.notification")}</p>
        <div className="flex items-center justify-between gap-4">
          <span className="text-xs text-foreground">
            {t("settings.general.notification.desktop")}
          </span>
          <button
            type="button"
            data-testid="settings-notification-system-link"
            disabled
            title={t("settings.general.notification.pending")}
            className="text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            {t("settings.general.notification.goSystem")} ↗
          </button>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-xs text-foreground">
            {t("settings.general.notification.sound")}
          </span>
          <Select value={notifySound} onValueChange={handleNotifySoundChange}>
            <SelectTrigger data-testid="settings-notification-sound" className="h-8 w-32 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="dynamic">
                {t("settings.general.notification.sound.dynamic")}
              </SelectItem>
              <SelectItem value="crisp">
                {t("settings.general.notification.sound.crisp")}
              </SelectItem>
              <SelectItem value="mute">{t("settings.general.notification.sound.mute")}</SelectItem>
              <SelectItem value="custom">
                {t("settings.general.notification.sound.custom")}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* B-05：「自定义」音效文件行（选中自定义时出现）。 */}
        {notifySound === "custom" ? (
          <div
            className="flex items-center justify-between gap-4"
            data-testid="settings-notification-sound-custom"
          >
            <span
              className="min-w-0 truncate text-xs text-muted-foreground"
              data-testid="settings-notification-sound-custom-name"
              title={customSound?.name}
            >
              {customSound
                ? customSound.name
                : t("settings.general.notification.sound.custom.empty")}
            </span>
            <span className="flex flex-none items-center gap-1.5">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                data-testid="settings-notification-sound-custom-import"
                onClick={() => soundFileRef.current?.click()}
              >
                {customSound
                  ? t("settings.general.notification.sound.custom.replace")
                  : t("settings.general.notification.sound.custom.import")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                data-testid="settings-notification-sound-custom-preview"
                disabled={!customSound}
                onClick={handlePreviewSound}
              >
                {t("settings.general.notification.sound.custom.preview")}
              </Button>
            </span>
            <input
              ref={soundFileRef}
              type="file"
              accept="audio/*"
              className="hidden"
              data-testid="settings-notification-sound-custom-file"
              onChange={(event) => void handleSoundFileChange(event)}
            />
          </div>
        ) : null}
        <div className="flex items-center justify-between gap-4">
          <span className="text-xs text-foreground">
            {t("settings.general.notification.taskDone")}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={notifyTaskDone}
            data-testid="settings-notification-taskdone"
            onClick={() => setNotifyTaskDone((previous) => !previous)}
            className={cn(
              "relative h-5 w-9 flex-none rounded-full transition-colors",
              notifyTaskDone ? "bg-primary" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-background transition-all",
                notifyTaskDone ? "left-[18px]" : "left-0.5",
              )}
            />
          </button>
        </div>
      </div>

      {/* F-17.2：点击关闭按钮行为（仅桌面壳内渲染；纯 Web 隐藏，优雅降级）。 */}
      {available ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="settings-close-action">{t("settings.general.closeAction")}</Label>
            <Select
              value={closeAction}
              onValueChange={(value) => void save({ closeAction: value as DesktopCloseAction })}
            >
              <SelectTrigger
                id="settings-close-action"
                data-testid="settings-close-action"
                className="w-40"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="quit">{t("settings.general.closeAction.quit")}</SelectItem>
                <SelectItem value="tray">{t("settings.general.closeAction.tray")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error ? (
            <p className="text-xs text-destructive" data-testid="settings-close-action-error">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** 字体档位 key（14 → small / 16 → default / 18 → large）。 */
function fontIndexLabel(size: number): "small" | "default" | "large" {
  if (size <= 14) {
    return "small";
  }
  if (size >= 18) {
    return "large";
  }
  return "default";
}
