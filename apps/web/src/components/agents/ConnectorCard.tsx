import { Plug } from "lucide-react";

import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import type { MCPServerResponse } from "@/types";

/** {@link ConnectorCard} 属性。 */
export interface ConnectorCardProps {
  /** MCP Server 响应（连接器列表项）。 */
  connector: MCPServerResponse;
}

/**
 * 连接器卡（V0.4.6 B-15 · 三 Tab 统一改版）。
 *
 * 与 {@link ExpertCard} 同规范：圆角 12 / 1px 描边 / hover 抬升 / 最小高 132。
 * 结构：34px 雾蓝图标块（plug）+ 名称 → mono 端点行（`endpoint || command || transport`，沿用
 * 旧口径）→ footer：状态点（绿 = `ACTIVE` / 灰 = 其他）+ 状态文案 + transport tag。
 *
 * 🔴 连接器**只读**：无启停 / 删除 / 测试连接（无后端能力），整卡不可点。
 *
 * `data-testid`：`agents-connector-card-<id>`（沿用）。
 */
export function ConnectorCard({ connector }: ConnectorCardProps) {
  const { t } = useTranslation();
  const enabled = connector.status === "ACTIVE";
  const endpoint = connector.endpoint || connector.command || connector.transport;

  return (
    <article
      data-testid={`agents-connector-card-${connector.id}`}
      className="group flex min-h-[132px] cursor-default flex-col rounded-xl border border-border bg-card p-3 transition-[border-color,box-shadow] duration-150 hover:border-input hover:shadow-[0_5px_16px_rgba(23,50,92,0.09)]"
    >
      {/* 头部：图标块 + 名称 + mono 端点行 */}
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[10px] bg-[#EAF0F8] text-primary"
        >
          <Plug className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{connector.name}</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{endpoint}</p>
        </div>
      </div>

      {/* footer：状态点 + 状态文案 + transport tag */}
      <div className="mt-auto flex items-center gap-2 border-t border-border pt-2">
        <span
          aria-hidden
          className={cn(
            "h-1.5 w-1.5 flex-none rounded-full",
            enabled ? "bg-success" : "bg-muted-foreground/50",
          )}
        />
        <span
          className={cn(
            "whitespace-nowrap text-xs",
            enabled ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {enabled ? t("agents.connectors.statusEnabled") : t("agents.connectors.statusDisabled")}
        </span>
        <span className="ml-auto whitespace-nowrap rounded-full bg-muted px-1.5 py-0.5 font-mono text-[10px] leading-4 text-muted-foreground">
          {connector.transport}
        </span>
      </div>
    </article>
  );
}
