import { useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Server } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ConnectorsTab } from "@/components/agents/ConnectorsTab";
import { CreateAgentWizard } from "@/components/agents/CreateAgentWizard";
import { ExpertsTab } from "@/components/agents/ExpertsTab";
import { SkillsTab } from "@/components/agents/SkillsTab";
import { PageContainer } from "@/components/layout/PageContainer";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgents } from "@/hooks/useAgents";
import { useMcpServers } from "@/hooks/useMcp";
import { useSkills } from "@/hooks/useSkills";
import { useTranslation } from "@/i18n";
import { queryKeys } from "@/lib/query";

/**
 * 智能页 Tab 键（V0.4.5 B4 · F-22；URL 契约 `/agents?tab=<AgentsTab>`，缺省 `experts`）。
 */
export type AgentsTab = "experts" | "skills" | "connectors";

/** 三 Tab 定义（顺序冻结：专家 → 技能 → 连接器）。 */
const AGENTS_TABS: readonly { value: AgentsTab; labelKey: string }[] = [
  { value: "experts", labelKey: "agents.tab.experts" },
  { value: "skills", labelKey: "agents.tab.skills" },
  { value: "connectors", labelKey: "agents.tab.connectors" },
];

/** 类型守卫：`value` 是否为合法 Tab（非法 → 回落 `experts`）。 */
function isAgentsTab(value: string | null): value is AgentsTab {
  return value === "experts" || value === "skills" || value === "connectors";
}

/** 页头主按钮定义（随 Tab 切换 label / onClick / testid）。 */
interface HeaderAction {
  /** testid（沿用各 Tab 既有入口契约：`toggle-wizard` / `agents-skills-add` / `agents-connectors-manage-mcp`）。 */
  testId: string;
  /** 按钮文案（已翻译）。 */
  label: string;
  /** 点击回调。 */
  onClick: () => void;
}

/**
 * 专家与智能体页（V0.4.5 B4 三 Tab 宿主；V0.4.6 B-14 专家 Tab 改版 + B-15 三 Tab 统一改版）。
 *
 * B-15（v3 设计）：
 * - **Tab 条恢复 pill 式**（`ui/tabs` 原生样式），计数胶囊保留并入标签（未加载显示 `–`）；
 * - **H1 / 副标题随 Tab**：专家 / 技能 / 连接器（`agents.tabTitle.*` + 各自副标题）；
 * - **页头主按钮随 Tab**：专家=创建专家（向导）/ 技能=添加技能 / 连接器=MCP 服务管理；
 *   技能 `addOpen` 与连接器 `manageOpen` 状态提升到本宿主，受控下传；
 * - **刷新随 Tab**：失效当前 Tab 对应 queryKey（agents / skills / mcpServers）。
 *
 * `data-testid`：`agents-tabs` / `agents-tab-<tab>` / `agents-tab-count-<tab>` /
 * `agents-panel-<tab>` / `agents-refresh` / `toggle-wizard` / `agents-skills-add` /
 * `agents-connectors-manage-mcp`。
 */
