import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { Link } from "react-router-dom";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateStudioAgent,
  usePublishAgentDraft,
  useStudioAgentVersions,
  useStudioAgents,
} from "@/hooks/useAgentStudio";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  AGENT_STUDIO_PANELS,
  agentVersionToDraft,
  createEmptyAgentStudioDraft,
  type AgentStudioDraft,
  type AgentStudioPanelId,
  type AgentStudioPanelProps,
} from "@/types";

import { Basic } from "./panels/Basic";
import { Knowledge } from "./panels/Knowledge";
import { Mcp } from "./panels/Mcp";
import { Memory } from "./panels/Memory";
import { Model } from "./panels/Model";
import { Permission } from "./panels/Permission";
import { Prompt } from "./panels/Prompt";
import { Skills } from "./panels/Skills";
import { Tools } from "./panels/Tools";

/** 九分区 → 面板组件映射（顺序见 {@link AGENT_STUDIO_PANELS}）。 */
const PANEL_COMPONENTS: Record<AgentStudioPanelId, ComponentType<AgentStudioPanelProps>> = {
  basic: Basic,
  model: Model,
  prompt: Prompt,
  skills: Skills,
  tools: Tools,
  mcp: Mcp,
  knowledge: Knowledge,
  memory: Memory,
  permission: Permission,
};

/**
 * Studio Hub 子页入口（D-UI 体验优化波 · WS-P3a / DU-8）。
 *
 * 补齐「Studio 子页无入口」缺口：左栏在九分区（本页内切换）之外，再给出一组
 * 链至各 Studio 子页的 hub 导航。
 *
 * 🔴 模块顶层**不**取 `t`：此处只存 `labelKey`，文案在组件内 `t(link.labelKey)` 解析；
 *    `Marketplace` / `Skill Builder` / `MCP Manager` 为产品技术名（两语言一致）→ 原样保留。
 */
const STUDIO_HUB_LINKS = [
  // 三条已重定向（router.tsx：/studio/marketplace|skills → /agents?tab=skills；
  // /studio/mcp → /agents?tab=connectors）：直指重定向后的目标，省一次跳转。
  { key: "marketplace", to: "/agents?tab=skills", label: "Marketplace" },
  { key: "evaluation", to: "/studio/evaluation", labelKey: "studio.hub.evaluation" },
  { key: "skills", to: "/agents?tab=skills", label: "Skill Builder" },
  { key: "mcp", to: "/agents?tab=connectors", label: "MCP Manager" },
  { key: "workflows", to: "/studio/workflows", labelKey: "studio.hub.workflows" },
  { key: "knowledge", to: "/studio/knowledge", labelKey: "studio.hub.knowledge" },
  { key: "memory", to: "/studio/memory", labelKey: "studio.hub.memory" },
] as const;

/**
 * Agent Studio 主框架（W8 / T2-41；设计 §2.13 · 屏幕 04-AgentStudio-三栏）。
 *
 * - **左栏（190）**：九分区导航（Basic / Model / Prompt / Skills / Tools / MCP /
 *   Knowledge / Memory / Permission）+ Studio Hub 子页入口；
 * - **中栏（1fr）**：渲染当前分区面板（各面板编辑同一份 {@link AgentStudioDraft}）；
 * - **右栏（280）**：合成配置摘要 + 发布新版本（一次发布 = 一个新 `agent_version`）。
 *
 * D-UI WS-P3a：宽档容器（{@link PageContainer} `width="wide"`）+ 三栏重排；
 * 既有 `data-testid` 全保留；数据流与 API 调用不变。
 */
