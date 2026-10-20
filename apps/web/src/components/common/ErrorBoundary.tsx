// ---------------------------------------------------------------------------
// 全局 / 局部错误边界（D-UI体验优化波 · WS-I · DU-9）
//
// 职责：捕获子树在**渲染期**抛出的异常，改为渲染兜底卡（标题 + 说明 + 重试按钮），
// 从而避免整页白屏。点「重试」→ 重置边界错误态，触发子树**重新挂载渲染**。
//
// 设计约束（裁定 §4.1 / §4.5）：
//   - 具名导出、无 default；
//   - 样式**全部走 token 语义类**（bg-card / text-foreground / border-border /
//     bg-muted / text-muted-foreground / Button 原语），零 hex 硬编码；
//   - 交互件挂稳定 `data-testid`（kebab-case）供 vitest 断言。
//
// React 18 中错误边界只能由 **class 组件**实现（`getDerivedStateFromError` /
// `componentDidCatch` 无 hook 等价物）。
// ---------------------------------------------------------------------------
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** 兜底渲染函数签名：入参为捕获到的错误与「重试」回调。 */
export type ErrorBoundaryFallback = (error: Error, reset: () => void) => ReactNode;

/** {@link ErrorBoundary} 属性。 */
export interface ErrorBoundaryProps {
  /** 受保护子树。 */
  children: ReactNode;
  /** 自定义兜底渲染（提供则覆盖默认兜底卡）。 */
  fallback?: ErrorBoundaryFallback;
  /** 错误上报回调；未提供时默认以 `console.error` 记录以便定位。 */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  /** 已捕获的错误；`null` = 正常态。 */
  error: Error | null;
}

/** 默认兜底卡属性。 */
export interface ErrorFallbackProps {
  /** 捕获到的错误。 */
  error: Error;
  /** 重试回调（重置边界并重新渲染子树）。 */
  onRetry: () => void;
}

/**
 * 默认兜底卡：标题 + 说明 + （可辨识的）错误信息 + 重试按钮。
 *
 * 纯展示组件，可由页面按需复用（例如作为 `fallback` 渲染函数的底座）。
 */
export function ErrorFallback({ error, onRetry }: ErrorFallbackProps) {
  return (
    <div
      role="alert"
      data-testid="error-boundary-fallback"
      className="flex min-h-[60vh] w-full items-center justify-center p-6"
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-card-foreground shadow-sm">
        <h2 className="text-[15px] font-semibold text-foreground">页面出错了</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          渲染过程中出现异常，已为你兜住白屏。可点击下方按钮重试；若仍失败请稍后再试。
        </p>
        {error.message ? (
          <p className="mt-3 break-words rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            {error.message}
          </p>
        ) : null}
        <div className="mt-5">
          <Button type="button" data-testid="error-boundary-retry" onClick={onRetry}>
            重试
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * 错误边界：包住任意子树，捕获其渲染异常并渲染兜底卡。
 *
 * 用法（顶层挂载见 `main.tsx`）：
 * ```tsx
 * <ErrorBoundary>
 *   <RouterProvider router={router} />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  /** 渲染期异常 → 进入错误态（由 React 在提交前调用）。 */
  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  /** 提交期捕获（用于日志 / 上报）。 */
  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (this.props.onError) {
      this.props.onError(error, info);
      return;
    }
    // 保留默认控制台噪声以便定位；如需接入上报，经 `onError` 注入。
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  /** 重置边界状态：清空错误并触发子树重新渲染。 */
  private readonly reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    if (this.props.fallback) {
      return this.props.fallback(error, this.reset);
    }
    return <ErrorFallback error={error} onRetry={this.reset} />;
  }
}
