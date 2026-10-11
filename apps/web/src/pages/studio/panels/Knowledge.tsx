import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateKnowledgeBase, useKnowledgeBases } from "@/hooks/useKnowledge";
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
      onFeedback("请填写知识库名");
      return;
    }
    createBase.mutate(
      { name: newName.trim() },
      {
        onSuccess: (base) => {
          setNewName("");
          onDraftChange({ knowledgeBaseIds: [...draft.knowledgeBaseIds, base.id] });
          onFeedback("知识库已创建并绑定");
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="panel-knowledge">
      <Card>
        <CardHeader>
          <CardTitle>绑定知识库</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (bases ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无知识库</p>
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
            <CardTitle>新建知识库</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="panel-kb-name">名称</Label>
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
              创建并绑定
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>
    </div>
  );
}
