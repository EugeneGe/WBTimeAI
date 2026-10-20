import * as ToastPrimitives from "@radix-ui/react-toast";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";
import * as React from "react";

import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/uiStore";

/**
 * shadcn/ui Toast（radix 原语，§4.3 冻结导出名）。
 *
 * **迁移等价策略**：`uiStore.showToast / dismissToast` 保持原签名与语义不变，
 * 调用方零改动；`Toaster` 订阅该 store 的单条 toast 并渲染，
 * `useToast()` 亦桥接到同一 store（多标签/多 toast 需求不在此波范围）。
 */
const ToastProvider = ToastPrimitives.Provider;

const ToastViewport = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Viewport>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Viewport>
>(({ className, ...props }, ref) => (
  <ToastPrimitives.Viewport
    ref={ref}
    className={cn(
      "fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col-reverse gap-2 p-4 sm:max-w-sm",
      className,
    )}
    {...props}
  />
));
ToastViewport.displayName = ToastPrimitives.Viewport.displayName;

const toastVariants = cva(
  "group pointer-events-auto relative flex w-full items-start justify-between gap-3 overflow-hidden rounded-2xl border p-4 pr-8 shadow-lg transition-all data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
  {
    variants: {
      variant: {
        default: "border bg-card text-card-foreground",
        destructive: "border-destructive bg-destructive text-destructive-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

const Toast = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Root> & VariantProps<typeof toastVariants>
>(({ className, variant, ...props }, ref) => (
  <ToastPrimitives.Root
    ref={ref}
    className={cn(toastVariants({ variant }), className)}
    {...props}
  />
));
Toast.displayName = ToastPrimitives.Root.displayName;

const ToastTitle = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Title>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Title>
>(({ className, ...props }, ref) => (
  <ToastPrimitives.Title ref={ref} className={cn("text-sm font-medium", className)} {...props} />
));
ToastTitle.displayName = ToastPrimitives.Title.displayName;

const ToastDescription = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Description>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Description>
>(({ className, ...props }, ref) => (
  <ToastPrimitives.Description
    ref={ref}
    className={cn("text-xs text-muted-foreground", className)}
    {...props}
  />
));
ToastDescription.displayName = ToastPrimitives.Description.displayName;

const ToastClose = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Close>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Close>
>(({ className, ...props }, ref) => {
  // hook 位于组件函数体顶层（forwardRef 渲染函数内合法，每次渲染调用顺序稳定）。
  const { t } = useTranslation();
  return (
    <ToastPrimitives.Close
      ref={ref}
      className={cn(
        "absolute right-2 top-2 rounded-md p-0.5 text-foreground/60 opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring",
        className,
      )}
      toast-close=""
      {...props}
    >
      <X className="h-4 w-4" />
      <span className="sr-only">{t("common.close")}</span>
    </ToastPrimitives.Close>
  );
});
ToastClose.displayName = ToastPrimitives.Close.displayName;

const ToastAction = React.forwardRef<
  React.ElementRef<typeof ToastPrimitives.Action>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitives.Action>
>(({ className, ...props }, ref) => (
  <ToastPrimitives.Action
    ref={ref}
    className={cn(
      "inline-flex h-8 shrink-0 items-center justify-center rounded-md border bg-transparent px-3 text-sm font-medium transition-colors hover:bg-secondary focus:outline-none focus:ring-2 focus:ring-ring disabled:pointer-events-none disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
ToastAction.displayName = ToastPrimitives.Action.displayName;

/** `useToast()` 入参。 */
export interface ToastOptions {
  title: string;
  description?: string;
  variant?: "default" | "destructive";
  duration?: number;
  action?: React.ReactNode;
}

/** `useToast().toast()` 返回值。 */
export interface ToastHandle {
  id: string;
  dismiss: () => void;
}

/** `useToast()` 返回值。 */
export interface UseToastReturn {
  toast: (options: ToastOptions) => ToastHandle;
  dismiss: (id?: string) => void;
}

/**
 * 轻提示 hook（§4.3 冻结签名 `useToast() → { toast, dismiss }`）。
 *
 * 桥接 `uiStore`（保持与既有 `showToast/dismissToast` 同源，行为等价）。
 */
export function useToast(): UseToastReturn {
  return React.useMemo<UseToastReturn>(() => {
    const toast = (options: ToastOptions): ToastHandle => {
      const id = String(Date.now());
      useUiStore.getState().showToast({
        id,
        title: options.title,
        description: options.description,
        variant: options.variant ?? "default",
      });
      return { id, dismiss: () => useUiStore.getState().dismissToast() };
    };
    const dismiss = (): void => useUiStore.getState().dismissToast();
    return { toast, dismiss };
  }, []);
}

/**
 * 全局 Toaster 挂载点（无参）；订阅 `uiStore.toast` 渲染，手动关闭前常驻
 * （与迁移前 `AppLayout` 内联 toast 行为一致）。
 */
export function Toaster(): JSX.Element {
  const toastMessage = useUiStore((state) => state.toast);
  const dismissToast = useUiStore((state) => state.dismissToast);

  return (
    <ToastProvider swipeDirection="right">
      {toastMessage ? (
        <Toast
          key={toastMessage.id}
          data-testid="toaster-toast"
          variant={toastMessage.variant ?? "default"}
          open
          duration={Number.POSITIVE_INFINITY}
          onOpenChange={(open) => {
            if (!open) {
              dismissToast();
            }
          }}
        >
          <div className="grid gap-1">
            <ToastTitle>{toastMessage.title}</ToastTitle>
            {toastMessage.description ? (
              <ToastDescription>{toastMessage.description}</ToastDescription>
            ) : null}
          </div>
          <ToastClose data-testid="toaster-toast-close" />
        </Toast>
      ) : null}
      <ToastViewport />
    </ToastProvider>
  );
}

export {
  ToastProvider,
  Toast,
  ToastTitle,
  ToastDescription,
  ToastClose,
  ToastAction,
  ToastViewport,
};
