import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { Link } from "react-router-dom";

import { RequirePermission } from "@/components/guards/RequirePermission";
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
 * Agent Studio 主框架（W8 / T2-41；设计 §2.13）。
 *
 * - **左侧九分区**：Basic / Model / Prompt / Skills / Tools / MCP / Knowledge / Memory / Permission；
 * - **中间配置**：渲染当前分区面板（各面板编辑同一份 {@link AgentStudioDraft}）；
 * - **右侧预览与发布**：合成配置摘要 + 发布新版本（一次发布 = 一个新 `agent_version`）。
 *
 * 🔴 与既有 5 个独立 Studio 页（SkillBuilder / McpManager / WorkflowDesigner /
 * KnowledgeManager / MemoryView）**并存**：本页为**新主框架**，九面板复用既有能力与 SDK。
 */
export function AgentStudio() {
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
      setFeedback("请填写 Agent 名称");
      return;
    }
    createAgent.mutate(
      { name: newAgentName.trim(), type: "PRIMARY" },
      {
        onSuccess: (agent) => {
          setNewAgentName("");
          setSelectedAgentId(agent.id);
          setDraft(createEmptyAgentStudioDraft());
          setFeedback("Agent 已创建");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handlePublish = (): void => {
    if (!selectedAgentId) {
      setFeedback("请先选择或创建 Agent");
      return;
    }
    publishDraft.mutate(
      { id: selectedAgentId, draft },
      {
        onSuccess: (version) => setFeedback(`已发布版本 ${version.version}`),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const ActivePanel = PANEL_COMPONENTS[activePanel];

  return (
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
          <CardTitle>选择 Agent</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2" data-testid="studio-agent-list">
            {(agents ?? []).length === 0 ? (
              <span className="text-sm text-muted-foreground">暂无 Agent</span>
            ) : (
              (agents ?? []).map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  data-testid={`studio-agent-${agent.id}`}
                  onClick={() => handleSelectAgent(agent.id)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-accent",
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
                <Label htmlFor="studio-agent-name">新建 Agent</Label>
                <Input
                  id="studio-agent-name"
                  data-testid="studio-agent-name-input"
                  value={newAgentName}
                  onChange={(event) => setNewAgentName(event.target.value)}
                  placeholder="Agent 名称"
                />
              </div>
              <Button
                size="sm"
                data-testid="studio-create-agent"
                onClick={handleCreate}
                disabled={createAgent.isPending}
              >
                创建
              </Button>
            </div>
          </RequirePermission>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[200px_1fr_320px]">
        {/* 左：九分区导航 */}
        <nav className="space-y-1" data-testid="studio-nav">
          {AGENT_STUDIO_PANELS.map((panel) => (
            <button
              key={panel.id}
              type="button"
              data-testid={`studio-nav-${panel.id}`}
              onClick={() => setActivePanel(panel.id)}
              aria-current={activePanel === panel.id ? "true" : undefined}
              className={cn(
                "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                activePanel === panel.id ? "border-primary bg-accent" : "",
              )}
            >
              <span className="font-medium">{panel.label}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {panel.description}
              </span>
            </button>
          ))}
        </nav>

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
              <CardTitle>配置与预览</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Agent</span>
                <span data-testid="studio-preview-agent">{selectedAgent?.name ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">状态</span>
                <Badge variant="outline">{selectedAgent?.status ?? "—"}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">当前版本</span>
                <span className="font-mono text-xs">{currentVersionId ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">模型</span>
                <span className="font-mono text-xs" data-testid="studio-preview-model">
                  {typeof draft.modelConfig.model === "string" && draft.modelConfig.model
                    ? draft.modelConfig.model
                    : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">System Prompt</span>
                <span className="text-xs">{draft.systemPrompt.length} 字符</span>
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
                  <span className="text-muted-foreground">权限声明</span>
                  <span data-testid="studio-preview-caps">{draft.declaredCapabilities.length}</span>
                </li>
              </ul>

              <RequirePermission code="agent:publish">
                <Button
                  size="sm"
                  data-testid="studio-publish"
                  onClick={handlePublish}
                  disabled={!selectedAgentId || publishDraft.isPending}
                >
                  发布新版本
                </Button>
              </RequirePermission>

              {selectedAgentId ? (
                <Link
                  className="block text-xs text-primary underline-offset-4 hover:underline"
                  data-testid="studio-open-versions"
                  to={`/studio/agents/${selectedAgentId}`}
                >
                  查看版本管理 →
                </Link>
              ) : null}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
