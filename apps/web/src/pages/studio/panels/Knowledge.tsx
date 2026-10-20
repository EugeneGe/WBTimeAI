import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateKnowledgeBase, useKnowledgeBases } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Knowledge 面板（W8 / T2-41；设计 §2.13）。
 *
 * - **绑定** 知识库（多选，写入草稿 `knowledgeBaseIds` → 发布落
 *   `runtime_config.knowledge_base_ids`）；
 * - **创建** 知识库（复用既有 Knowledge 服务；`RequirePermission` = `knowledge:create`）。
 */
export function Knowledge({ draft, onDraftChange, onFeedback }: AgentStudioPanelProps) {
  const { t } = useTranslation();
  const { data: bases, isLoading } = useKnowledgeBases();
  const createBase = useCreateKnowledgeBase();
  const [newName, setNewName] = useState("");

  const toggle = (baseId: string): void => {
    onDraftChange({
      knowledgeBaseIds: draft.knowledgeBaseIds.includes(baseId)
        ? draft.knowledgeBaseIds.filter((id) => id !== baseId)
        : [...draft.knowledgeBaseIds, baseId],
    });
  };

  const handleCreate = (): void => {
    if (!newName.trim()) {
      onFeedback(t("studio.panel.knowledge.nameRequired"));
      return;
    }
    createBase.mutate(
      { name: newName.trim() },
      {
        onSuccess: (base) => {
          setNewName("");
          onDraftChange({ knowledgeBaseIds: [...draft.knowledgeBaseIds, base.id] });
          onFeedback(t("studio.panel.knowledge.created"));
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="panel-knowledge">
      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.knowledge.bindTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
          ) : (bases ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("studio.panel.knowledge.empty")}</p>
          ) : (
            <ul className="space-y-2">
              {(bases ?? []).map((base) => (
                <li key={base.id} className="flex items-center gap-2">
                  <input
                    id={`kb-bind-${base.name}`}
                    data-testid={`kb-bind-${base.name}`}
                    type="checkbox"
                    checked={draft.knowledgeBaseIds.includes(base.id)}
                    onChange={() => toggle(base.id)}
                  />
                  <label htmlFor={`kb-bind-${base.name}`} className="text-sm">
                    {base.name}
                  </label>
                  <Badge variant="outline">{base.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <RequirePermission code="knowledge:create">
        <Card>
          <CardHeader>
            <CardTitle>{t("studio.panel.knowledge.createTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="panel-kb-name">{t("common.name")}</Label>
              <Input
                id="panel-kb-name"
                data-testid="panel-kb-name-input"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              data-testid="panel-kb-create"
              onClick={handleCreate}
              disabled={createBase.isPending}
            >
              {t("studio.panel.knowledge.createAndBind")}
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>
    </div>
  );
}
