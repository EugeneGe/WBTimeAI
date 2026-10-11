import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

import { usePermission } from "@/lib/permission";

/** 无权占位提示。 */
function PermissionDenied({ code }: { code: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-muted-foreground">
      <ShieldAlert className="h-6 w-6" />
      <p className="text-sm">缺少权限：{code}</p>
    </div>
  );
}

/** 权限守卫：缺失权限码 → 阻止渲染（可传 `fallback` 自定义）。 */
export function RequirePermission({
  code,
  children,
  fallback,
}: {
  code: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { can } = usePermission();
  if (!can(code)) {
    return <>{fallback ?? <PermissionDenied code={code} />}</>;
  }
  return <>{children}</>;
}
