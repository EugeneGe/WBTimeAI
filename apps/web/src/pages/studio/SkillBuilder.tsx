import { useMemo, useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateSkill,
  useCreateSkillVersion,
  usePublishSkill,
  useSkill,
  useSkillVersions,
  useSkills,
  useUpdateSkill,
} from "@/hooks/useSkills";
import { toApiError } from "@/lib/api";
import type { SkillResponse } from "@/types";

/** 资源清单条目（2a 仅登记元数据；二进制上传归后续阶段）。 */
interface ResourceEntry {
  name: string;
  size: number;
}

/**
 * Skill Builder（W3 / T2-18；设计 §2.3 / §2.12）。
 *
 * - Skill 元数据编辑（展示名 / 描述 / 分类 / 状态）；
 * - 指令编辑（`instructions`）+ 版本创建（`DRAFT`）；
 * - 资源上传（2a **仅登记元数据**：名称 / 大小 → `manifest.resources`）；
 * - 发布（冻结最新 `DRAFT` 版本为 `PUBLISHED`）。
 *
 * 🔴 动作级守卫经 {@link RequirePermission}（`can()`，后端下发 capability 集）。
 */
export function SkillBuilder() {
  const { data: skills, isLoading } = useSkills();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const createSkill = useCreateSkill();

  // 新建 Skill 表单。
  const [newName, setNewName] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newCategory, setNewCategory] = useState("");

  const handleCreate = (): void => {
    if (!newName.trim()) {
      setFeedback("请填写 Skill 名");
      return;
    }
    createSkill.mutate(
      {
        name: newName.trim(),
        display_name: newDisplayName.trim(),
        category: newCategory.trim(),
      },
      {
        onSuccess: (skill) => {
          setNewName("");
          setNewDisplayName("");
          setNewCategory("");
          setSelectedId(skill.id);
          setFeedback("Skill 已创建");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Skill Builder</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="skill-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        {/* 左：列表 + 新建 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Skills</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2" data-testid="skill-list">
                {isLoading ? (
                  <li className="text-sm text-muted-foreground">加载中…</li>
                ) : (skills ?? []).length === 0 ? (
                  <li className="text-sm text-muted-foreground">暂无 Skill</li>
                ) : (
                  (skills ?? []).map((skill) => (
                    <li key={skill.id}>
                      <button
                        type="button"
                        data-testid={`skill-item-${skill.name}`}
                        onClick={() => setSelectedId(skill.id)}
                        className={
                          "w-full rounded-md border p-3 text-left transition-colors hover:bg-accent " +
                          (selectedId === skill.id ? "border-primary" : "")
                        }
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">
                            {skill.display_name || skill.name}
                          </span>
                          <Badge variant="outline">{skill.status}</Badge>
                        </div>
                        {skill.category ? (
                          <p className="mt-1 text-xs text-muted-foreground">{skill.category}</p>
                        ) : null}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>

          <RequirePermission code="skill:create">
            <Card>
              <CardHeader>
                <CardTitle>新建 Skill</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="skill-name">名称</Label>
                  <Input
                    id="skill-name"
                    data-testid="skill-name-input"
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="skill-display-name">展示名</Label>
                  <Input
                    id="skill-display-name"
                    value={newDisplayName}
                    onChange={(event) => setNewDisplayName(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="skill-category">分类</Label>
                  <Input
                    id="skill-category"
                    value={newCategory}
                    onChange={(event) => setNewCategory(event.target.value)}
                  />
                </div>
                <Button
                  size="sm"
                  data-testid="skill-create-submit"
                  onClick={handleCreate}
                  disabled={createSkill.isPending}
                >
                  创建
                </Button>
              </CardContent>
            </Card>
          </RequirePermission>
        </div>

        {/* 右：选中 Skill 编辑区 */}
        <div>
          {selectedId ? (
            <SkillEditor key={selectedId} skillId={selectedId} onFeedback={setFeedback} />
          ) : (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                选择左侧 Skill 以编辑元数据 / 指令 / 版本
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

/** 单个 Skill 的编辑视图（元数据 + 指令 + 资源 + 版本 + 发布）。 */
function SkillEditor({
  skillId,
  onFeedback,
}: {
  skillId: string;
  onFeedback: (message: string) => void;
}) {
  const { data: skill } = useSkill(skillId);
  const { data: versions } = useSkillVersions(skillId);
  const updateSkill = useUpdateSkill();
  const createVersion = useCreateSkillVersion();
  const publishSkill = usePublishSkill();

  const [displayName, setDisplayName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [versionLabel, setVersionLabel] = useState("1.0.0");
  const [instructions, setInstructions] = useState("");
  const [resources, setResources] = useState<ResourceEntry[]>([]);

  const target: SkillResponse | undefined = skill;
  const effectiveDisplayName = displayName ?? target?.display_name ?? "";
  const effectiveDescription = description ?? target?.description ?? "";

  const manifest = useMemo(
    () => (resources.length > 0 ? { resources: resources.map((item) => ({ ...item })) } : {}),
    [resources],
  );

  const handleSaveMeta = (): void => {
    updateSkill.mutate(
      {
        skillId,
        payload: {
          display_name: effectiveDisplayName,
          description: effectiveDescription || null,
        },
      },
      {
        onSuccess: () => onFeedback("元数据已保存"),
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  const handleCreateVersion = (): void => {
    if (!versionLabel.trim()) {
      onFeedback("请填写版本号");
      return;
    }
    createVersion.mutate(
      { skillId, payload: { version: versionLabel.trim(), instructions, manifest } },
      {
        onSuccess: () => {
          setInstructions("");
          setResources([]);
          onFeedback("版本已创建（DRAFT）");
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  const handlePublish = (): void => {
    publishSkill.mutate(skillId, {
      onSuccess: (version) => onFeedback(`已发布版本 ${version.version}`),
      onError: (error) => onFeedback(toApiError(error).message),
    });
  };

  const handleFiles = (fileList: FileList | null): void => {
    if (!fileList) {
      return;
    }
    const picked: ResourceEntry[] = Array.from(fileList).map((file) => ({
      name: file.name,
      size: file.size,
    }));
    setResources((prev) => [...prev, ...picked]);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>元数据</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="edit-display-name">展示名</Label>
            <Input
              id="edit-display-name"
              value={effectiveDisplayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-description">描述</Label>
            <textarea
              id="edit-description"
              className="min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={effectiveDescription}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <RequirePermission code="skill:update">
            <Button size="sm" onClick={handleSaveMeta} disabled={updateSkill.isPending}>
              保存元数据
            </Button>
          </RequirePermission>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>指令与资源</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="version-label">版本号</Label>
            <Input
              id="version-label"
              value={versionLabel}
              onChange={(event) => setVersionLabel(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="skill-instructions">指令</Label>
            <textarea
              id="skill-instructions"
              data-testid="skill-instructions-input"
              className="min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="Skill 指令文本…"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="skill-resources">资源清单（2a 仅登记元数据）</Label>
            <Input
              id="skill-resources"
              data-testid="skill-resources-input"
              type="file"
              multiple
              onChange={(event) => handleFiles(event.target.files)}
            />
            {resources.length > 0 ? (
              <ul className="text-xs text-muted-foreground" data-testid="skill-resource-list">
                {resources.map((item) => (
                  <li key={`${item.name}-${item.size}`}>
                    {item.name}（{item.size} B）
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <RequirePermission code="skill:update">
            <Button
              size="sm"
              data-testid="skill-version-submit"
              onClick={handleCreateVersion}
              disabled={createVersion.isPending}
            >
              创建版本
            </Button>
          </RequirePermission>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>版本</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <ul className="space-y-2" data-testid="skill-version-list">
            {(versions ?? []).length === 0 ? (
              <li className="text-sm text-muted-foreground">暂无版本</li>
            ) : (
              (versions ?? []).map((version) => (
                <li
                  key={version.id}
                  className="flex items-center justify-between rounded-md border p-3"
                >
                  <span className="text-sm">{version.version}</span>
                  <Badge variant={version.status === "PUBLISHED" ? "default" : "secondary"}>
                    {version.status}
                  </Badge>
                </li>
              ))
            )}
          </ul>
          <RequirePermission code="skill:publish">
            <Button
              size="sm"
              data-testid="skill-publish-submit"
              onClick={handlePublish}
              disabled={publishSkill.isPending}
            >
              发布最新版本
            </Button>
          </RequirePermission>
        </CardContent>
      </Card>
    </div>
  );
}
