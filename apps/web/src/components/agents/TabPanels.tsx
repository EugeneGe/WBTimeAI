import { AlertCircle, Info } from "lucide-react";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";

/**
 * 三 Tab 统一骨架 / 错误 / 空态面板（V0.4.6 B-15 · 三 Tab 统一改版）。
 *
 * 专家 / 技能 / 连接器三个 Tab 共用同一套非正常态形态（同尺寸骨架、同错误面板、
 * 同空态面板节奏），只替换图标 / 文案 / CTA 与 testid。
 */

/** 六卡骨架网格（与内容网格同列数 / 同间距）。 */
export function TabSkeleton({ testId, height = 132 }: { testId: string; height?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid={testId}>
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="w-full rounded-xl" style={{ height }} />
      ))}
    </div>
  );
}

/** {@link TabErrorPanel} 属性。 */
export interface TabErrorPanelProps {
  /** 面板 testid（`agents-<tab>-error`）。 */
  testId: string;
  /** 重试按钮 testid（`agents-<tab>-retry`）。 */
  retryTestId: string;
  /** 查询错误对象（经 `toApiError` 归一化取 message）。 */
  error: unknown;
  /** 重试回调（透传 `refetch`）。 */
  onRetry: () => void;
}

/** 错误面板（优先于空态渲染）：图标 + 加载失败 + 归一化 message + 重试。 */
export function TabErrorPanel({ testId, retryTestId, error, onRetry }: TabErrorPanelProps) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card px-6 py-12 text-center"
      data-testid={testId}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertCircle aria-hidden className="h-5 w-5" />
      </span>
      <h2 className="text-sm font-semibold text-foreground">{t("agents.panel.loadFailed")}</h2>
      <p className="max-w-md text-xs text-muted-foreground">{toApiError(error).message}</p>
      <button
        type="button"
        data-testid={retryTestId}
        onClick={onRetry}
        className="mt-1 h-8 rounded-lg border border-input bg-background px-3 text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("agents.panel.retry")}
      </button>
    </div>
  );
}

/** {@link TabEmptyPanel} 属性。 */
export interface TabEmptyPanelProps {
  /** 面板 testid（`agents-<tab>-empty`）。 */
  testId: string;
  /** 空态图标（lucide 节点）。 */
  icon: ReactNode;
  /** 标题（已翻译文案）。 */
  title: string;
  /** 一句说明（已翻译文案）。 */
  description: string;
  /** 唯一 CTA 文案。 */
  ctaLabel: string;
  /** CTA testid。 */
  ctaTestId: string;
  /** CTA 回调（打开对应弹窗 / 向导）。 */
  onCta?: () => void;
}

/** 真空态面板（三 Tab 同构）：图标 + 标题 + 说明 + 唯一 CTA；工具栏在空态不渲染。 */
export function TabEmptyPanel({
  testId,
  icon,
  title,
  description,
  ctaLabel,
  ctaTestId,
  onCta,
}: TabEmptyPanelProps) {
  return (
    <div className="flex items-center justify-center px-2 py-8">
      <div
        className="w-full max-w-[560px] rounded-2xl border border-dashed border-border bg-card px-7 py-6 text-center"
        data-testid={testId}
      >
        <span className="mx-auto mb-2.5 flex h-11 w-11 items-center justify-center rounded-xl bg-muted text-primary">
          {icon}
        </span>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
        <button
          type="button"
          data-testid={ctaTestId}
          onClick={onCta}
          className="mt-3.5 inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {ctaLabel}
        </button>
      </div>
    </div>
  );
}

/** 「筛选后为空」面板属性。 */
export interface TabNoMatchPanelProps {
  /** 面板 testid（`agents-<tab>-no-match`）。 */
  testId: string;
  /** 「没有匹配的 …」文案（已翻译）。 */
  message: string;
  /** 清除筛选按钮 testid。 */
  clearTestId: string;
  /** 清除筛选回调。 */
  onClear: () => void;
}

/** 筛选空面板：提示 + 清除筛选（恢复默认 query / 筛选档）。 */
export function TabNoMatchPanel({ testId, message, clearTestId, onClear }: TabNoMatchPanelProps) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card px-6 py-10 text-center"
      data-testid={testId}
    >
      <p className="text-sm text-foreground">{message}</p>
      <button
        type="button"
        data-testid={clearTestId}
        onClick={onClear}
        className="h-8 rounded-lg border border-input bg-background px-3 text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("agents.panel.clearFilters")}
      </button>
    </div>
  );
}

/** 底部能力说明条属性。 */
export interface TabHintBarProps {
  /** 说明文案（已翻译，调用方负责 i18n）。 */
  text: string;
}

/** 底部能力说明条（Info 图标 + 浅底细边，不抢视觉）。 */
export function TabHintBar({ text }: TabHintBarProps) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
      <Info aria-hidden className="mt-px h-3.5 w-3.5 flex-none text-primary" />
      <p>{text}</p>
    </div>
  );
}
