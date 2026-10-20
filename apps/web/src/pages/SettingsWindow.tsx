import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import {
  SettingsBody,
  SETTINGS_SECTIONS,
  type SettingsSection,
} from "@/components/settings/SettingsDialog";
import { DocumentTitle } from "@/components/common/DocumentTitle";
import { useTranslation } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";

/** 合法分区键集合（用于校验 `?section=` 深链）。 */
const SECTION_KEYS = SETTINGS_SECTIONS.map((item) => item.key) as SettingsSection[];

/** 类型守卫：`value` 是否为合法分区。 */
function isSettingsSection(value: string | null): value is SettingsSection {
  return value !== null && (SECTION_KEYS as string[]).includes(value);
}

/**
 * 设置独立窗口页（V0.4.5 B5 · F-26.5，Q12 拍板；F-29 铺满重排）。
 *
 * - **顶层独立路由 `/settings`**：不经 `AppLayout` 外壳（无 Rail / Sidebar / Topbar），
 *   供桌面壳「独立设置窗口」加载；
 * - 深链 `?section=<key>`（缺省 `profile`）；渲染结构 = 复用 {@link SettingsBody}
 *   （与 SettingsDialog 同款左侧分组导航 + 各分区组件）；
 * - **铺满整个窗口（F-29）**：根容器 `h-screen w-screen`（去 `p-4` / `justify-center` /
 *   `max-w-3xl` 与卡片 `rounded-xl border shadow-sm`），内部两栏吃满：
 *   左侧导航列固定宽（由 `SettingsBody` 的 `fullHeight` 态提供，`w-[200px]` + 撑满高度），
 *   右侧内容区 `flex-1 min-w-0 overflow-y-auto`（滚动只发生在内容区）；
 * - 顶部整宽标题条（`设置`，与顶栏同高 42px、`border-b` 收口）；
 * - 字体大小（`uiStore.fontSize`，本波仅存档）以容器根 `font-size` 体现。
 *
 * `data-testid`：`settings-window` / `settings-window-nav-<section>` / `settings-window-content`。
 */
export function SettingsWindow() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const fontSize = useUiStore((state) => state.fontSize);

  // 读 `?section=`（缺省 profile）；非法值回落 profile。
  const rawSection = searchParams.get("section");
  const section: SettingsSection = isSettingsSection(rawSection) ? rawSection : "profile";

  /** 切换分区并同步 `?section=`（`replace`，避免污染历史）。 */
  const setSection = (next: SettingsSection): void => {
    const params = new URLSearchParams(searchParams);
    params.set("section", next);
    setSearchParams(params, { replace: true });
  };

  // 深链为非法值时归一化 URL（不改变渲染）。
  useEffect(() => {
    if (!isSettingsSection(rawSection) && rawSection !== null) {
      setSection("profile");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawSection]);

  return (
    <div
      data-testid="settings-window"
      className="flex h-screen w-screen items-stretch overflow-hidden bg-page text-foreground"
      style={{ fontSize: `${fontSize}px` }}
    >
      {/* B-01：顶层独立路由不经 `App`，故在此同步窗口标题（品牌名随语言）。 */}
      <DocumentTitle />
      {/* 纵向：标题条（整宽、42px、无卡片外框）+ 两栏主体（左导航 / 右内容）。 */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-[42px] flex-none items-center border-b border-border bg-background px-5">
          <h1 className="text-title font-semibold leading-none tracking-tight">
            {t("settings.title")}
          </h1>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden">
          {/* `fullHeight`：左侧导航列撑满窗口高度，右侧内容区 `flex-1` + `overflow-y-auto`。
              B-07/B-09：模型分区已改为**本窗内添加 + 分组列表**（凭证掩码一并并入），
              旧 `/models` 页已下线（`/models` 兼容重定向到 `/workbench`）。 */}
          <SettingsBody
            section={section}
            onSectionChange={setSection}
            testIdPrefix="settings-window"
            fullHeight
          />
        </div>
      </div>
    </div>
  );
}
