import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePermissionCheck } from "@/hooks/usePermissionCheck";
import { useTranslation } from "@/i18n";
import type { AgentStudioPanelProps } from "@/types";

/** Studio 关注的 capability 清单（后端为唯一判定源；此处仅展示判定结果）。 */
const CAPABILITIES = [
  "agent:read",
  "agent:update",
  "agent:publish",
  "skill:create",
  "skill:publish",
  "tool:execute",
  "mcp:create",
  "mcp:delete",
  "knowledge:create",
  "memory:delete",
] as const;

/** 单条 capability：展示后端判定结果（`can()`）+ 草稿声明开关。 */
function CapabilityRow({
  cap,
  declared,
  onToggle,
}: {
  cap: string;
  declared: boolean;
  onToggle: (cap: string) => void;
}) {
  const check = usePermissionCheck(cap);
  const { t } = useTranslation();
  return (
    <li className="flex items-center gap-2" data-testid={`perm-row-${cap}`}>
      <input
        id={`perm-declare-${cap}`}
        data-testid={`perm-declare-${cap}`}
        type="checkbox"
        checked={declared}
        onChange={() => onToggle(cap)}
      />
      <label htmlFor={`perm-declare-${cap}`} className="text-sm">
        {cap}
      </label>
      {check.data ? (
        <Badge variant={check.data.allowed ? "default" : "secondary"}>
          {check.data.allowed
            ? t("studio.panel.permission.allowed")
            : t("studio.panel.permission.denied")}
        </Badge>
      ) : null}
    </li>
  );
}

/**
 * Permission 面板（W8 / T2-41；设计 §2.13 / §2.10.2）。
 *
 * - 展示后端对一组 capability 的**判定结果**（`GET /permissions/check`，唯一真相源）；
 * - 维护 Agent 的**权限声明**（写入草稿 `declaredCapabilities` → 发布落
 *   `runtime_config.capabilities`）。
 *
 * 🔴 前端**不做**本地 capability 推断（W3 裁定 §4.2）。
 */
export function Permission({ draft, onDraftChange }: AgentStudioPanelProps) {
  const { t } = useTranslation();
  const toggle = (cap: string): void => {
    onDraftChange({
      declaredCapabilities: draft.declaredCapabilities.includes(cap)
        ? draft.declaredCapabilities.filter((item) => item !== cap)
        : [...draft.declaredCapabilities, cap],
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-permission">
      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.permission.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">{t("studio.panel.permission.note")}</p>
          <ul className="space-y-2">
            {CAPABILITIES.map((cap) => (
              <CapabilityRow
                key={cap}
                cap={cap}
                declared={draft.declaredCapabilities.includes(cap)}
                onToggle={toggle}
              />
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
