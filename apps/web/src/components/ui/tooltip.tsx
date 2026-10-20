import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * shadcn/ui Tooltip（radix 原语，WS-F 基础件层）。
 *
 * 消费示例（WS-L Rail 悬停提示）：
 * ```tsx
 * <TooltipProvider delayDuration={250}>
 *   <Tooltip>
 *     <TooltipTrigger asChild><button …/></TooltipTrigger>
 *     <TooltipContent>工作台</TooltipContent>
 *   </Tooltip>
 * </TooltipProvider>
 * ```
 */
const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "z-50 overflow-hidden rounded-lg border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md animate-in fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
      className,
    )}
    {...props}
  />
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
