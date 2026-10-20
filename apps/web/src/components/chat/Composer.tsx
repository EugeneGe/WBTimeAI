import {
  ArrowUp,
  Layers,
  MessageSquare,
  Mic,
  Paperclip,
  Plug,
  Plus,
  Square,
  Users,
  Wrench,
} from "lucide-react";
import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import { ExpertChip, type ExpertOption } from "@/components/chat/ExpertChip";
import { ModelPicker, type ModelOption } from "@/components/chat/ModelPicker";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAgents } from "@/hooks/useAgents";
import { useMcpServers } from "@/hooks/useMcp";
import { useProviders } from "@/hooks/useModels";
import { useSkills } from "@/hooks/useSkills";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import { hasShellAction, invokeShellAction } from "@/lib/shellAction";
import { useUiStore } from "@/stores/uiStore";

/** Composer 冻结签名（§4.4）。 */
export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  streaming?: boolean;
  onCancel?: () => void;
  agentId?: string | null;
  onAgentChange?: (id: string | null) => void;
}

/**
 * 暂存提示词草稿键（localStorage）。
 *
 * ⚠️ V0.4.5 B3 · F-14.3 已**移除**「暂存提示词」UI 及其读写；常量**保留**（不破坏既有导入）。
 */
export const COMPOSER_DRAFT_KEY = "wbtime-ai.composer.draft";

/** 输入框最小 / 最大高度（px；F-14.4：默认高度 + 随文增高有上限 + 内部滚动）。 */
const MIN_INPUT_HEIGHT = 44;
const MAX_INPUT_HEIGHT = 200;

/** 二级子项（技能 / 专家 / 连接器：动态数据走 `label`；模式等静态项走 `labelKey`）。 */
interface PlusSubItem {
  id: string;
  /** 动态数据项展示名（专家 / 技能 / 连接器）。 */
  label?: string;
  /** 静态项 i18n key（模式：`composer.mode.*`）。 */
  labelKey?: string;
}

/**
 * ＋ 菜单项（F-05a 二级联动；`hasSubmenu` 决定单级 or 二级；
 * 单级 / 二级之间在「模式」前加分隔线）。
 */
const PLUS_ITEMS = [
  { key: "add-file", labelKey: "composer.plus.addFile", icon: Paperclip, hasSubmenu: false },
  { key: "ref-file", labelKey: "composer.plus.refFile", icon: MessageSquare, hasSubmenu: false },
  { key: "mode", labelKey: "composer.plus.mode", icon: Layers, hasSubmenu: true },
  { key: "expert", labelKey: "composer.plus.expert", icon: Users, hasSubmenu: true },
  { key: "skill", labelKey: "composer.plus.skill", icon: Wrench, hasSubmenu: true },
  { key: "connector", labelKey: "composer.plus.connector", icon: Plug, hasSubmenu: true },
] as const;

type PlusItemKey = (typeof PLUS_ITEMS)[number]["key"];

/** 「模式」二级静态项（假定 A-5：静态常量；文案走 i18n `composer.mode.*`）。 */
const MODE_OPTIONS: PlusSubItem[] = [
  { id: "fast", labelKey: "composer.mode.fast" },
  { id: "standard", labelKey: "composer.mode.standard" },
  { id: "deep", labelKey: "composer.mode.deep" },
];

/**
 * 输入台 Composer（D-UI 体验优化波 · WS-C / DU-6，§4.4 冻结签名）。
 *
 * 交互态（对照设计屏 02）：
 * ① ＋弹出（添加文件/引用对话中的文件/模式/专家/技能/连接器）；
 * ② 权限下拉（默认权限/完全访问）；③ 专家位（默认空，选中显示 chip + 搜索面板）；
 * ④ 模型选择；⑤ 语音转文字（UI 壳）；⑥ 发送（`Ctrl+Enter`）；streaming 态显取消。
 *
 * V0.4.5 B3 · F-14 改版：
 * - **F-14.1**：模型选择器仅「图标 + 名称」（去 `rate` / `badge`）；
 * - **F-14.2 / B-08**：「配置自定义模型」→ **设置·模型**（壳内开独立设置窗；纯 Web 就地打开
 *   `SettingsDialog` 并直达「添加模型配置」表单）。B-07 起设置·模型已支持页内添加，
 *   不再跳转 `/models`——入口与设置保持统一。
 * - **F-14.3**：**移除**「暂存提示词 / 上下文用量 / 增强提示词」三项；
 * - **F-14.4**：输入框两侧留白、默认高度、随文字增高（有上限）、内部右侧滚动条。
 *
 * 浮层统一消费 WS-F 原语：＋/权限 → `ui/dropdown-menu`，专家/模型 → `ui/popover`（§4.3 补遗）。
 * 数据：专家位复用 `useAgents`（只读）、模型选择复用 `useModels.useProviders`（只读）。
 */
