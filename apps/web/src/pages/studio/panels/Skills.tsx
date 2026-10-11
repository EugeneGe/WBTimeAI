import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateSkill, useSkills } from "@/hooks/useSkills";
import { toApiError } from "@/lib/api";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Skills 面板（W8 / T2-41；设计 §2.13）。
 *
 * - **绑定** Skill（多选，写入草稿 `skillIds` → 发布落 `runtime_config.skill_ids`）；
 * - **创建** Skill（复用既有 Skill 服务，`RequirePermission` = `skill:create`）。
 *
 * 🔴 复用既有能力（`services/skill.ts`），本面板不重复实现后端能力。
 */
export function Skills({ draft, onDraftChange, onFeedback }: AgentStudioPanelProps) {
  const { data: skills, isLoading } = useSkills();
  const createSkill = useCreateSkill();
  const [newName, setNewName] = useState("");

  const toggle = (skillId: string): void => {
    onDraftChange({
      skillIds: draft.skillIds.includes(skillId)
        ? draft.skillIds.filter((id) => id !== skillId)
        : [...draft.skillIds, skillId],
    });
  };

  const handleCreate = (): void => {
    if (!newName.trim()) {
      onFeedback("请填写 Skill 名");
      return;
    }
    createSkill.mutate(
      { name: newName.trim() },
      {
        onSuccess: (skill) => {
          setNewName("");
          onDraftChange({ skillIds: [...draft.skillIds, skill.id] });
          onFeedback("Skill 已创建并绑定");
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="panel-skills">
      <Card>
        <CardHeader>
          <CardTitle>绑定 Skill</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (skills ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无 Skill</p>
          ) : (
            <ul className="space-y-2">
              {(skills ?? []).map((skill) => (
                <li key={skill.id} className="flex items-center gap-2">
                  <input
                    id={`skill-bind-${skill.name}`}
                    data-testid={`skill-bind-${skill.name}`}
                    type="checkbox"
                    checked={draft.skillIds.includes(skill.id)}
                    onChange={() => toggle(skill.id)}
                  />
                  <label htmlFor={`skill-bind-${skill.name}`} className="text-sm">
                    {skill.display_name || skill.name}
                  </label>
                  <Badge variant="outline">{skill.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <RequirePermission code="skill:create">
        <Card>
          <CardHeader>
            <CardTitle>新建 Skill</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="panel-skill-name">名称</Label>
              <Input
                id="panel-skill-name"
                data-testid="panel-skill-name-input"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              data-testid="panel-skill-create"
              onClick={handleCreate}
              disabled={createSkill.isPending}
            >
              创建并绑定
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>
    </div>
  );
}
