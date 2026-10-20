import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * shadcn/ui Skeleton（纯 `div`，零依赖，§4.3）。
 *
 * 载入态占位块：`<Skeleton className="h-4 w-32" />`。
 */
const Skeleton = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />
  ),
);
Skeleton.displayName = "Skeleton";

export { Skeleton };
