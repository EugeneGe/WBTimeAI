import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { skillService } from "@/services/skill";
import { useAuthStore } from "@/stores/authStore";
import type {
  CreateSkillRequest,
  CreateSkillVersionRequest,
  SkillResponse,
  UpdateSkillRequest,
} from "@/types";

/**
 * Skill hooks（TanStack Query；W3 / T2-18；设计 §2.3）。
 *
 * 服务状态唯一真相源；`enabled` 依认证态（对齐 `hooks/useTools.ts` 范式）。
 */

/** Skill 列表。 */
export function useSkills() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.skills,
    queryFn: () => skillService.list(),
    enabled: isAuthenticated,
  });
}

/** Skill 详情（`skillId` 为空时不请求）。 */
export function useSkill(skillId: string | null) {
  return useQuery({
    queryKey: queryKeys.skill(skillId ?? ""),
    queryFn: () => skillService.get(skillId as string),
    enabled: Boolean(skillId),
  });
}

/** Skill 版本列表（`skillId` 为空时不请求）。 */
export function useSkillVersions(skillId: string | null) {
  return useQuery({
    queryKey: queryKeys.skillVersions(skillId ?? ""),
    queryFn: () => skillService.listVersions(skillId as string),
    enabled: Boolean(skillId),
  });
}

/** 创建 Skill mutation。 */
export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateSkillRequest) => skillService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
    },
  });
}

/** 更新 Skill mutation。 */
export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, payload }: { skillId: string; payload: UpdateSkillRequest }) =>
      skillService.update(skillId, payload),
    onSuccess: (skill) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(skill.id) });
    },
  });
}

/** 创建 Skill 版本 mutation。 */
export function useCreateSkillVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, payload }: { skillId: string; payload: CreateSkillVersionRequest }) =>
      skillService.createVersion(skillId, payload),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillVersions(version.skill_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(version.skill_id) });
    },
  });
}

/** 发布 Skill 版本 mutation。 */
export function usePublishSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) => skillService.publish(skillId),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(version.skill_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillVersions(version.skill_id) });
    },
  });
}

/**
 * 技能列表项（UI 投影；V0.4.5 B4 · F-22.4）。
 *
 * `enabled` 为**本地态占位**（后端 `SkillResponse` 无启用字段；技能页开关仅 UI 骨架，
 * 不落库，登记遗留）。
 */
export interface SkillListItem {
  /** 技能 id（`agents-skill-toggle-<id>` 等 testid 使用）。 */
  id: string;
  /** 技能名（稳定标识）。 */
  name: string;
  /** 展示名（缺省回落 `name`）。 */
  displayName: string;
  /** 描述（B-15：搜索命中 + 展示兜底；可空串）。 */
  description: string;
  /** 分类。 */
  category: string;
  /** 状态（`DRAFT` / `PUBLISHED` …）。 */
  status: string;
  /** 启用态（本地占位，默认 `true`）。 */
  enabled: boolean;
  /** 创建时间（B-15：卡片 meta 相对时间；可空）。 */
  createdAt: string | null;
}

/**
 * 将服务端 Skill 列表映射为技能页 UI 列表项（F-22.4；`enabled` 默认 `true`）。
 *
 * @param skills `useSkills()` 返回的技能列表（可空）。
 * @returns UI 列表项数组（空输入 → 空数组）。
 */
export function toSkillListItems(skills: SkillResponse[] | undefined | null): SkillListItem[] {
  return (skills ?? []).map((skill) => ({
    id: skill.id,
    name: skill.name,
    displayName: skill.display_name || skill.name,
    description: skill.description ?? "",
    category: skill.category ?? "",
    status: skill.status,
    enabled: true,
    createdAt: skill.created_at ?? null,
  }));
}