export function AgentStudio() {
  const { t } = useTranslation();
  const [activePanel, setActivePanel] = useState<AgentStudioPanelId>("basic");
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AgentStudioDraft>(createEmptyAgentStudioDraft);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [newAgentName, setNewAgentName] = useState("");

  const { data: agents } = useStudioAgents();
  const { data: versions } = useStudioAgentVersions(selectedAgentId);
  const createAgent = useCreateStudioAgent();
  const publishDraft = usePublishAgentDraft();

  const selectedAgent = (agents ?? []).find((item) => item.id === selectedAgentId) ?? null;
  const currentVersionId = selectedAgent?.current_version_id ?? null;

  // 选中 Agent 后，以其当前版本（若有）载入草稿。
  useEffect(() => {
    if (!selectedAgentId || !versions) {
      return;
    }
    const current = versions.find((item) => item.id === currentVersionId) ?? versions[0];
    if (current) {
      setDraft(agentVersionToDraft(current));
    }
  }, [selectedAgentId, currentVersionId, versions]);

  const handleSelectAgent = (agentId: string): void => {
    setSelectedAgentId(agentId);
    setDraft(createEmptyAgentStudioDraft());
    setFeedback(null);
  };

  const handleDraftChange = (patch: Partial<AgentStudioDraft>): void => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const handleCreate = (): void => {
    if (!newAgentName.trim()) {
      setFeedback(t("studio.feedback.nameRequired"));
      return;
    }
    createAgent.mutate(
      { name: newAgentName.trim(), type: "PRIMARY" },
      {
        onSuccess: (agent) => {
          setNewAgentName("");
          setSelectedAgentId(agent.id);
          setDraft(createEmptyAgentStudioDraft());
          setFeedback(t("studio.feedback.created"));
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handlePublish = (): void => {
    if (!selectedAgentId) {
      setFeedback(t("studio.feedback.selectRequired"));
      return;
    }
    publishDraft.mutate(
      { id: selectedAgentId, draft },
      {
        onSuccess: (version) =>
          setFeedback(t("studio.feedback.published", { version: version.version })),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const ActivePanel = PANEL_COMPONENTS[activePanel];

  return (
    <PageContainer width="wide">
      <div className="space-y-4" data-testid="agent-studio">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Agent Studio</h1>
          {feedback ? (
            <span className="text-xs text-muted-foreground" data-testid="studio-feedback">
              {feedback}
            </span>
          ) : null}
        </div>

        {/* 选择 / 新建 Agent（列表 R + 创建 C） */}
        <Card>
          <CardHeader>
            <CardTitle>{t("studio.select.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2" data-testid="studio-agent-list">
              {(agents ?? []).length === 0 ? (
                <span className="text-sm text-muted-foreground">{t("studio.select.empty")}</span>
              ) : (
                (agents ?? []).map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    data-testid={`studio-agent-${agent.id}`}
                    onClick={() => handleSelectAgent(agent.id)}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm transition-colors hover:bg-accent",
                      selectedAgentId === agent.id ? "border-primary" : "",
                    )}
                  >
                    {agent.name}
                  </button>
                ))
              )}
            </div>
            <RequirePermission code="agent:create">
              <div className="flex items-end gap-2 border-t pt-3">
                <div className="space-y-2">
                  <Label htmlFor="studio-agent-name">{t("studio.create.label")}</Label>
                  <Input
                    id="studio-agent-name"
                    data-testid="studio-agent-name-input"
                    value={newAgentName}
                    onChange={(event) => setNewAgentName(event.target.value)}
                    placeholder={t("studio.create.placeholder")}
                  />
                </div>
                <Button
                  size="sm"
                  data-testid="studio-create-agent"
                  onClick={handleCreate}
                  disabled={createAgent.isPending}
                >
                  {t("studio.create.submit")}
                </Button>
              </div>
            </RequirePermission>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[190px_1fr_280px]">
          {/* 左：九分区导航 + Studio Hub 入口 */}
          <div className="space-y-4">
            <nav className="space-y-1" data-testid="studio-nav">
              {AGENT_STUDIO_PANELS.map((panel) => (
                <button
                  key={panel.id}
                  type="button"
                  data-testid={`studio-nav-${panel.id}`}
                  onClick={() => setActivePanel(panel.id)}
                  aria-current={activePanel === panel.id ? "true" : undefined}
                  className={cn(
                    "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                    activePanel === panel.id ? "border-primary bg-accent" : "",
                  )}
                >
                  <span className="font-medium">{panel.label}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {t(panel.descriptionKey)}
                  </span>
                </button>
              ))}
            </nav>

            <div className="border-t pt-3">
              <p className="px-3 pb-1 text-xs font-medium text-muted-foreground">Studio</p>
              <nav
                className="space-y-1"
                data-testid="studio-hub-nav"
                aria-label={t("studio.hubNavLabel")}
              >
                {STUDIO_HUB_LINKS.map((link) => (
                  <Link
                    key={link.key}
                    to={link.to}
                    data-testid={`studio-hub-${link.key}`}
                    className="block rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {"label" in link ? link.label : t(link.labelKey)}
                  </Link>
                ))}
                {selectedAgentId ? (
                  <Link
                    to={`/studio/agents/${selectedAgentId}`}
                    data-testid="studio-hub-versions"
                    className="block rounded-lg px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {t("studio.hub.versions")}
                  </Link>
                ) : null}
              </nav>
            </div>
          </div>

          {/* 中：当前分区面板 */}
          <div key={selectedAgentId ?? "none"}>
            <ActivePanel
              agent={selectedAgent}
              draft={draft}
              onDraftChange={handleDraftChange}
              onFeedback={setFeedback}
            />
          </div>

          {/* 右：配置与预览 + 发布 */}
          <aside className="space-y-4">
            <Card data-testid="studio-preview">
              <CardHeader>
                <CardTitle>{t("studio.preview.title")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Agent</span>
                  <span data-testid="studio-preview-agent">{selectedAgent?.name ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("studio.preview.status")}</span>
                  <Badge variant="outline">{selectedAgent?.status ?? "—"}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">
                    {t("studio.preview.currentVersion")}
                  </span>
                  <span className="font-mono text-xs">{currentVersionId ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("studio.preview.model")}</span>
                  <span className="font-mono text-xs" data-testid="studio-preview-model">
                    {typeof draft.modelConfig.model === "string" && draft.modelConfig.model
                      ? draft.modelConfig.model
                      : "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">System Prompt</span>
                  <span className="text-xs">
                    {t("studio.preview.systemPromptLength", { count: draft.systemPrompt.length })}
                  </span>
                </div>
                <ul className="space-y-1 border-t pt-3 text-xs">
                  <li className="flex items-center justify-between">
                    <span className="text-muted-foreground">Skills</span>
                    <span data-testid="studio-preview-skills">{draft.skillIds.length}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span className="text-muted-foreground">Tools</span>
                    <span data-testid="studio-preview-tools">{draft.toolIds.length}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span className="text-muted-foreground">MCP</span>
                    <span data-testid="studio-preview-mcp">{draft.mcpServerIds.length}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span className="text-muted-foreground">Knowledge</span>
                    <span data-testid="studio-preview-kb">{draft.knowledgeBaseIds.length}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span className="text-muted-foreground">
                      {t("studio.preview.capabilities")}
                    </span>
                    <span data-testid="studio-preview-caps">
                      {draft.declaredCapabilities.length}
                    </span>
                  </li>
                </ul>

                <RequirePermission code="agent:publish">
                  <Button
                    size="sm"
                    data-testid="studio-publish"
                    onClick={handlePublish}
                    disabled={!selectedAgentId || publishDraft.isPending}
                  >
                    {t("studio.preview.publish")}
                  </Button>
                </RequirePermission>

                {selectedAgentId ? (
                  <Link
                    className="block text-xs text-primary underline-offset-4 hover:underline"
                    data-testid="studio-open-versions"
                    to={`/studio/agents/${selectedAgentId}`}
                  >
                    {t("studio.preview.openVersions")}
                  </Link>
                ) : null}
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </PageContainer>
  );
}