export function Agents() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showWizard, setShowWizard] = useState(false);
  // B-15：技能「添加技能」/ 连接器「MCP 服务管理」弹窗开合提升到宿主（页头主按钮共用）。
  const [skillsAddOpen, setSkillsAddOpen] = useState(false);
  const [connectorsManageOpen, setConnectorsManageOpen] = useState(false);

  // 读 `?tab=`（缺省 experts）；非法值回落 experts。
  const rawTab = searchParams.get("tab");
  const tab: AgentsTab = isAgentsTab(rawTab) ? rawTab : "experts";

  // Tab 计数来源：三份列表查询（与各 Tab 面板共用同一 query，天然去重）。
  const { data: agentsData } = useAgents();
  const { data: skillsData } = useSkills();
  const { data: mcpData } = useMcpServers();
  const tabCounts: Record<AgentsTab, number | null> = {
    experts: agentsData ? agentsData.length : null,
    skills: skillsData ? skillsData.length : null,
    connectors: mcpData ? mcpData.length : null,
  };

  /** 切换 Tab 并同步 URL（`replace`，避免污染历史）。 */
  const setTab = (next: string): void => {
    if (!isAgentsTab(next)) {
      return;
    }
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  /** 刷新：失效**当前 Tab** 对应的列表 query。 */
  const refreshCurrentTab = (): void => {
    const queryKey =
      tab === "experts"
        ? queryKeys.agents
        : tab === "skills"
          ? queryKeys.skills
          : queryKeys.mcpServers;
    void queryClient.invalidateQueries({ queryKey });
  };

  /** 页头主按钮随 Tab（一个按钮，label / onClick / testid 随 tab）。 */
  const headerAction: HeaderAction =
    tab === "experts"
      ? {
          testId: "toggle-wizard",
          label: t("agents.create"),
          onClick: () => setShowWizard(true),
        }
      : tab === "skills"
        ? {
            testId: "agents-skills-add",
            label: t("agents.skills.add"),
            onClick: () => setSkillsAddOpen(true),
          }
        : {
            testId: "agents-connectors-manage-mcp",
            label: t("agents.mcp.title"),
            onClick: () => setConnectorsManageOpen(true),
          };

  return (
    <PageContainer width="content">
      <div className="space-y-3">
        {/* ===== 页头：标题随 Tab + 副标题随 Tab + 刷新 + 当前 Tab 主按钮 ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{t(`agents.tabTitle.${tab}`)}</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              {tab === "experts"
                ? t("agents.subtitle")
                : tab === "skills"
                  ? t("agents.subtitleSkills")
                  : t("agents.subtitleConnectors")}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            <button
              type="button"
              data-testid="agents-refresh"
              aria-label={t("agents.refresh")}
              title={t("agents.refresh")}
              onClick={refreshCurrentTab}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RefreshCw aria-hidden className="h-4 w-4" />
            </button>
            <button
              type="button"
              data-testid={headerAction.testId}
              onClick={headerAction.onClick}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {tab === "connectors" ? (
                <Server aria-hidden className="h-3.5 w-3.5" />
              ) : (
                <Plus aria-hidden className="h-3.5 w-3.5" />
              )}
              {headerAction.label}
            </button>
          </div>
        </div>

        {/* 创建向导（F-27.2）：Dialog 弹窗承载（专家 Tab 页头主按钮触发）。 */}
        <Dialog open={showWizard} onOpenChange={setShowWizard}>
          <DialogContent data-testid="agents-wizard-dialog" className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t("agents.wizard.title")}</DialogTitle>
              <DialogDescription className="sr-only">{t("agents.wizard.title")}</DialogDescription>
            </DialogHeader>
            {showWizard ? (
              <CreateAgentWizard
                onCreated={(agent) => {
                  setShowWizard(false);
                  navigate(`/agents/${agent.id}`);
                }}
              />
            ) : null}
          </DialogContent>
        </Dialog>

        <Tabs value={tab} onValueChange={setTab}>
          {/* pill 式 Tab 条（`ui/tabs` 原生样式；计数胶囊并入标签）。 */}
          <TabsList data-testid="agents-tabs">
            {AGENTS_TABS.map((item) => {
              const count = tabCounts[item.value];
              return (
                <TabsTrigger
                  key={item.value}
                  value={item.value}
                  data-testid={`agents-tab-${item.value}`}
                  className="group"
                >
                  {t(item.labelKey)}
                  <span
                    data-testid={`agents-tab-count-${item.value}`}
                    className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground group-data-[state=active]:bg-accent/15 group-data-[state=active]:text-primary"
                  >
                    {count === null ? "–" : count}
                  </span>
                </TabsTrigger>
              );
            })}
          </TabsList>

          <TabsContent value="experts" data-testid="agents-panel-experts">
            <ExpertsTab onCreate={() => setShowWizard(true)} />
          </TabsContent>
          <TabsContent value="skills" data-testid="agents-panel-skills">
            <SkillsTab addOpen={skillsAddOpen} onAddOpenChange={setSkillsAddOpen} />
          </TabsContent>
          <TabsContent value="connectors" data-testid="agents-panel-connectors">
            <ConnectorsTab
              manageOpen={connectorsManageOpen}
              onManageOpenChange={setConnectorsManageOpen}
            />
          </TabsContent>
        </Tabs>
      </div>
    </PageContainer>
  );
}
