import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

import { useTranslation } from "@/i18n";
import { usePermission } from "@/lib/permission";

/**
 * 无权占位提示（默认 `fallback`）。
 *
 * 文案走 i18n（`common.permissionDenied`，`{code}` 插值），**不再硬编码**
 * 中文串——否则切 `en` 时残留中文且破坏语言无关断言。
 *
 * 稳定锚点：`data-testid="permission-denied"` + `data-permission-code={code}`，
 * 供测试以「权限码」而非「文案」断言（语言无关）。
 */
function PermissionDenied({ code }: { code: string }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-muted-foreground"
      data-testid="permission-denied"
      data-permission-code={code}
    >
      <ShieldAlert className="h-6 w-6" />
      <p className="text-sm">{t("common.permissionDenied", { code })}</p>
    </div>
  );
}

/**
 * 权限守卫：缺失权限码 → 阻止渲染（可传 `fallback` 自定义）。
 *
 * `fallback` 为**三态**语义（不可用 `??` / `||` 合并，否则 `null` 会被吞掉）：
 * - `undefined`（未传）→ 渲染默认占位 `<PermissionDenied />`；
 * - `null` → **显式不渲染**任何占位（用于「整个入口都不该存在」的场景）；
 * - 任意节点 → 渲染该自定义占位。
 */
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
    return <>{fallback === undefined ? <PermissionDenied code={code} /> : fallback}</>;
  }
  return <>{children}</>;
}