export function Composer({
  value,
  onChange,
  onSend,
  streaming = false,
  onCancel,
  agentId = null,
  onAgentChange,
}: ComposerProps) {
  const { t } = useTranslation();
  const [expertOpen, setExpertOpen] = useState(false);
  const [permission, setPermission] = useState<"default" | "full">("default");
  const [listening, setListening] = useState(false);
  const [modelId, setModelId] = useState<string | null>(null);
  // B-08：Web 形态下就地打开设置·模型（并直达「添加模型配置」表单）。
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);

  /**
   * B-08：模型「配置自定义模型」→ 设置·模型（**不再跳转 `/models`**）。
   *
   * - 桌面壳：`shellAction(open-settings, models)` 打开独立设置窗（壳契约既有）；
   * - 纯 Web：就地打开 `SettingsDialog`，`autoOpenModelsAdd` 直达添加表单。
   *
   * 变更背景：B-07 起设置·模型已支持页内添加，`/models` 不再是唯一写入口；
   * 用户实测要求入口与设置保持统一。
   */
  const openModelSettings = (): void => {
    if (hasShellAction()) {
      invokeShellAction({ action: "open-settings", section: "models" });
      return;
    }
    setModelSettingsOpen(true);
  };

  // F-14.4：受控高度 textarea 引用。
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 只读数据源（既有 hooks）。
  const { data: agents, isLoading: agentsLoading } = useAgents();
  const { data: providers, isLoading: providersLoading } = useProviders();
  const { data: skills } = useSkills();
  const { data: connectors } = useMcpServers();

  const experts: ExpertOption[] = (agents ?? []).map((agent) => ({
    id: agent.id,
    name: agent.name,
  }));
  const skillOptions: PlusSubItem[] = (skills ?? []).map((skill) => ({
    id: skill.id,
    label: skill.display_name || skill.name,
  }));
  const connectorOptions: PlusSubItem[] = (connectors ?? []).map((server) => ({
    id: server.id,
    label: server.name,
  }));

  /** 取一级条目对应的二级项（假定 A-5）。 */
  const subItemsFor = (key: PlusItemKey): PlusSubItem[] => {
    switch (key) {
      case "mode":
        return MODE_OPTIONS;
      case "expert":
        return experts.map((expert) => ({ id: expert.id, label: expert.name }));
      case "skill":
        return skillOptions;
      case "connector":
        return connectorOptions;
      default:
        return [];
    }
  };

  // F-14.1：模型选项仅 id + 名称（不展示折率 / 费率）。
  // V0.4.5 B4 · F-20.2：**移除** `FALLBACK_MODELS` 兜底——未配置 provider 时列表为空，
  // 由 `ModelPicker` 呈现空态引导（「未配置模型，去设置添加」）。
  const providerModels: ModelOption[] = (providers ?? []).map((provider) => ({
    id: provider.id,
    name: provider.name,
  }));
  const models = providerModels;

  const canSend = value.trim().length > 0 && !streaming;

  // F-14.4：随文本增高（有上限）；内部 `overflow-y-auto` 承接过高内容。
  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }
    element.style.height = "auto";
    const nextHeight = Math.min(Math.max(element.scrollHeight, MIN_INPUT_HEIGHT), MAX_INPUT_HEIGHT);
    element.style.height = `${nextHeight}px`;
  }, [value]);

  const handleSend = (): void => {
    if (!canSend) {
      return;
    }
    onSend();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    // V0.4.5 B4 · F-20.3：外层**居中 + 适度最大宽**（两侧留白，随容器自适应）。
    <div data-testid="composer" className="mx-auto w-full max-w-[768px]">
      {/* 输入台主体。 */}
      <div className="rounded-xl border border-border bg-card p-3">
        {/* F-14.4：两侧留白（px-2）、默认高度、随文增高（有上限）、内部右侧滚动条。 */}
        <textarea
          ref={textareaRef}
          data-testid="composer-input"
          rows={1}
          value={value}
          placeholder={t("composer.placeholder")}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          style={{ maxHeight: MAX_INPUT_HEIGHT }}
          className="min-h-[44px] w-full resize-none overflow-y-auto bg-transparent px-2 pb-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />

        <div className="flex items-center gap-2 border-t border-border pt-2">
          {/* ① ＋ 弹出菜单（ui/dropdown-menu）。
              F-05a：单级（添加文件 / 引用对话中的文件）+ 二级（模式 / 专家 / 技能 / 连接器）；
              悬停一级条目 → 右侧展开二级列表；点二级项父子菜单一并关闭。 */}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="composer-plus"
                aria-label={t("composer.more")}
                className="flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full border border-muted-foreground text-muted-foreground hover:bg-accent/15"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={8}
              data-testid="composer-plus-menu"
              className="w-[206px]"
            >
              {/* 单级条目：添加文件 / 引用对话中的文件。 */}
              {PLUS_ITEMS.filter((item) => !item.hasSubmenu).map((item) => {
                const Icon = item.icon;
                return (
                  <DropdownMenuItem key={item.key} data-testid={`composer-plus-${item.key}`}>
                    <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                    <span>{t(item.labelKey)}</span>
                  </DropdownMenuItem>
                );
              })}

              <DropdownMenuSeparator />

              {/* 二级条目：模式 / 专家 / 技能 / 连接器（radix 原生 hover 展开）。 */}
              {PLUS_ITEMS.filter((item) => item.hasSubmenu).map((item) => {
                const Icon = item.icon;
                const subItems = subItemsFor(item.key);
                return (
                  <DropdownMenuSub key={item.key}>
                    <DropdownMenuSubTrigger data-testid={`composer-plus-${item.key}`}>
                      <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                      <span>{t(item.labelKey)}</span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent
                      data-testid={`composer-plus-sub-${item.key}`}
                      className="w-[196px]"
                    >
                      {subItems.length > 0 ? (
                        subItems.map((sub) => (
                          <DropdownMenuItem
                            key={sub.id}
                            data-testid={`composer-plus-sub-${item.key}-item-${sub.id}`}
                            // 点击二级项（radix 默认关闭整棵菜单）；专家项顺带选中该专家。
                            onSelect={() => {
                              if (item.key === "expert") {
                                onAgentChange?.(sub.id);
                              }
                            }}
                          >
                            {/* 静态项走 `labelKey`（模式），动态数据项走 `label`。 */}
                            {sub.labelKey ? t(sub.labelKey) : sub.label}
                          </DropdownMenuItem>
                        ))
                      ) : (
                        <DropdownMenuItem disabled>暂无可用项</DropdownMenuItem>
                      )}
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* ② 权限下拉（ui/dropdown-menu）。 */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="composer-permission"
                className="flex flex-none items-center gap-1.5 whitespace-nowrap rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
              >
                <span className="h-2 w-2 flex-none rounded-full border border-muted-foreground" />
                {permission === "default"
                  ? t("composer.permission.default")
                  : t("composer.permission.full")}
                <span aria-hidden>⌄</span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              side="top"
              sideOffset={8}
              data-testid="composer-permission-menu"
              className="w-40"
            >
              <DropdownMenuRadioGroup
                value={permission}
                onValueChange={(next) => setPermission(next as "default" | "full")}
              >
                <DropdownMenuRadioItem value="default" data-testid="composer-permission-default">
                  {t("composer.permission.default")}
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="full" data-testid="composer-permission-full">
                  {t("composer.permission.full")}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* ③ 专家位（ui/popover；点击已选 chip 打开搜索面板）。 */}
          <ExpertChip
            experts={experts}
            value={agentId}
            onChange={(id) => onAgentChange?.(id)}
            open={expertOpen}
            onOpenChange={setExpertOpen}
            loading={agentsLoading}
          />

          <span className="flex-1" />

          {/* ④ 模型选择（ui/popover；F-14.1 仅图标+名称；F-14.2 配置 → 设置·模型页）。 */}
          <ModelPicker
            models={models}
            value={modelId}
            onChange={setModelId}
            loading={providersLoading}
            onConfigure={openModelSettings}
          />

          {/* ⑤ 语音转文字（UI 壳；Bug6c：点击明示演示态，不接真实 STT）。 */}
          <button
            type="button"
            data-testid="composer-voice"
            title={t("composer.voice.title")}
            aria-label={t("composer.voice.aria")}
            aria-pressed={listening}
            onClick={() => {
              setListening((on) => !on);
              useUiStore.getState().showToast({
                title: t("composer.voice.demoToast"),
              });
            }}
            className={cn(
              "flex h-6 w-6 flex-none items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent/15",
              listening ? "text-primary" : "",
            )}
          >
            <Mic className="h-3.5 w-3.5" />
          </button>

          {/* ⑥ 发送 / streaming 取消。 */}
          {streaming ? (
            <button
              type="button"
              data-testid="composer-cancel"
              onClick={() => onCancel?.()}
              className="flex h-[26px] flex-none items-center gap-1 rounded-full border border-border px-3 text-xs text-foreground hover:bg-accent/15"
            >
              <Square className="h-3 w-3" />
              {t("common.cancel")}
            </button>
          ) : (
            <button
              type="button"
              data-testid="composer-send"
              aria-label={t("composer.send")}
              disabled={!canSend}
              onClick={handleSend}
              className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-50"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* B-08：「配置自定义模型」→ 页内设置·模型（Web 直达添加表单；壳内走独立设置窗）。 */}
      <SettingsDialog
        open={modelSettingsOpen}
        onOpenChange={setModelSettingsOpen}
        initialSection="models"
        autoOpenModelsAdd
      />
    </div>
  );
}
