import { Pencil, Play } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useTranslation } from "@/i18n";
import {
  agentDisplayStatus,
  agentStatusLabel,
  agentTypeLabel,
  formatAgentUpdatedAt,
  type AgentDisplayStatus,
} from "@/lib/agentDisplay";
import { cn } from "@/lib/cn";
import type { AgentResponse } from "@/types";

/** 状态徽标配色（D-UI 优化波：金底 / 绿底 / 灰底，不用告警红绿块）。 */
const STATUS_BADGE_CLASS: Record<AgentDisplayStatus, string> = {
  draft: "border-[#EBD9AC] bg-[#FDF6E6] text-[#8A6322]",
  published: "border-[#C9DFD2] bg-[#F0F7F3] text-[#4A7C63]",
  archived: "border-border bg-muted text-muted-foreground",
  unknown: "border-border bg-muted text-muted-foreground",
};

/**
 * 状态徽标（内联 `span`，**不改** `ui/badge` 原语）。
 *
 * 带 `aria-label="状态：<文案>"`，避免读屏只听到「草稿」两字而丢失语义。
 */
export function AgentStatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation();
  const display = agentDisplayStatus(status);
  const label = agentStatusLabel(status, t);
  return (
    <span
      aria-label={t("agents.status.aria", { status: label })}
      className={cn(
        "flex-none whitespace-nowrap rounded-full border px-1.5 py-px text-[10px] font-medium leading-4",
        STATUS_BADGE_CLASS[display],
      )}
    >
      {label}
    </span>
  );
}

/** {@link ExpertCard} 属性。 */
export interface ExpertCardProps {
  /** Agent 响应（专家列表项）。 */
  agent: AgentResponse;
  /** 参照时刻（测试注入固定值，保证相对时间可断言）。 */
  now?: Date;
}

/**
 * 专家卡（V0.4.6 · D-UI 优化波 · D3）。
 *
 * 四层信息：头像 + 名称 + 状态徽标 → 类型与相对更新时间 → 两行描述 → 主操作 + 详情。
 * 主操作随状态切换（D3）：
 * - 已发布（`ACTIVE`）→「开始对话」→ `/chat?agent=<id>`；
 * - 草稿（`DRAFT`）→「完善并发布」→ `/agents/<id>`；
 * - 已归档（`ARCHIVED`）→ 不提供主操作，灰字「已归档，仅可查看」。
 *
 * 交互：整卡可点（`role="link"` + `tabIndex=0` + Enter）进详情；内部按钮 `stopPropagation`。
 *
 * `data-testid`：`agent-card-<id>` / `agent-card-primary-<id>`。
 */
export function ExpertCard({ agent, now }: ExpertCardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const detailPath = `/agents/${agent.id}`;
  const display = agentDisplayStatus(agent.status);
  const meta = agentTypeLabel(agent.type, t);
  const updatedAt = formatAgentUpdatedAt(agent, t, now);

  /** 整卡进入详情。 */
  const openDetail = (): void => {
    navigate(detailPath);
  };

  /** 主操作分发（按真实 `status`）。 */
  const runPrimaryAction = (): void => {
    if (display === "published") {
      navigate(`/chat?agent=${agent.id}`);
      return;
    }
    if (display === "draft") {
      navigate(detailPath);
    }
  };

  return (
    <article
      role="link"
      tabIndex={0}
      aria-label={agent.name}
      data-testid={`agent-card-${agent.id}`}
      onClick={openDetail}
      onKeyDown={(event) => {
        // 键盘冲突守卫：焦点在卡内按钮（开始对话 / 完善并发布）时，Enter 属于该按钮，
        // 整卡不得抢走（否则 `preventDefault` 会抑制按钮的合成 click）。
        if (event.target !== event.currentTarget) {
          return;
        }
        if (event.key === "Enter") {
          event.preventDefault();
          openDetail();
        }
      }}
      className="group flex min-h-[156px] cursor-pointer flex-col rounded-xl border border-border bg-card p-3 transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:border-input hover:shadow-[0_5px_16px_rgba(23,50,92,0.09)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {/* 头部：头像 + 名称 + 状态徽标 + 类型/时间 */}
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="flex h-9 w-9 flex-none items-center justify-center rounded-[10px] bg-primary text-sm font-medium text-primary-foreground"
        >
          {agent.name.slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-sm font-semibold text-foreground">{agent.name}</span>
            <AgentStatusBadge status={agent.status} />
          </div>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {updatedAt === null ? meta : `${meta} · ${updatedAt}`}
          </p>
        </div>
      </div>

      {/* 描述（两行截断） */}
      <p className="mt-2 line-clamp-2 min-h-[35px] text-xs leading-relaxed text-muted-foreground">
        {agent.description?.trim() ? agent.description : t("agents.experts.noDescription")}
      </p>

      {/* 底部：主操作 + 详情 */}
      <div className="mt-auto flex items-center gap-2 border-t border-border pt-2">
        {display === "published" ? (
          <button
            type="button"
            data-testid={`agent-card-primary-${agent.id}`}
            onClick={(event) => {
              event.stopPropagation();
              runPrimaryAction();
            }}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Play aria-hidden className="h-3 w-3" />
            {t("agents.card.openChat")}
          </button>
        ) : null}

        {display === "draft" ? (
          <button
            type="button"
            data-testid={`agent-card-primary-${agent.id}`}
            onClick={(event) => {
              event.stopPropagation();
              runPrimaryAction();
            }}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Pencil aria-hidden className="h-3 w-3" />
            {t("agents.card.completePublish")}
          </button>
        ) : null}

        {display === "archived" ? (
          <span
            data-testid={`agent-card-primary-${agent.id}`}
            aria-disabled
            className="text-xs text-muted-foreground"
          >
            {t("agents.card.archivedOnly")}
          </span>
        ) : null}

        {/* 未知状态（后端新增枚举）：不给主操作，仅可查看详情，避免死按钮。 */}
        {display === "unknown" ? (
          <span className="text-xs text-muted-foreground">{agentStatusLabel(agent.status, t)}</span>
        ) : null}

        <span
          aria-hidden
          className="ml-auto whitespace-nowrap text-xs text-muted-foreground transition-colors group-hover:text-foreground"
        >
          {t("agents.card.detail")} →
        </span>
      </div>
    </article>
  );
}
